"""Student portal, consent, record access, corrections, regulator audit queries, audit log."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth.deps import Principal, assert_inst, current, need
from ..db import get_db
from ..models import (AuditLog, Conflict, ConsentRequest, CorrectionRequest, Enrollment, Institution, Person, Program,
                      Transfer, utcnow)
from ..services import audit, events, records
from ..services.lifecycle import set_status
from ..validation import intake

router = APIRouter(prefix="/api/v1", tags=["people"])


# ---------------------------------------------------------------- student self-service
@router.get("/me/record")
def my_record(p: Principal = Depends(need("self:read")), db: Session = Depends(get_db)):
    pe = db.get(Person, p.person_id)
    rec = records.full_record(db, pe)
    rec["open_conflicts"] = db.execute(select(func.count()).where(
        or_(Conflict.person_a_id == pe.id, Conflict.person_b_id == pe.id),
        Conflict.status.in_(("OPEN", "STUDENT_CONFIRMED")))).scalar()
    rec["pending_consents"] = db.execute(select(func.count()).where(ConsentRequest.person_id == pe.id,
                                                                    ConsentRequest.status == "PENDING")).scalar()
    return rec


@router.get("/me/access-log", summary="Who accessed or changed my data (from the tamper-evident audit log)")
def my_access_log(p: Principal = Depends(need("self:read")), db: Session = Depends(get_db), limit: int = 200):
    rows = db.execute(select(AuditLog).where(AuditLog.subject_person_id == p.person_id)
                      .order_by(AuditLog.id.desc()).limit(limit)).scalars()
    return [{"id": a.id, "at": a.ts.isoformat(), "actor": a.actor, "role": a.actor_role, "action": a.action,
             "purpose": a.purpose, "details": a.details, "hash": a.hash[:16]} for a in rows]


# ---------------------------------------------------------------- consent
class ConsentIn(BaseModel):
    apaar_id: str
    purpose: str = Field(min_length=8)
    fields: list[str]
    duration_days: int = Field(30, ge=1, le=365)


def consent_out(db: Session, c: ConsentRequest, p: Principal) -> dict:
    pe = db.get(Person, c.person_id)
    d = {"id": c.id, "requester": c.requester_label, "requester_role": c.requester_role, "purpose": c.purpose,
         "fields": c.fields, "duration_days": c.duration_days, "status": c.status, "transfer_id": c.transfer_id,
         "created_at": c.created_at.isoformat(), "decided_at": c.decided_at.isoformat() if c.decided_at else None,
         "expires_at": c.expires_at.isoformat() if c.expires_at else None,
         "expired": bool(c.expires_at and c.expires_at < utcnow())}
    if p.role != "STUDENT":
        d["student"] = pe.name if c.status == "APPROVED" else None
        d["apaar"] = records.pretty(pe.apaar_id) if pe.apaar_id else pe.provisional_id
    return d


@router.post("/consents", summary="Another institution asks a student for access")
def request_consent(body: ConsentIn, p: Principal = Depends(need("consent:request")), db: Session = Depends(get_db)):
    pe = records.find_person(db, body.apaar_id)
    if not pe:
        raise HTTPException(404, "no student with that APAAR")
    bad = [f for f in body.fields if f not in records.SHAREABLE_FIELDS]
    if bad:
        raise HTTPException(400, f"unknown fields: {bad}; allowed: {records.SHAREABLE_FIELDS}")
    inst = db.get(Institution, p.institution_id)
    c = ConsentRequest(person_id=pe.id, requester_role=p.role, requester_institution_id=p.institution_id,
                       requester_label=inst.name, purpose=body.purpose, fields=body.fields, duration_days=body.duration_days)
    db.add(c)
    db.flush()
    events.emit(db, "CONSENT_REQUESTED", institution_id=p.institution_id, person_id=pe.id, actor=p.label,
                payload={"consent_id": c.id, "purpose": body.purpose})
    audit.record(db, actor=p.label, role=p.role, action="CONSENT_REQUEST", resource=f"consent:{c.id}",
                 subject_person_id=pe.id, purpose=body.purpose, details={"fields": body.fields})
    db.commit()
    return consent_out(db, c, p)


@router.get("/consents")
def list_consents(p: Principal = Depends(current), db: Session = Depends(get_db)):
    stmt = select(ConsentRequest).order_by(ConsentRequest.id.desc()).limit(200)
    if p.role == "STUDENT":
        stmt = stmt.where(ConsentRequest.person_id == p.person_id)
    elif p.institution_scoped:
        stmt = stmt.where(ConsentRequest.requester_institution_id == p.institution_id)
    elif p.role != "AICTE_ADMIN":
        raise HTTPException(403)
    return [consent_out(db, c, p) for c in db.execute(stmt).scalars()]


class DecideIn(BaseModel):
    approve: bool


@router.post("/consents/{cid}/decide")
def decide(cid: int, body: DecideIn, p: Principal = Depends(need("consent:decide")), db: Session = Depends(get_db)):
    c = db.get(ConsentRequest, cid)
    if not c or c.person_id != p.person_id:
        raise HTTPException(404)
    records.decide_consent(db, c, body.approve)
    if c.transfer_id:
        t = db.get(Transfer, c.transfer_id)
        if t and t.status == "PENDING_STUDENT":
            t.status = "PENDING_RELEASE" if body.approve else "REJECTED"
            t.updated_at = utcnow()
            src = db.get(Enrollment, t.from_enrollment_id)
            if body.approve:
                events.emit(db, "TRANSFER_REQUESTED", institution_id=src.institution_id, person_id=t.person_id,
                            payload={"transfer_id": t.id, "stage": "awaiting release"}, actor=p.label)
    events.emit(db, "CONSENT_DECIDED", institution_id=c.requester_institution_id, person_id=c.person_id, actor=p.label,
                payload={"consent_id": c.id, "approved": body.approve})
    audit.record(db, actor=p.label, role=p.role, action="CONSENT_APPROVE" if body.approve else "CONSENT_DENY",
                 resource=f"consent:{c.id}", subject_person_id=c.person_id, purpose=c.purpose,
                 details={"requester": c.requester_label, "fields": c.fields})
    db.commit()
    return consent_out(db, c, p)


@router.post("/consents/{cid}/revoke")
def revoke_consent(cid: int, p: Principal = Depends(need("consent:decide")), db: Session = Depends(get_db)):
    c = db.get(ConsentRequest, cid)
    if not c or c.person_id != p.person_id:
        raise HTTPException(404)
    if c.status != "APPROVED":
        raise HTTPException(409, "only an approved consent can be revoked")
    c.status, c.decided_at = "REVOKED", utcnow()
    events.emit(db, "CONSENT_DECIDED", institution_id=c.requester_institution_id, person_id=c.person_id, actor=p.label,
                payload={"consent_id": c.id, "revoked": True})
    audit.record(db, actor=p.label, role=p.role, action="CONSENT_REVOKE", resource=f"consent:{c.id}",
                 subject_person_id=c.person_id, details={"requester": c.requester_label})
    db.commit()
    return consent_out(db, c, p)


@router.get("/records/{ref}", summary="Read a student's record (consent enforced at read time)")
def read_record(ref: str, purpose: str | None = None, p: Principal = Depends(need("record:read")),
                db: Session = Depends(get_db)):
    return records.read_record(db, p, ref, purpose)


# ---------------------------------------------------------------- corrections (right to correction)
class CorrectionIn(BaseModel):
    enrollment_id: int
    field: str
    requested_value: str
    reason: str | None = None


CORRECTABLE = {"social_category", "seat_type", "nationality", "year_of_study", "parent_name"}


@router.post("/me/corrections")
def request_correction(body: CorrectionIn, p: Principal = Depends(need("correction:request")), db: Session = Depends(get_db)):
    e = db.get(Enrollment, body.enrollment_id)
    if not e or e.person_id != p.person_id:
        raise HTTPException(404)
    if body.field not in CORRECTABLE:
        raise HTTPException(400, f"correctable here: {sorted(CORRECTABLE)}; name/DOB are corrected in the APAAR registry")
    pe = db.get(Person, e.person_id)
    cur = getattr(pe, body.field) if body.field == "parent_name" else getattr(e, body.field)
    cr = CorrectionRequest(person_id=p.person_id, enrollment_id=e.id, institution_id=e.institution_id, field=body.field,
                           current_value=str(cur), requested_value=body.requested_value, reason=body.reason)
    db.add(cr)
    db.flush()
    events.emit(db, "CORRECTION_REQUESTED", institution_id=e.institution_id, person_id=e.person_id, enrollment_id=e.id,
                payload={"correction_id": cr.id, "field": body.field}, actor=p.label)
    audit.record(db, actor=p.label, role=p.role, action="CORRECTION_REQUEST", resource=f"correction:{cr.id}",
                 subject_person_id=p.person_id, details={"field": body.field})
    db.commit()
    return {"id": cr.id, "status": cr.status}


@router.get("/corrections")
def list_corrections(p: Principal = Depends(current), db: Session = Depends(get_db)):
    stmt = select(CorrectionRequest).order_by(CorrectionRequest.id.desc()).limit(200)
    if p.role == "STUDENT":
        stmt = stmt.where(CorrectionRequest.person_id == p.person_id)
    elif p.institution_scoped:
        stmt = stmt.where(CorrectionRequest.institution_id == p.institution_id)
    elif p.role != "AICTE_ADMIN":
        raise HTTPException(403)
    out = []
    for c in db.execute(stmt).scalars():
        e = db.get(Enrollment, c.enrollment_id)
        out.append({"id": c.id, "enrollment_id": c.enrollment_id, "roll_no": e.roll_no, "student": db.get(Person, c.person_id).name,
                    "field": c.field, "current_value": c.current_value, "requested_value": c.requested_value,
                    "reason": c.reason, "status": c.status, "decided_by": c.decided_by,
                    "created_at": c.created_at.isoformat()})
    return out


class CorrectionDecisionIn(BaseModel):
    accept: bool


@router.post("/corrections/{cid}/decide")
def decide_correction(cid: int, body: CorrectionDecisionIn, p: Principal = Depends(need("correction:decide")),
                      db: Session = Depends(get_db)):
    c = db.get(CorrectionRequest, cid)
    if not c:
        raise HTTPException(404)
    assert_inst(p, c.institution_id)
    if c.status != "OPEN":
        raise HTTPException(409, "already decided")
    if body.accept:
        e = db.get(Enrollment, c.enrollment_id)
        pe = db.get(Person, e.person_id)
        from ..ingestion.pipeline import ingest
        row = {"roll_no": e.roll_no, "apaar_id": pe.apaar_id or "", "name": pe.name, "dob": pe.dob.isoformat(),
               "gender": pe.gender, "parent_name": pe.parent_name or "", "qualifying_exam_roll": pe.exam_roll or "",
               "program_code": e.program.code, "admission_date": e.admission_date.isoformat(),
               "year_of_study": e.year_of_study, "mode": e.mode, "seat_type": e.seat_type,
               "social_category": e.social_category, "nationality": e.nationality}
        row[c.field] = c.requested_value
        report = ingest(db, e.institution, [row], source="FIX", actor=p, commit=False)
        if report["rejected"]:
            db.rollback()
            msgs = [f["message"] for r in report["rows"] for f in r["findings"] if f["severity"] == "ERROR"]
            raise HTTPException(409, "the corrected value fails validation: " + "; ".join(msgs))
    c.status, c.decided_by, c.decided_at = ("ACCEPTED" if body.accept else "REJECTED"), p.label, utcnow()
    audit.record(db, actor=p.label, role=p.role, action="CORRECTION_DECIDE", resource=f"correction:{c.id}",
                 subject_person_id=c.person_id, details={"accepted": body.accept})
    db.commit()
    return {"id": c.id, "status": c.status}


# ---------------------------------------------------------------- regulators (NAAC / NBA / UGC)
class AuditQueryIn(BaseModel):
    institution_id: int
    purpose: str = Field(min_length=10)


def pseudonym(apaar_or_prov: str) -> str:
    return "S-" + hashlib.sha256(("spine-pseudonym:" + apaar_or_prov).encode()).hexdigest()[:10].upper()


@router.post("/regulator/audit-queries", summary="Purpose-bound, pseudonymised bulk audit of one institution")
def audit_query(body: AuditQueryIn, p: Principal = Depends(need("audit:query")), db: Session = Depends(get_db)):
    inst = db.get(Institution, body.institution_id)
    if not inst:
        raise HTTPException(404)
    rows = db.execute(select(Enrollment, Person).join(Person, Person.id == Enrollment.person_id)
                      .where(Enrollment.institution_id == inst.id).order_by(Enrollment.program_id, Enrollment.id)).all()
    q = audit.record(db, actor=p.label, role=p.role, action="AUDIT_QUERY", resource=f"institution:{inst.id}",
                     purpose=body.purpose, details={"rows": len(rows), "body": p.regulator_body})
    db.flush()
    for _e, pe in rows:   # each student can see their data was included, and why
        audit.record(db, actor=p.label, role=p.role, action="INCLUDED_IN_AUDIT", resource=f"audit:{q.id}",
                     subject_person_id=pe.id, purpose=body.purpose, details={"pseudonymised": True})
    db.commit()
    programs = {pr.id: pr for pr in db.execute(select(Program).where(Program.institution_id == inst.id)).scalars()}
    return {
        "query_id": q.id, "institution": {"id": inst.id, "name": inst.name, "code": inst.aicte_code, "state": inst.state},
        "purpose": body.purpose,
        "programs": [{**intake.program_status(db, pid), "name": pr.name, "code": pr.code, "level": pr.level}
                     for pid, pr in programs.items()],
        "records": [{"ref": pseudonym(pe.apaar_id or pe.provisional_id), "program": programs[e.program_id].code,
                     "seat_type": e.seat_type, "social_category": e.social_category, "nationality": e.nationality,
                     "status": e.status, "identity": pe.registry_status, "admission_date": e.admission_date.isoformat(),
                     "year_of_study": e.year_of_study} for e, pe in rows],
        "note": "Records are pseudonymised (no name, DOB or APAAR). Each student's access log shows this query.",
    }


@router.get("/regulator/audit-queries")
def my_audit_queries(p: Principal = Depends(need("audit:query")), db: Session = Depends(get_db)):
    rows = db.execute(select(AuditLog).where(AuditLog.action == "AUDIT_QUERY", AuditLog.actor == p.label)
                      .order_by(AuditLog.id.desc()).limit(50)).scalars()
    return [{"id": a.id, "at": a.ts.isoformat(), "resource": a.resource, "purpose": a.purpose, "details": a.details}
            for a in rows]


# ---------------------------------------------------------------- audit log
@router.get("/audit")
def audit_log(p: Principal = Depends(need("audit:read")), db: Session = Depends(get_db), action: str | None = None,
              limit: int = 100, before_id: int | None = None):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)
    total = db.execute(select(func.count(AuditLog.id))).scalar()
    return {"total": total, "entries": [{"id": a.id, "at": a.ts.isoformat(), "actor": a.actor, "role": a.actor_role,
                                         "action": a.action, "resource": a.resource, "subject": a.subject_person_id,
                                         "purpose": a.purpose, "details": a.details, "prev_hash": a.prev_hash[:12],
                                         "hash": a.hash[:12]} for a in db.execute(stmt).scalars()]}


@router.get("/audit/verify", summary="Recompute the hash chain")
def audit_verify(p: Principal = Depends(need("audit:read")), db: Session = Depends(get_db)):
    return audit.verify_chain(db)


# ---------------------------------------------------------------- lookups used by forms
@router.get("/institutions/directory")
def directory(p: Principal = Depends(current), db: Session = Depends(get_db), state: str | None = None):
    stmt = select(Institution).order_by(Institution.name)
    if state:
        stmt = stmt.where(Institution.state == state)
    return [{"id": i.id, "name": i.name, "code": i.aicte_code, "state": i.state} for i in db.execute(stmt).scalars()]
