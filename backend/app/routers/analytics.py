from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..anomaly import engine
from ..auth.deps import Principal, assert_inst, need
from ..config import settings
from ..db import get_db
from ..identity import apaar_client
from ..mocks import registry
from ..models import (Anomaly, ApprovedIntake, CensusSnapshot, Conflict, Enrollment, Institution, IntakeHistory,
                      Program, ProgramCount, ValidationIssue, utcnow)
from ..services import audit
from ..validation import intake

router = APIRouter(prefix="/api/v1", tags=["analytics"])
CATS = ["GEN", "EWS", "OBC-NCL", "SC", "ST"]


@router.get("/meta")
def meta():
    today = date.today()
    return {
        "academic_year": settings.current_year, "label": f"{settings.current_year}-{(settings.current_year + 1) % 100:02d}",
        "admission_open": settings.admission_open.isoformat(), "admission_cutoff": settings.admission_cutoff.isoformat(),
        "census_date": settings.census_date.isoformat(), "census_binding": today >= settings.census_date,
        "window": "open" if settings.admission_open <= today <= settings.admission_cutoff else "closed",
        "caps": settings.caps, "dual_policy": {f"{a}+{b}": v for (a, b), v in settings.dual_policy.items()},
        "late_report_days": settings.late_report_days, "provisional_link_days": settings.provisional_link_days,
        "demo_mode": settings.demo_mode, "public_base_url": settings.public_base_url,
        "simulated": ["APAAR registry", "DigiLocker login", "AICTE approval feed", "Institution ERP webhook receiver"],
        "registry": {**registry.control.__dict__, "breaker": apaar_client.breaker_state()},
    }


def _program_rows(db: Session, year: int):
    progs = {p.id: p for p in db.execute(select(Program)).scalars()}
    appr = {a.program_id: a.approved for a in db.execute(select(ApprovedIntake).where(ApprovedIntake.year == year)).scalars()}
    cur = {pc.program_id: pc for pc in db.execute(select(ProgramCount).where(ProgramCount.year == year)).scalars()}
    return progs, appr, cur


def _sum_counts(pcs) -> dict:
    acc = defaultdict(int)
    for pc in pcs:
        for k, v in (pc.counts or {}).items():
            acc[k] += v
    return acc


@router.get("/analytics/national")
def national(p: Principal = Depends(need("national:read")), db: Session = Depends(get_db)):
    y = settings.current_year
    progs, appr, cur = _program_rows(db, y)
    insts = {i.id: i for i in db.execute(select(Institution)).scalars()}
    all_c = _sum_counts(cur.values())
    total = sum(pc.total for pc in cur.values())
    regular = all_c["seat:MERIT"] + all_c["seat:MANAGEMENT"] + all_c["seat:NRI"]
    approved = sum(appr.values())
    anomalies = dict(db.execute(select(Anomaly.institution_id, func.count()).where(
        Anomaly.active.is_(True), Anomaly.status.in_(("OPEN", "INVESTIGATING"))).group_by(Anomaly.institution_id)).all())
    reporting = {pc.institution_id for pc in cur.values() if pc.total > 0}

    by_state = defaultdict(lambda: defaultdict(int))
    by_disc = defaultdict(lambda: defaultdict(int))
    for pid, pr in progs.items():
        inst = insts[pr.institution_id]
        pc = cur.get(pid)
        s, d = by_state[inst.state], by_disc[pr.discipline]
        for bucket in (s, d):
            bucket["approved"] += appr.get(pid, 0)
            if pc:
                c = pc.counts or {}
                bucket["students"] += pc.total
                bucket["regular"] += c.get("seat:MERIT", 0) + c.get("seat:MANAGEMENT", 0) + c.get("seat:NRI", 0)
                bucket["provisional"] += c.get("prov", 0)
    for iid, inst in insts.items():
        by_state[inst.state]["institutions"] += 1
        by_state[inst.state]["anomalies"] += anomalies.get(iid, 0)

    def fin(dct, key):
        out = []
        for k, v in sorted(dct.items()):
            out.append({key: k, **v, "fill": round(v["regular"] / v["approved"], 3) if v["approved"] else None})
        return out

    trend = []
    hist = db.execute(select(IntakeHistory.year, func.sum(IntakeHistory.admitted)).group_by(IntakeHistory.year)).all()
    appr_hist = dict(db.execute(select(ApprovedIntake.year, func.sum(ApprovedIntake.approved))
                                .group_by(ApprovedIntake.year)).all())
    for yr, adm in sorted(hist):
        trend.append({"year": yr, "admitted": int(adm), "approved": int(appr_hist.get(yr, 0)), "source": "aggregate return"})
    trend.append({"year": y, "admitted": total, "approved": approved, "source": "APAAR student-level (live)"})

    open_conf = db.execute(select(Conflict.kind, func.count()).where(Conflict.status.in_(("OPEN", "STUDENT_CONFIRMED")))
                           .group_by(Conflict.kind)).all()
    return {
        "kpis": {"institutions": len(insts), "reporting_institutions": len(reporting), "students": total,
                 "approved_intake": approved, "regular": regular, "supernumerary": total - regular,
                 "utilisation": round(regular / approved, 4) if approved else None,
                 "apaar_coverage": round(1 - all_c.get("prov", 0) / total, 4) if total else None,
                 "provisional": all_c.get("prov", 0), "pending_verification": all_c.get("pending", 0),
                 "open_conflicts": dict(open_conf), "open_anomalies": sum(anomalies.values())},
        "by_state": fin(by_state, "state"), "by_discipline": fin(by_disc, "discipline"),
        "categories": {k: all_c.get(f"cat:{k}", 0) for k in CATS},
        "seats": {k: all_c.get(f"seat:{k}", 0) for k in ("MERIT", "MANAGEMENT", "NRI", "TFW", "FOREIGN", "LATERAL")},
        "trend": trend,
    }


