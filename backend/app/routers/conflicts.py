"""Conflict queue. Institutions see only their own side: the other college is shown as
'another AICTE institution' (data minimisation). AICTE and the student see both sides."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.deps import Principal, current, need
from ..db import get_db
from ..identity.apaar_format import mask, pretty
from ..models import Conflict, Enrollment, Person, utcnow
from ..services import audit, events, lifecycle

router = APIRouter(prefix="/api/v1", tags=["conflicts"])


def _visible(p: Principal, e: Enrollment) -> bool:
    return p.role in ("AICTE_ADMIN", "STUDENT") or (p.institution_scoped and e.institution_id == p.institution_id)


def conflict_out(db: Session, c: Conflict, p: Principal) -> dict:
    def side(e: Enrollment) -> dict:
        pe = db.get(Person, e.person_id)
        v = _visible(p, e)
        return {"enrollment_id": e.id, "status": e.status, "yours": bool(p.institution_id and p.institution_id == e.institution_id),
                "institution": e.institution.name if v else "Another AICTE institution",
                "institution_code": e.institution.aicte_code if v else None,
                "institution_id": e.institution_id if v else None, "state": e.institution.state if v else None,
                "program": e.program.name if v else None, "roll_no": e.roll_no if v else None,
                "admission_date": e.admission_date.isoformat() if v else None,
                "reported_at": e.reported_at.isoformat(), "seat_type": e.seat_type if v else None,
                "student_name": pe.name if v else None,
                "apaar": (pretty(pe.apaar_id) if p.role != "DATA_OPERATOR" else mask(pe.apaar_id)) if v and pe.apaar_id else None,
                "provisional_id": pe.provisional_id if v else None}
    a, b = db.get(Enrollment, c.enrollment_a_id), db.get(Enrollment, c.enrollment_b_id)
    return {"id": c.id, "kind": c.kind, "score": c.score, "status": c.status, "reasons": c.reasons,
            "a": side(a), "b": side(b), "student_choice_enrollment_id": c.student_choice_enrollment_id,
            "student_note": c.student_note, "evidence": c.evidence or [], "resolution": c.resolution,
            "resolved_by": c.resolved_by, "created_at": c.created_at.isoformat(),
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None}


def _scoped(p: Principal, stmt):
    if p.institution_scoped:
        ids = select(Enrollment.id).where(Enrollment.institution_id == p.institution_id)
        return stmt.where(or_(Conflict.enrollment_a_id.in_(ids), Conflict.enrollment_b_id.in_(ids)))
    if p.role == "STUDENT":
        return stmt.where(or_(Conflict.person_a_id == p.person_id, Conflict.person_b_id == p.person_id))
    if p.role == "AICTE_ADMIN":
        return stmt
    raise HTTPException(403, "no access to conflicts")


@router.get("/conflicts")
def list_conflicts(p: Principal = Depends(current), db: Session = Depends(get_db), status: str | None = None,
                   kind: str | None = None, limit: int = 200):
    stmt = _scoped(p, select(Conflict))
    if status == "open":
        stmt = stmt.where(Conflict.status.in_(("OPEN", "STUDENT_CONFIRMED")))
    elif status:
        stmt = stmt.where(Conflict.status == status)
    if kind:
        stmt = stmt.where(Conflict.kind == kind)
    return [conflict_out(db, c, p) for c in db.execute(stmt.order_by(Conflict.id.desc()).limit(limit)).scalars()]


def _get(db, cid, p) -> Conflict:
    c = db.execute(_scoped(p, select(Conflict).where(Conflict.id == cid))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "conflict not found")
    return c


@router.get("/conflicts/{cid}")
def get_conflict(cid: int, p: Principal = Depends(current), db: Session = Depends(get_db)):
    return conflict_out(db, _get(db, cid, p), p)


class NoteIn(BaseModel):
    note: str


@router.post("/conflicts/{cid}/evidence", summary="An involved institution attaches evidence")
def add_evidence(cid: int, body: NoteIn, p: Principal = Depends(need("conflict:evidence")), db: Session = Depends(get_db)):
    c = _get(db, cid, p)
    c.evidence = [*(c.evidence or []), {"by": p.label, "institution_id": p.institution_id, "note": body.note[:1000],
                                        "at": utcnow().isoformat()}]
    audit.record(db, actor=p.label, role=p.role, action="CONFLICT_EVIDENCE", resource=f"conflict:{c.id}",
                 subject_person_id=c.person_b_id)
    db.commit()
    return conflict_out(db, c, p)


class ConfirmIn(BaseModel):
    enrollment_id: int
    note: str | None = None


@router.post("/conflicts/{cid}/student-confirm", summary="The student says where they actually study")
def student_confirm(cid: int, body: ConfirmIn, p: Principal = Depends(need("conflict:confirm")),
                    db: Session = Depends(get_db)):
    c = _get(db, cid, p)
    if c.status not in ("OPEN", "STUDENT_CONFIRMED"):
        raise HTTPException(409, "conflict is closed")
    if body.enrollment_id not in (c.enrollment_a_id, c.enrollment_b_id):
        raise HTTPException(400, "pick one of the two enrolments")
    c.student_choice_enrollment_id, c.student_note, c.status = body.enrollment_id, body.note, "STUDENT_CONFIRMED"
    for eid in (c.enrollment_a_id, c.enrollment_b_id):
        e = db.get(Enrollment, eid)
        events.emit(db, "CONFLICT_STUDENT_CONFIRMED", institution_id=e.institution_id, enrollment_id=e.id,
                    person_id=e.person_id, actor=p.label, payload={"conflict_id": c.id,
                                                                  "confirmed_here": eid == body.enrollment_id})
    audit.record(db, actor=p.label, role=p.role, action="CONFLICT_STUDENT_CONFIRM", resource=f"conflict:{c.id}",
                 subject_person_id=p.person_id, details={"enrollment_id": body.enrollment_id})
    db.commit()
    return conflict_out(db, c, p)


class ResolveIn(BaseModel):
    winner_enrollment_id: int | None = None
    loser_action: str = "VOID"            # VOID | TRANSFER
    decision: str | None = None           # FUZZY only: SAME_PERSON | DIFFERENT_PERSONS
    note: str | None = None


@router.post("/conflicts/{cid}/resolve", summary="AICTE adjudicates")
def resolve(cid: int, body: ResolveIn, p: Principal = Depends(need("conflict:resolve")), db: Session = Depends(get_db)):
    c = _get(db, cid, p)
    lifecycle.resolve_conflict(db, c, p, winner_enrollment_id=body.winner_enrollment_id,
                               loser_action=body.loser_action.upper(), decision=body.decision, note=body.note)
    db.commit()
    return conflict_out(db, c, p)
