"""Enrolment lifecycle: status transitions, conflict resolution and transfers.
Every change updates counters, writes an outbox event and an audit entry in one transaction."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..analytics import counts
from ..auth.deps import Principal
from ..credentials import service as creds
from ..models import (ConsentRequest, Conflict, Enrollment, Person, Program, Transfer, utcnow)
from . import audit, events

TRANSITIONS = {
    "ACTIVE": {"DROPPED", "SUSPENDED", "GRADUATED", "TRANSFERRED_OUT", "VOID"},
    "SUSPENDED": {"ACTIVE", "DROPPED"},
    "DROPPED": {"ACTIVE"},
    "CONFLICT": {"ACTIVE", "VOID", "TRANSFERRED_OUT"},
    "TRANSFERRED_OUT": set(), "GRADUATED": set(), "VOID": set(),
}
ACTION_TO_STATUS = {"DROP": "DROPPED", "SUSPEND": "SUSPENDED", "GRADUATE": "GRADUATED",
                    "RE_ENROL": "ACTIVE", "REINSTATE": "ACTIVE"}


def set_status(db: Session, e: Enrollment, new: str, actor: Principal, reason: str | None = None,
               event_type: str = "STATUS_CHANGED") -> None:
    if new not in TRANSITIONS.get(e.status, set()):
        raise HTTPException(409, f"cannot move an enrolment from {e.status} to {new}")
    p = db.get(Person, e.person_id)
    old = e.status
    counts.apply(db, e, p, -1)
    db.flush()                       # counter change lands outside the savepoint below
    e.status, e.updated_at = new, utcnow()
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # Only a move *into* ACTIVE can hit the one-active-regular index, and the -1 above was
        # a no-op for those (old status not counted), so there is nothing to undo.
        db.expire(e)
        raise HTTPException(409, "the student is already actively enrolled elsewhere; use a transfer instead")
    counts.apply(db, e, p, +1)
    if new in {"DROPPED", "SUSPENDED", "TRANSFERRED_OUT"}:
        creds.revoke_for_enrollment(db, e.id, f"enrolment {new.lower()}")
    if new == "VOID":
        creds.revoke_for_enrollment(db, e.id, "enrolment voided", types=("ENROLLMENT", "DEGREE"))
    events.emit(db, event_type, institution_id=e.institution_id, person_id=e.person_id, enrollment_id=e.id,
                payload={"from": old, "to": new, "reason": reason, "roll_no": e.roll_no}, actor=actor.label)
    audit.record(db, actor=actor.label, role=actor.role, action="ENROLLMENT_STATUS", resource=f"enrollment:{e.id}",
                 subject_person_id=e.person_id, details={"from": old, "to": new, "reason": reason})


# --------------------------------------------------------------------------- conflicts
def resolve_conflict(db: Session, c: Conflict, actor: Principal, *, winner_enrollment_id: int | None,
                     loser_action: str, decision: str | None, note: str | None) -> None:
    if c.status in ("RESOLVED", "DISMISSED"):
        raise HTTPException(409, "conflict already closed")
    a, b = db.get(Enrollment, c.enrollment_a_id), db.get(Enrollment, c.enrollment_b_id)
    if c.kind == "FUZZY" and decision == "DIFFERENT_PERSONS":
        c.status, c.resolution = "DISMISSED", f"Determined to be different students. {note or ''}".strip()
    else:
        if winner_enrollment_id not in (a.id, b.id):
            raise HTTPException(400, "winner must be one of the two enrolments")
        winner, loser = (a, b) if winner_enrollment_id == a.id else (b, a)
        target = "TRANSFERRED_OUT" if loser_action == "TRANSFER" else "VOID"
        # loser leaves first so the winner can take the 'one active regular' slot
        if loser.status in ("ACTIVE", "CONFLICT"):
            set_status(db, loser, target, actor, f"conflict #{c.id} resolved", "CONFLICT_LOSER")
        if c.kind == "FUZZY":            # same human under two identities: merge
            keep_p, drop_p = db.get(Person, winner.person_id), db.get(Person, loser.person_id)
            if keep_p.id != drop_p.id:
                if not keep_p.apaar_id and drop_p.apaar_id:
                    keep_p, drop_p = drop_p, keep_p
                drop_p.merged_into_id = keep_p.id
                for e in db.execute(select(Enrollment).where(Enrollment.person_id == drop_p.id)).scalars():
                    counts.apply(db, e, drop_p, -1)
                    e.person_id = keep_p.id
                    counts.apply(db, e, keep_p, +1)
        if winner.status == "CONFLICT":
            set_status(db, winner, "ACTIVE", actor, f"conflict #{c.id} resolved", "CONFLICT_WINNER")
        c.status = "RESOLVED"
        outcome = "closed as transferred out" if target == "TRANSFERRED_OUT" else "voided"
        c.resolution = (f"Enrolment at {winner.institution.name} confirmed; the enrolment at "
                        f"{loser.institution.name} was {outcome}. {note or ''}").strip()
    c.resolved_by, c.resolved_at = actor.label, utcnow()
    for e in (a, b):
        events.emit(db, "CONFLICT_RESOLVED", institution_id=e.institution_id, person_id=e.person_id,
                    enrollment_id=e.id, payload={"conflict_id": c.id, "resolution": c.resolution}, actor=actor.label)
    audit.record(db, actor=actor.label, role=actor.role, action="CONFLICT_RESOLVE", resource=f"conflict:{c.id}",
                 subject_person_id=a.person_id, details={"resolution": c.resolution})


# --------------------------------------------------------------------------- transfers
def request_transfer(db: Session, actor: Principal, *, apaar_id: str, to_program: Program, to_roll_no: str,
                     reason: str | None) -> Transfer:
    p = db.execute(select(Person).where(Person.apaar_id == apaar_id)).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "no student with that APAAR")
    src = db.execute(select(Enrollment).where(Enrollment.person_id == p.id, Enrollment.status == "ACTIVE",
                                              Enrollment.mode == "REGULAR")).scalar_one_or_none()
    if not src:
        raise HTTPException(409, "student has no active regular enrolment to transfer from")
    if src.institution_id == to_program.institution_id:
        raise HTTPException(400, "student is already at your institution")
    t = Transfer(person_id=p.id, from_enrollment_id=src.id, to_institution_id=to_program.institution_id,
                 to_program_id=to_program.id, to_roll_no=to_roll_no, reason=reason)
    db.add(t)
    db.flush()
    cr = ConsentRequest(person_id=p.id, requester_role=actor.role, requester_institution_id=actor.institution_id,
                        requester_label=to_program.institution.name, purpose=f"Transfer admission to {to_program.name}",
                        fields=["name", "dob", "program", "year_of_study", "social_category", "institution"],
                        duration_days=30, transfer_id=t.id)
    db.add(cr)
    db.flush()
    events.emit(db, "TRANSFER_REQUESTED", institution_id=src.institution_id, other_institution_id=to_program.institution_id,
                person_id=p.id, enrollment_id=src.id, payload={"transfer_id": t.id, "to": to_program.institution.name},
                actor=actor.label)
    events.emit(db, "CONSENT_REQUESTED", institution_id=actor.institution_id, person_id=p.id,
                payload={"consent_id": cr.id, "purpose": cr.purpose}, actor=actor.label)
    audit.record(db, actor=actor.label, role=actor.role, action="TRANSFER_REQUEST", resource=f"transfer:{t.id}",
                 subject_person_id=p.id, details={"to_program": to_program.id})
    return t


def release_transfer(db: Session, t: Transfer, actor: Principal) -> Enrollment:
    """Source institution releases. Both rows flip in one transaction: no window in which the
    student is active twice (false duplicate) or nowhere (lost student)."""
    if t.status != "PENDING_RELEASE":
        raise HTTPException(409, f"transfer is {t.status}, expected PENDING_RELEASE")
    src = db.get(Enrollment, t.from_enrollment_id)
    set_status(db, src, "TRANSFERRED_OUT", actor, f"transfer #{t.id}")
    new = Enrollment(person_id=t.person_id, institution_id=t.to_institution_id, program_id=t.to_program_id,
                     roll_no=t.to_roll_no, academic_year=src.academic_year, admission_date=utcnow().date(),
                     year_of_study=src.year_of_study, mode=src.mode, seat_type=src.seat_type if src.seat_type in
                     ("MERIT", "MANAGEMENT", "NRI") else "MERIT", social_category=src.social_category,
                     nationality=src.nationality, status="ACTIVE", source="TRANSFER")
    db.add(new)
    db.flush()
    counts.apply(db, new, db.get(Person, t.person_id), +1)
    t.status, t.new_enrollment_id, t.updated_at = "COMPLETED", new.id, utcnow()
    events.emit(db, "TRANSFER_COMPLETED", institution_id=t.to_institution_id, other_institution_id=src.institution_id,
                person_id=t.person_id, enrollment_id=new.id, payload={"transfer_id": t.id}, actor=actor.label)
    audit.record(db, actor=actor.label, role=actor.role, action="TRANSFER_RELEASE", resource=f"transfer:{t.id}",
                 subject_person_id=t.person_id, details={"new_enrollment": new.id})
    return new
