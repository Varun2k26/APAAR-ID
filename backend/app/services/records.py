"""Record access with consent enforced at read time (DPDP Act 2023).

  own institution    -> its own enrolment(s) + identity (data fiduciary for that student)
  other institution  -> ONLY the fields in an APPROVED, unexpired consent; otherwise 403
  AICTE              -> full record, purpose required, logged
Every read lands in the hash-chained audit log with the student as subject, so the student's
"who looked at my record" page is generated from the same tamper-evident log.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.deps import Principal
from ..identity.apaar_format import clean, pretty
from ..models import ConsentRequest, Enrollment, Event, Person, utcnow
from . import audit

SHAREABLE_FIELDS = ["name", "dob", "gender", "parent_name", "apaar_id", "institution", "program", "admission_year",
                    "year_of_study", "enrollment_status", "seat_type", "social_category", "nationality", "history"]


def find_person(db: Session, ref: str) -> Person | None:
    ref = (ref or "").strip()
    if ref.upper().startswith("PROV-"):
        return db.execute(select(Person).where(Person.provisional_id == ref.upper())).scalar_one_or_none()
    return db.execute(select(Person).where(Person.apaar_id == clean(ref))).scalar_one_or_none()


def enrollment_view(e: Enrollment, with_history: list | None = None) -> dict:
    d = {"enrollment_id": e.id, "institution": e.institution.name, "institution_code": e.institution.aicte_code,
         "institution_id": e.institution_id, "program": e.program.name, "program_code": e.program.code,
         "roll_no": e.roll_no, "admission_year": e.academic_year, "admission_date": e.admission_date.isoformat(),
         "year_of_study": e.year_of_study, "mode": e.mode, "seat_type": e.seat_type,
         "social_category": e.social_category, "nationality": e.nationality, "enrollment_status": e.status}
    if with_history is not None:
        d["history"] = with_history
    return d


def history(db: Session, enrollment_id: int) -> list[dict]:
    return [{"at": ev.created_at.isoformat(), "type": ev.type, "by": ev.actor, "details": ev.payload}
            for ev in db.execute(select(Event).where(Event.enrollment_id == enrollment_id).order_by(Event.id)).scalars()]


def full_record(db: Session, p: Person, institution_id: int | None = None) -> dict:
    stmt = select(Enrollment).where(Enrollment.person_id == p.id).order_by(Enrollment.id)
    if institution_id is not None:
        stmt = stmt.where(Enrollment.institution_id == institution_id)
    return {"person_id": p.id, "name": p.name, "dob": p.dob.isoformat(), "gender": p.gender, "parent_name": p.parent_name,
            "apaar_id": pretty(p.apaar_id) if p.apaar_id else None, "provisional_id": p.provisional_id,
            "registry_status": p.registry_status,
            "enrollments": [enrollment_view(e, history(db, e.id)) for e in db.execute(stmt).scalars()]}


def active_consent(db: Session, person_id: int, institution_id: int) -> ConsentRequest | None:
    now = utcnow()
    return db.execute(select(ConsentRequest).where(
        ConsentRequest.person_id == person_id, ConsentRequest.requester_institution_id == institution_id,
        ConsentRequest.status == "APPROVED", or_(ConsentRequest.expires_at.is_(None), ConsentRequest.expires_at > now))
        .order_by(ConsentRequest.id.desc())).scalars().first()


def filtered(record: dict, fields: list[str]) -> dict:
    f = set(fields)
    out = {k: v for k, v in record.items() if k in f}
    ens = []
    for e in record["enrollments"]:
        if e["enrollment_status"] not in ("ACTIVE", "GRADUATED", "SUSPENDED"):
            continue
        ens.append({k: v for k, v in e.items() if k in f or k in ("enrollment_status",)})
    out["enrollments"] = ens
    out["_disclosed_fields"] = sorted(f)
    return out


def read_record(db: Session, pr: Principal, ref: str, purpose: str | None) -> dict:
    p = find_person(db, ref)
    if not p:
        raise HTTPException(404, "no student with that APAAR / provisional ID")
    if pr.role == "AICTE_ADMIN":
        if not purpose or len(purpose.strip()) < 5:
            raise HTTPException(400, "AICTE record access requires a stated purpose")
        rec, basis = full_record(db, p), "AICTE oversight"
    elif pr.institution_scoped:
        own = db.execute(select(Enrollment).where(Enrollment.person_id == p.id,
                                                  Enrollment.institution_id == pr.institution_id)).scalars().first()
        if own:
            rec, basis = full_record(db, p, pr.institution_id), "own institution"
        else:
            c = active_consent(db, p.id, pr.institution_id)
            if not c:
                audit.record(db, actor=pr.label, role=pr.role, action="RECORD_READ_DENIED", resource=f"person:{p.id}",
                             subject_person_id=p.id, purpose=purpose, details={"reason": "no consent"})
                db.commit()
                raise HTTPException(403, "consent required: this student is not enrolled with you. Send a consent "
                                         "request; the student decides what to share.")
            rec, basis = filtered(full_record(db, p), c.fields), f"consent #{c.id}"
            purpose = purpose or c.purpose
    else:
        raise HTTPException(403, "record access is not available to this role")
    audit.record(db, actor=pr.label, role=pr.role, action="RECORD_READ", resource=f"person:{p.id}",
                 subject_person_id=p.id, purpose=purpose, details={"basis": basis})
    db.commit()
    rec["_access_basis"] = basis
    return rec


def decide_consent(db: Session, c: ConsentRequest, approve: bool) -> None:
    if c.status != "PENDING":
        raise HTTPException(409, f"consent is already {c.status}")
    c.status, c.decided_at = ("APPROVED" if approve else "DENIED"), utcnow()
    if approve:
        c.expires_at = utcnow() + timedelta(days=c.duration_days)