@router.get("/analytics/institutions")
def institutions(p: Principal = Depends(need("institution:read", "national:read")), db: Session = Depends(get_db),
                 state: str | None = None, q: str | None = None, sort: str = "anomalies"):
    y = settings.current_year
    progs, appr, cur = _program_rows(db, y)
    stmt = select(Institution)
    if p.institution_scoped:
        stmt = stmt.where(Institution.id == p.institution_id)
    if state:
        stmt = stmt.where(Institution.state == state)
    if q:
        stmt = stmt.where(Institution.name.ilike(f"%{q}%") | Institution.aicte_code.ilike(f"%{q}%"))
    anomalies = dict(db.execute(select(Anomaly.institution_id, func.count()).where(
        Anomaly.active.is_(True), Anomaly.status.in_(("OPEN", "INVESTIGATING"))).group_by(Anomaly.institution_id)).all())
    by_inst = defaultdict(list)
    for pid, pr in progs.items():
        by_inst[pr.institution_id].append(pid)
    out = []
    for i in db.execute(stmt).scalars():
        pcs = [cur[x] for x in by_inst[i.id] if x in cur]
        c = _sum_counts(pcs)
        tot = sum(pc.total for pc in pcs)
        ap = sum(appr.get(x, 0) for x in by_inst[i.id])
        reg = c["seat:MERIT"] + c["seat:MANAGEMENT"] + c["seat:NRI"]
        out.append({"id": i.id, "name": i.name, "code": i.aicte_code, "state": i.state, "district": i.district,
                    "type": i.inst_type, "programs": len(by_inst[i.id]), "approved": ap, "students": tot, "regular": reg,
                    "fill": round(reg / ap, 3) if ap else None,
                    "provisional_share": round(c.get("prov", 0) / tot, 3) if tot else 0,
                    "anomalies": anomalies.get(i.id, 0) if not p.institution_scoped else None})
    key = {"anomalies": lambda r: (-(r["anomalies"] or 0), r["name"]), "students": lambda r: -r["students"],
           "name": lambda r: r["name"], "fill": lambda r: -(r["fill"] or 0)}.get(sort, lambda r: r["name"])
    return sorted(out, key=key)


