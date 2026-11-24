"""Intake check that understands supernumerary seats.

Regular seats (MERIT, MANAGEMENT, NRI) are counted against the approved intake. TFW,
Foreign/OCI/PIO and lateral-entry seats are supernumerary: each is checked against its own
cap instead. So 'approved 60, enrolled 76' can be perfectly legal (60 + 3 TFW + 8 FN + 5 LE),
while 'approved 60, enrolled 73' with 13 TFW is not.
"""
from __future__ import annotations

import math
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ApprovedIntake, ProgramCount


def cap_for(approved: int, kind: str) -> int:
    return math.floor(approved * settings.caps[kind] + 1e-9)


def program_status(db: Session, program_id: int, year: int | None = None) -> dict:
    year = year or settings.current_year
    ai = db.execute(select(ApprovedIntake).where(ApprovedIntake.program_id == program_id,
                                                 ApprovedIntake.year == year)).scalar_one_or_none()
    pc = db.execute(select(ProgramCount).where(ProgramCount.program_id == program_id,
                                               ProgramCount.year == year)).scalar_one_or_none()
    approved = ai.approved if ai else 0
    c = (pc.counts if pc else {}) or {}
    seat = {k: c.get(f"seat:{k}", 0) for k in ("MERIT", "MANAGEMENT", "NRI", "TFW", "FOREIGN", "LATERAL")}
    regular = seat["MERIT"] + seat["MANAGEMENT"] + seat["NRI"]
    caps = {k: cap_for(approved, k) for k in ("TFW", "FOREIGN", "LATERAL", "NRI")}
    violations = []
    if regular > approved:
        violations.append({"code": "R20", "kind": "INTAKE_EXCEEDED", "bucket": "REGULAR", "count": regular,
                           "limit": approved, "excess": regular - approved})
    for k in ("TFW", "FOREIGN", "LATERAL"):
        if seat[k] > caps[k]:
            violations.append({"code": "R21", "kind": "SUPERNUMERARY_EXCEEDED", "bucket": k, "count": seat[k],
                               "limit": caps[k], "excess": seat[k] - caps[k]})
    if seat["NRI"] > caps["NRI"]:
        violations.append({"code": "R22", "kind": "NRI_QUOTA_EXCEEDED", "bucket": "NRI", "count": seat["NRI"],
                           "limit": caps["NRI"], "excess": seat["NRI"] - caps["NRI"]})
    total = pc.total if pc else 0
    return {
        "program_id": program_id, "year": year, "approved": approved, "total": total,
        "regular": regular, "seats": seat, "caps": caps,
        "supernumerary": seat["TFW"] + seat["FOREIGN"] + seat["LATERAL"],
        "fill_rate": round(regular / approved, 4) if approved else None,
        "provisional": c.get("prov", 0), "pending": c.get("pending", 0), "late": c.get("late", 0),
        "categories": {k[4:]: v for k, v in c.items() if k.startswith("cat:")},
        "violations": violations,
        "binding": date.today() >= settings.census_date,   # live until the census date, binding after
    }
