"""Probabilistic duplicate detection for records that do not share an APAAR.

Multi-pass blocking keeps it near-linear and hard to dodge:
  pass 1  same date of birth
  pass 2  same qualifying-exam roll number (any DOB, catches a shifted DOB)
  pass 3  same phonetic name key AND same phonetic parent key (any DOB)
At national scale (~1.2 crore active students) a DOB block is a few thousand people, so
each new record is compared against thousands, not crores.
"""
from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..identity.names import name_similarity
from ..models import Enrollment, Person


def match_score(a: Person, b: Person) -> tuple[float, list[str]]:
    reasons: list[str] = []
    ns = name_similarity(a.name, b.name)
    ps = name_similarity(a.parent_name, b.parent_name) if a.parent_name and b.parent_name else None
    s = 0.6 * ns + 0.4 * ps if ps is not None else 0.95 * ns
    reasons.append(f"name similarity {ns:.2f}")
    if ps is not None:
        reasons.append(f"parent-name similarity {ps:.2f}")
    if a.dob == b.dob:
        reasons.append("same date of birth")
    else:
        s *= 0.85
        reasons.append("different date of birth")
    if a.exam_roll and a.exam_roll == b.exam_roll:
        s = max(s, 0.97)
        reasons.append("same qualifying-exam roll number")
    elif a.exam_roll and b.exam_roll:
        s *= 0.92                       # two different (verifiable) exam rolls: mild evidence against
        reasons.append("different qualifying-exam roll numbers")
    if a.gender != b.gender:
        s *= 0.7
        reasons.append("different gender")
    return round(min(s, 1.0), 4), reasons


def candidates(db: Session, p: Person) -> list[Person]:
    conds = [Person.dob == p.dob]
    if p.exam_roll:
        conds.append(Person.exam_roll == p.exam_roll)
    if p.name_key and p.parent_key:
        conds.append(and_(Person.name_key == p.name_key, Person.parent_key == p.parent_key))
    stmt = select(Person).where(or_(*conds), Person.id != p.id, Person.merged_into_id.is_(None))
    return list(db.execute(stmt).scalars())


def find_matches(db: Session, p: Person, *, same_institution_id: int | None = None,
                 exclude_institution_id: int | None = None) -> list[tuple[Enrollment, float, list[str]]]:
    """Active enrolments of *other* people who are probably this person."""
    out = []
    for c in candidates(db, p):
        if p.apaar_id and c.apaar_id:
            continue          # two distinct registry identities: not our call to merge
        score, reasons = match_score(p, c)
        if score < settings.fuzzy_dup_threshold:
            continue
        stmt = select(Enrollment).where(Enrollment.person_id == c.id, Enrollment.status == "ACTIVE")
        if same_institution_id is not None:
            stmt = stmt.where(Enrollment.institution_id == same_institution_id)
        if exclude_institution_id is not None:
            stmt = stmt.where(Enrollment.institution_id != exclude_institution_id)
        for e in db.execute(stmt).scalars():
            out.append((e, score, reasons))
    return out