@router.get("/analytics/institutions/{iid}")
def institution_detail(iid: int, p: Principal = Depends(need("institution:read", "national:read")),
                       db: Session = Depends(get_db)):
    assert_inst(p, iid)
    inst = db.get(Institution, iid)
    if not inst:
        raise HTTPException(404)
    y = settings.current_year
    programs = []
    for pr in db.execute(select(Program).where(Program.institution_id == iid).order_by(Program.code)).scalars():
        st = intake.program_status(db, pr.id, y)
        hist = db.execute(select(IntakeHistory).where(IntakeHistory.program_id == pr.id)
                          .order_by(IntakeHistory.year)).scalars().all()
        programs.append({**st, "code": pr.code, "name": pr.name, "level": pr.level, "discipline": pr.discipline,
                         "history": [{"year": h.year, "admitted": h.admitted} for h in hist]})
    tot = sum(x["total"] for x in programs)
    ap = sum(x["approved"] for x in programs)
    reg = sum(x["regular"] for x in programs)
    cats = defaultdict(int)
    for x in programs:
        for k, v in x["categories"].items():
            cats[k] += v
    an_stmt = select(Anomaly).where(Anomaly.institution_id == iid, Anomaly.active.is_(True))
    if p.institution_scoped:
        an_stmt = an_stmt.where(Anomaly.source == "RULE")       # statistical suspicions stay with AICTE
    anomalies = [{"id": a.id, "kind": a.kind, "source": a.source, "severity": a.severity, "title": a.title,
                  "status": a.status, "score": a.score, "explanation": a.explanation, "program_id": a.program_id}
                 for a in db.execute(an_stmt.order_by(Anomaly.score.desc())).scalars()]
    issues = dict(db.execute(select(ValidationIssue.severity, func.count()).where(
        ValidationIssue.institution_id == iid, ValidationIssue.status == "OPEN").group_by(ValidationIssue.severity)).all())
    status_counts = dict(db.execute(select(Enrollment.status, func.count()).where(
        Enrollment.institution_id == iid, Enrollment.academic_year == y).group_by(Enrollment.status)).all())
    prov = sum(x["provisional"] for x in programs)
    return {"institution": {"id": inst.id, "name": inst.name, "code": inst.aicte_code, "state": inst.state,
                            "district": inst.district, "type": inst.inst_type},
            "kpis": {"students": tot, "approved": ap, "regular": reg, "supernumerary": tot - reg,
                     "fill": round(reg / ap, 3) if ap else None,
                     "apaar_coverage": round(1 - prov / tot, 3) if tot else None, "provisional": prov,
                     "open_errors": issues.get("ERROR", 0), "open_warnings": issues.get("WARN", 0),
                     "statuses": status_counts},
            "programs": programs, "categories": {k: cats.get(k, 0) for k in CATS}, "anomalies": anomalies}


# ------------------------------------------------------------------------- anomalies
@router.get("/anomalies")
def anomalies(p: Principal = Depends(need("anomaly:manage", "institution:read")), db: Session = Depends(get_db),
              status: str | None = None, kind: str | None = None, source: str | None = None, include_inactive: bool = False,
              limit: int = 200):
    stmt = select(Anomaly, Institution).join(Institution, Institution.id == Anomaly.institution_id)
    if p.institution_scoped:
        stmt = stmt.where(Anomaly.institution_id == p.institution_id, Anomaly.source == "RULE")
    if not include_inactive:
        stmt = stmt.where(Anomaly.active.is_(True))
    if status:
        stmt = stmt.where(Anomaly.status == status)
    if kind:
        stmt = stmt.where(Anomaly.kind == kind)
    if source:
        stmt = stmt.where(Anomaly.source == source)
    rows = db.execute(stmt.order_by(Anomaly.score.desc(), Anomaly.id.desc()).limit(limit)).all()
    progs = {pr.id: pr for pr in db.execute(select(Program)).scalars()}
    return [{"id": a.id, "institution_id": a.institution_id, "institution": i.name, "institution_code": i.aicte_code,
             "state": i.state, "program": progs[a.program_id].name if a.program_id else None, "kind": a.kind,
             "source": a.source, "severity": a.severity, "score": a.score, "title": a.title,
             "explanation": a.explanation, "status": a.status, "note": a.note, "active": a.active,
             "updated_at": a.updated_at.isoformat()} for a, i in rows]


