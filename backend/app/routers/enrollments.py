from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth.deps import Principal, assert_inst, need, scope_inst
from ..db import get_db
from ..identity.apaar_format import clean, mask, pretty
from ..models import (ConsentRequest, Credential, Enrollment, Institution, Person, Program, Transfer, ValidationIssue)
from ..services import audit, lifecycle, records

router = APIRouter(prefix="/api/v1", tags=["enrollments"])


def row(e: Enrollment, p: Person, full_ids: bool) -> dict:
    return {"id": e.id, "roll_no": e.roll_no, "name": p.name, "apaar": (pretty(p.apaar_id) if full_ids else mask(p.apaar_id))
            if p.apaar_id else None, "provisional_id": p.provisional_id, "registry_status": p.registry_status,
            "program_id": e.program_id, "program": e.program.code, "seat_type": e.seat_type,
            "social_category": e.social_category, "nationality": e.nationality, "mode": e.mode, "status": e.status,
            "year_of_study": e.year_of_study, "admission_date": e.admission_date.isoformat(),
            "institution_id": e.institution_id, "dob": p.dob.isoformat(), "gender": p.gender}


@router.get("/enrollments")
def list_enrollments(p: Principal = Depends(need("enrollment:read")), db: Session = Depends(get_db),
                     institution_id: int | None = None, status: str | None = None, program_id: int | None = None,
                     q: str | None = None, provisional: bool | None = None, page: int = 1, size: int = 50):
    stmt = select(Enrollment, Person).join(Person, Person.id == Enrollment.person_id)
    stmt = scope_inst(p, stmt, Enrollment.institution_id)
    if institution_id and not p.institution_scoped:
        stmt = stmt.where(Enrollment.institution_id == institution_id)
    if status:
        stmt = stmt.where(Enrollment.status == status)
    if program_id:
        stmt = stmt.where(Enrollment.program_id == program_id)
    if provisional is True:
        stmt = stmt.where(Person.apaar_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Person.name.ilike(like), Enrollment.roll_no.ilike(like),
                              Person.apaar_id == clean(q), Person.provisional_id == q.strip().upper()))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(Enrollment.id.desc()).offset((page - 1) * size).limit(min(size, 200))).all()
    audit.record(db, actor=p.label, role=p.role, action="ENROLLMENT_LIST", resource="enrollments",
                 details={"institution_id": institution_id or p.institution_id, "q": q, "page": page, "rows": len(rows)})
    db.commit()
    own = p.institution_scoped
    return {"total": total, "page": page, "items": [row(e, pp, own) for e, pp in rows]}


@router.get("/enrollments/{eid}")
def get_enrollment(eid: int, purpose: str | None = None, p: Principal = Depends(need("enrollment:read")),
                   db: Session = Depends(get_db)):
    e = db.get(Enrollment, eid)
    if not e:
        raise HTTPException(404)
    assert_inst(p, e.institution_id)
    if p.role == "AICTE_ADMIN" and not purpose:
        raise HTTPException(400, "state a purpose to open an individual record (it is logged and shown to the student)")
    pe = db.get(Person, e.person_id)
    out = row(e, pe, True)
    out["parent_name"], out["exam_roll"] = pe.parent_name, pe.exam_roll
    out["institution"] = e.institution.name
    out["program_name"] = e.program.name
    out["history"] = records.history(db, e.id)
    out["issues"] = [{"code": i.rule_code, "severity": i.severity, "message": i.message, "status": i.status}
                     for i in db.execute(select(ValidationIssue).where(ValidationIssue.enrollment_id == e.id)).scalars()]
    out["credentials"] = [{"id": c.id, "type": c.type, "revoked": bool(c.revoked_at),
                           "issued_at": c.issued_at.isoformat()}
                          for c in db.execute(select(Credential).where(Credential.enrollment_id == e.id)).scalars()]
    audit.record(db, actor=p.label, role=p.role, action="RECORD_READ", resource=f"enrollment:{e.id}",
                 subject_person_id=e.person_id, purpose=purpose or "institution record management",
                 details={"basis": "AICTE oversight" if p.role == "AICTE_ADMIN" else "own institution"})
    db.commit()
    return out


