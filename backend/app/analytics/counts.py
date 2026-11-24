"""Incremental counters, updated in the same transaction as every enrolment change."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Enrollment, Person, ProgramCount

COUNTED = {"ACTIVE"}


def is_late(e: Enrollment) -> bool:
    return (e.reported_at.date() - e.admission_date).days > settings.late_report_days


def keys_for(e: Enrollment, p: Person) -> list[str]:
    ks = [f"seat:{e.seat_type}", f"cat:{e.social_category}", f"nat:{e.nationality}", f"mode:{e.mode}"]
    if not p.apaar_id and p.registry_status != "EXEMPT":
        ks.append("prov")
    elif p.registry_status == "PENDING":
        ks.append("pending")
    if is_late(e):
        ks.append("late")
    return ks


def _row(db: Session, e: Enrollment) -> ProgramCount:
    pc = db.execute(select(ProgramCount).where(ProgramCount.program_id == e.program_id,
                                               ProgramCount.year == e.academic_year)
                    .with_for_update()).scalar_one_or_none()
    if pc is None:
        pc = ProgramCount(program_id=e.program_id, institution_id=e.institution_id, year=e.academic_year,
                          total=0, counts={})
        db.add(pc)
        db.flush()
    return pc


def apply(db: Session, e: Enrollment, p: Person, sign: int) -> None:
    """Add (+1) or remove (-1) one enrolment from the counters, only if it is in a counted status."""
    if e.status not in COUNTED:
        return
    pc = _row(db, e)
    c = dict(pc.counts or {})
    for k in keys_for(e, p):
        c[k] = c.get(k, 0) + sign
    pc.counts = c
    pc.total = (pc.total or 0) + sign


def recompute(db: Session, year: int | None = None) -> int:
    """Rebuild counters from enrolments (repair tool + used by the seed and tests)."""
    year = year or settings.current_year
    db.execute(delete(ProgramCount).where(ProgramCount.year == year))
    acc: dict[tuple, dict] = defaultdict(lambda: {"total": 0, "counts": defaultdict(int), "inst": None})
    rows = db.execute(select(Enrollment, Person).join(Person, Person.id == Enrollment.person_id)
                      .where(Enrollment.academic_year == year, Enrollment.status.in_(COUNTED)))
    for e, p in rows:
        a = acc[e.program_id]
        a["inst"] = e.institution_id
        a["total"] += 1
        for k in keys_for(e, p):
            a["counts"][k] += 1
    for pid, a in acc.items():
        db.add(ProgramCount(program_id=pid, institution_id=a["inst"], year=year, total=a["total"],
                            counts=dict(a["counts"])))
    db.flush()
    return len(acc)