class TriageIn(BaseModel):
    status: str
    note: str | None = None


@router.post("/anomalies/{aid}/triage")
def triage(aid: int, body: TriageIn, p: Principal = Depends(need("anomaly:manage")), db: Session = Depends(get_db)):
    a = db.get(Anomaly, aid)
    if not a:
        raise HTTPException(404)
    if body.status not in ("OPEN", "INVESTIGATING", "CONFIRMED", "DISMISSED"):
        raise HTTPException(400, "bad status")
    old = a.status
    a.status, a.note, a.updated_at = body.status, body.note, utcnow()
    audit.record(db, actor=p.label, role=p.role, action="ANOMALY_TRIAGE", resource=f"anomaly:{a.id}",
                 details={"from": old, "to": body.status, "note": body.note})
    db.commit()
    return {"id": a.id, "status": a.status}


@router.post("/anomalies/run")
def run_anomalies(p: Principal = Depends(need("anomaly:manage")), db: Session = Depends(get_db)):
    res = engine.run(db)
    audit.record(db, actor=p.label, role=p.role, action="ANOMALY_RUN", resource="anomalies", details=res)
    db.commit()
    return res


# ------------------------------------------------------------------------- census
@router.get("/census")
def census(p: Principal = Depends(need("census:manage")), db: Session = Depends(get_db)):
    return [{"id": c.id, "year": c.year, "frozen_at": c.frozen_at.isoformat(), "frozen_by": c.frozen_by,
             "students": c.data.get("students"), "programs": len(c.data.get("programs", []))}
            for c in db.execute(select(CensusSnapshot).order_by(CensusSnapshot.id.desc())).scalars()]


@router.post("/census/freeze", summary="Freeze the census snapshot that makes intake checks binding")
def freeze(p: Principal = Depends(need("census:manage")), db: Session = Depends(get_db)):
    y = settings.current_year
    progs = [intake.program_status(db, pr.id, y) for pr in db.execute(select(Program)).scalars()]
    snap = CensusSnapshot(year=y, frozen_by=p.label, data={"students": sum(x["total"] for x in progs),
                                                          "programs": [{k: v for k, v in x.items() if k != "binding"}
                                                                       for x in progs]})
    db.add(snap)
    audit.record(db, actor=p.label, role=p.role, action="CENSUS_FREEZE", resource=f"census:{y}",
                 details={"students": snap.data["students"]})
    db.commit()
    return {"id": snap.id, "students": snap.data["students"]}


class ApprovalRow(BaseModel):
    aicte_code: str
    program_code: str
    approved_intake: int


class ApprovalsIn(BaseModel):
    year: int
    approvals: list[ApprovalRow]


@router.post("/aicte/approvals/import", summary="Import approved intake from the AICTE approval portal feed")
def import_approvals(body: ApprovalsIn, p: Principal = Depends(need("approvals:manage")), db: Session = Depends(get_db)):
    insts = {i.aicte_code: i for i in db.execute(select(Institution)).scalars()}
    changed, unknown = 0, []
    for r in body.approvals:
        inst = insts.get(r.aicte_code)
        prog = inst and db.execute(select(Program).where(Program.institution_id == inst.id,
                                                         Program.code == r.program_code)).scalar_one_or_none()
        if not prog:
            unknown.append(f"{r.aicte_code}/{r.program_code}")
            continue
        ai = db.execute(select(ApprovedIntake).where(ApprovedIntake.program_id == prog.id,
                                                     ApprovedIntake.year == body.year)).scalar_one_or_none()
        if ai is None:
            db.add(ApprovedIntake(program_id=prog.id, year=body.year, approved=r.approved_intake))
            changed += 1
        elif ai.approved != r.approved_intake:
            ai.approved = r.approved_intake
            changed += 1
    audit.record(db, actor=p.label, role=p.role, action="APPROVALS_IMPORT", resource=f"approvals:{body.year}",
                 details={"rows": len(body.approvals), "changed": changed, "unknown": len(unknown)})
    db.commit()
    return {"rows": len(body.approvals), "changed": changed, "unknown": unknown[:50]}
