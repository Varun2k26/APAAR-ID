"""Programme-level rule anomalies (intake / supernumerary / NRI caps). Unlike the statistical
detectors these are shown to the institution too: they are facts, not suspicions."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Anomaly, Program, utcnow
from ..services import events
from ..validation import intake

RULE_KINDS = ("INTAKE_EXCEEDED", "SUPERNUMERARY_EXCEEDED", "NRI_QUOTA_EXCEEDED")


def upsert(db: Session, *, institution_id: int, program_id: int | None, kind: str, source: str, severity: str,
           score: float, title: str, explanation: dict, year: int | None = None) -> tuple[Anomaly, bool]:
    year = year or settings.current_year
    prog_cond = Anomaly.program_id == program_id if program_id is not None else Anomaly.program_id.is_(None)
    a = db.execute(select(Anomaly).where(Anomaly.institution_id == institution_id, prog_cond,
                                         Anomaly.kind == kind, Anomaly.year == year)).scalar_one_or_none()
    is_new = a is None or not a.active
    prev_score = a.score if a else None
    if a is None:
        a = Anomaly(institution_id=institution_id, program_id=program_id, kind=kind, year=year, source=source,
                    status="OPEN")
        db.add(a)
    a.severity, a.score, a.title, a.explanation, a.active, a.updated_at = severity, score, title, explanation, True, utcnow()
    # An officer's dismissal sticks unless the signal gets materially worse (+25%).
    if a.status == "DISMISSED":
        if prev_score is not None and score > prev_score * 1.25:
            a.status, a.note = "OPEN", (a.note or "") + " [re-opened: signal worsened after dismissal]"
        else:
            is_new = False
    db.flush()
    return a, is_new


def refresh_programs(db: Session, program_ids) -> list[dict]:
    alerts = []
    for pid in sorted(set(program_ids)):
        prog = db.get(Program, pid)
        st = intake.program_status(db, pid)
        by_kind = defaultdict(list)
        for v in st["violations"]:
            by_kind[v["kind"]].append(v)
        for kind in RULE_KINDS:
            vs = by_kind.get(kind)
            existing = db.execute(select(Anomaly).where(Anomaly.program_id == pid, Anomaly.kind == kind,
                                                        Anomaly.year == settings.current_year)).scalar_one_or_none()
            if not vs:
                if existing and existing.active:
                    existing.active, existing.updated_at = False, utcnow()
                continue
            excess = sum(v["excess"] for v in vs)
            ratio = excess / max(1, st["approved"])
            sev = "HIGH" if ratio >= 0.1 else "MEDIUM"
            names = {"REGULAR": "regular admissions", "TFW": "tuition fee waiver seats", "FOREIGN": "FN/OCI/PIO seats",
                     "LATERAL": "lateral entry seats", "NRI": "NRI seats"}
            limit_word = "an approved intake of" if kind == "INTAKE_EXCEEDED" else "a cap of"
            title = f"{prog.name}: " + "; ".join(f"{v['count']} {names[v['bucket']]} against {limit_word} {v['limit']}" for v in vs)
            a, is_new = upsert(db, institution_id=prog.institution_id, program_id=pid, kind=kind, source="RULE",
                               severity=sev, score=round(min(1.0, 0.5 + ratio), 3), title=title,
                               explanation={"violations": vs, "approved": st["approved"], "seats": st["seats"],
                                            "caps": st["caps"], "regular": st["regular"],
                                            "note": "Supernumerary seats are checked against their own caps and do "
                                                    "not count towards the approved intake."})
            alerts.append({"program_id": pid, "kind": kind, "title": title, "anomaly_id": a.id})
            if is_new:
                events.emit(db, "INTAKE_ALERT", institution_id=prog.institution_id,
                            payload={"anomaly_id": a.id, "kind": kind, "title": title})
    return alerts