class LifecycleIn(BaseModel):
    action: str            # DROP | SUSPEND | GRADUATE | RE_ENROL | REINSTATE
    reason: str | None = None


@router.post("/enrollments/{eid}/events", summary="Lifecycle event: drop, suspend, graduate, re-enrol")
def lifecycle_event(eid: int, body: LifecycleIn, p: Principal = Depends(need("enrollment:write")),
                    db: Session = Depends(get_db)):
    e = db.get(Enrollment, eid)
    if not e:
        raise HTTPException(404)
    assert_inst(p, e.institution_id)
    new = lifecycle.ACTION_TO_STATUS.get(body.action.upper())
    if not new:
        raise HTTPException(400, f"action must be one of {', '.join(lifecycle.ACTION_TO_STATUS)}")
    lifecycle.set_status(db, e, new, p, body.reason, event_type=f"ENROLLMENT_{body.action.upper()}")
    db.commit()
    return {"id": e.id, "status": e.status}


# ------------------------------------------------------------------------- transfers
class TransferIn(BaseModel):
    apaar_id: str
    to_program_id: int
    to_roll_no: str
    reason: str | None = None


def transfer_out(db: Session, t: Transfer) -> dict:
    src = db.get(Enrollment, t.from_enrollment_id)
    pe = db.get(Person, t.person_id)
    return {"id": t.id, "status": t.status, "student": pe.name, "apaar": mask(pe.apaar_id),
            "from_institution": src.institution.name, "from_institution_id": src.institution_id,
            "to_institution": db.get(Institution, t.to_institution_id).name, "to_institution_id": t.to_institution_id,
            "to_program": db.get(Program, t.to_program_id).name, "to_roll_no": t.to_roll_no, "reason": t.reason,
            "created_at": t.created_at.isoformat()}


@router.post("/transfers", summary="Destination institution requests a transfer (student must consent)")
def create_transfer(body: TransferIn, p: Principal = Depends(need("transfer:manage")), db: Session = Depends(get_db)):
    prog = db.get(Program, body.to_program_id)
    if not prog:
        raise HTTPException(404, "programme not found")
    assert_inst(p, prog.institution_id)
    t = lifecycle.request_transfer(db, p, apaar_id=clean(body.apaar_id), to_program=prog, to_roll_no=body.to_roll_no,
                                   reason=body.reason)
    db.commit()
    return transfer_out(db, t)


@router.get("/transfers")
def list_transfers(p: Principal = Depends(need("transfer:manage", "transfer:read")), db: Session = Depends(get_db)):
    stmt = select(Transfer).order_by(Transfer.id.desc()).limit(100)
    out = []
    for t in db.execute(stmt).scalars():
        src = db.get(Enrollment, t.from_enrollment_id)
        if p.institution_scoped and p.institution_id not in (src.institution_id, t.to_institution_id):
            continue
        out.append(transfer_out(db, t))
    return out


@router.post("/transfers/{tid}/release", summary="Source institution releases the student")
def release(tid: int, p: Principal = Depends(need("transfer:manage")), db: Session = Depends(get_db)):
    t = db.get(Transfer, tid)
    if not t:
        raise HTTPException(404)
    assert_inst(p, db.get(Enrollment, t.from_enrollment_id).institution_id)
    new = lifecycle.release_transfer(db, t, p)
    db.commit()
    return {"transfer": transfer_out(db, t), "new_enrollment_id": new.id}


@router.post("/transfers/{tid}/reject")
def reject(tid: int, p: Principal = Depends(need("transfer:manage")), db: Session = Depends(get_db)):
    t = db.get(Transfer, tid)
    if not t:
        raise HTTPException(404)
    assert_inst(p, db.get(Enrollment, t.from_enrollment_id).institution_id)
    if t.status not in ("PENDING_STUDENT", "PENDING_RELEASE"):
        raise HTTPException(409, f"transfer is {t.status}")
    t.status = "REJECTED"
    for c in db.execute(select(ConsentRequest).where(ConsentRequest.transfer_id == t.id)).scalars():
        if c.status == "PENDING":
            c.status = "DENIED"
    audit.record(db, actor=p.label, role=p.role, action="TRANSFER_REJECT", resource=f"transfer:{t.id}",
                 subject_person_id=t.person_id)
    db.commit()
    return transfer_out(db, t)
