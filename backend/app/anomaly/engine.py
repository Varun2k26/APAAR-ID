"""Statistical anomaly detection. Every anomaly carries an explanation an officer can read.

Detectors
  FILL_RATE_JUMP     fill rate vs the institution's own 5-year history (robust z on median/MAD)
                     AND vs peers (same state + discipline). Uses fill rate, not raw counts, so a
                     college that was *approved* for 3x seats is not flagged for admitting 3x.
  CATEGORY_SHIFT     Jensen-Shannon divergence of this year's category mix vs history, a
                     chi-square test for significance, and a peer comparison.
  PROVISIONAL_SHARE  share of students without APAAR far above peers (the ghost-student pattern).
  MULTIVARIATE       Isolation Forest over a per-institution feature vector; explained by the
                     features that deviate most from the median institution.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import chisquare
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (Anomaly, ApprovedIntake, Conflict, Enrollment, Institution, IntakeHistory, Program,
                      ProgramCount, ValidationIssue, utcnow)
from ..services import events
from .rules import refresh_programs, upsert

log = logging.getLogger("anomaly")
CATS = ["GEN", "EWS", "OBC-NCL", "SC", "ST"]
STAT_KINDS = ("FILL_RATE_JUMP", "CATEGORY_SHIFT", "PROVISIONAL_SHARE", "MULTIVARIATE")
FEATURE_LABELS = {
    "fill_rate": "Fill rate", "fill_delta": "Change in fill rate from five-year median",
    "provisional_share": "Share reported without APAAR ID", "late_share": "Share reported late",
    "category_entropy": "Category mix compared with the state", "churn_rate": "Withdrawals and transfers during the year",
    "conflict_rate": "Share in duplicate enrolment cases", "mismatch_rate": "Rows rejected for APAAR mismatch",
}


def _robust_z(x: float, ref: np.ndarray, floor: float) -> float:
    if len(ref) == 0:
        return 0.0
    med = float(np.median(ref))
    mad = float(np.median(np.abs(ref - med))) * 1.4826
    return (x - med) / max(mad, floor)


def _entropy(counts: dict) -> float:
    tot = sum(counts.values())
    if not tot:
        return 0.0
    return -sum((c / tot) * math.log2(c / tot) for c in counts.values() if c)


def gather(db: Session, year: int) -> dict:
    """Pull everything the detectors need in a few queries; computation happens outside the DB."""
    insts = {i.id: {"name": i.name, "state": i.state} for i in db.execute(select(Institution)).scalars()}
    progs = {p.id: {"institution_id": p.institution_id, "discipline": p.discipline}
             for p in db.execute(select(Program)).scalars()}
    approved = defaultdict(dict)
    for a in db.execute(select(ApprovedIntake)).scalars():
        approved[a.program_id][a.year] = a.approved
    hist = defaultdict(dict)
    for h in db.execute(select(IntakeHistory)).scalars():
        hist[h.program_id][h.year] = (h.admitted, h.categories)
    cur = {pc.program_id: (pc.total, dict(pc.counts or {}))
           for pc in db.execute(select(ProgramCount).where(ProgramCount.year == year)).scalars()}
    churn = dict(db.execute(select(Enrollment.institution_id, func.count()).where(
        Enrollment.academic_year == year, Enrollment.status.in_(("DROPPED", "TRANSFERRED_OUT")))
        .group_by(Enrollment.institution_id)).all())
    conflict_enr = set()
    for a, b in db.execute(select(Conflict.enrollment_a_id, Conflict.enrollment_b_id)
                           .where(Conflict.status.in_(("OPEN", "STUDENT_CONFIRMED")))).all():
        conflict_enr.update((a, b))
    conflicts = defaultdict(int)
    if conflict_enr:
        for inst_id, n in db.execute(select(Enrollment.institution_id, func.count()).where(
                Enrollment.id.in_(conflict_enr)).group_by(Enrollment.institution_id)).all():
            conflicts[inst_id] = n
    mismatch = dict(db.execute(select(ValidationIssue.institution_id, func.count()).where(
        ValidationIssue.rule_code.in_(("R41", "R42"))).group_by(ValidationIssue.institution_id)).all())
    return {"insts": insts, "progs": progs, "approved": approved, "hist": hist, "cur": cur, "churn": churn,
            "conflicts": conflicts, "mismatch": mismatch}


def compute(data: dict, year: int) -> list[dict]:
    insts, progs, approved, hist, cur = data["insts"], data["progs"], data["approved"], data["hist"], data["cur"]
    past = list(range(year - 5, year))
    findings: list[dict] = []

    # ---------------- per-institution aggregates
    inst_pids = defaultdict(list)
    for pid, pr in progs.items():
        inst_pids[pr["institution_id"]].append(pid)
    inst_rows = {}
    for iid in insts:
        pids = inst_pids[iid]
        appr_now = sum(approved[p].get(year, 0) for p in pids)
        c = defaultdict(int)
        total = 0
        for p in pids:
            if p in cur:
                total += cur[p][0]
                for k, v in cur[p][1].items():
                    c[k] += v
        regular = c["seat:MERIT"] + c["seat:MANAGEMENT"] + c["seat:NRI"]
        fills_hist = []
        for y in past:
            ad = sum(hist[p].get(y, (0, {}))[0] for p in pids)
            ap = sum(approved[p].get(y, 0) for p in pids)
            if ap:
                fills_hist.append(ad / ap)
        hist_cats = defaultdict(int)
        for p in pids:
            for y in past:
                for k, v in hist[p].get(y, (0, {}))[1].items():
                    hist_cats[k] += v
        cur_cats = {k: c.get(f"cat:{k}", 0) for k in CATS}
        inst_rows[iid] = {
            "inst": insts[iid], "approved": appr_now, "total": total, "regular": regular,
            "fill": regular / appr_now if appr_now else 0.0, "fills_hist": np.array(fills_hist),
            "cur_cats": cur_cats, "hist_cats": {k: hist_cats.get(k, 0) for k in CATS},
            "prov": c.get("prov", 0), "late": c.get("late", 0),
            "discipline": _main_discipline(pids, progs, approved, year),
        }
    live = {k: r for k, r in inst_rows.items() if r["total"] >= 10 and len(r["fills_hist"]) >= 3}

    # ---------------- FILL_RATE_JUMP
    deltas = {k: r["fill"] - float(np.median(r["fills_hist"])) for k, r in live.items()}
    peer_groups = defaultdict(list)
    for k, r in live.items():
        peer_groups[(r["inst"]["state"], r["discipline"])].append(k)
    for k, r in live.items():
        d = deltas[k]
        own_z = _robust_z(r["fill"], r["fills_hist"], 0.04)
        peers = [deltas[j] for j in peer_groups[(r["inst"]["state"], r["discipline"])] if j != k]
        if len(peers) < 4:
            peers = [deltas[j] for j in live if j != k]
        peer_z = _robust_z(d, np.array(peers), 0.03)
        if d >= 0.25 and own_z >= 3.0 and peer_z >= 2.5:
            med = float(np.median(r["fills_hist"]))
            ratio = r["fill"] / med if med else float("inf")
            findings.append({
                "institution_id": k, "kind": "FILL_RATE_JUMP",
                "severity": "HIGH" if ratio >= 2 else "MEDIUM", "score": round(min(1.0, d + 0.3), 3),
                "title": f"Fill rate rose from {med:.0%} to {r['fill']:.0%}, {ratio:.1f} times the five-year median",
                "explanation": {
                    "summary": f"Regular admissions filled {r['fill']:.0%} of approved seats this year, against a five-year "
                               f"median of {med:.0%}. Institutions in the same state and discipline changed by "
                               f"{float(np.median(peers)) * 100:+.0f} percentage points.",
                    "history_fill": [round(x, 3) for x in r["fills_hist"].tolist()], "current_fill": round(r["fill"], 3),
                    "own_robust_z": round(own_z, 2), "peer_robust_z": round(peer_z, 2),
                    "why_fill_rate": "Measured as fill rate rather than headcount, so an approved increase in intake "
                                     "does not trigger it.",
                    "pattern": "A sharp rise to near-full intake at an institution with historically low fill is "
                               "consistent with admissions reported to claim fee reimbursement or scholarships for "
                               "students who are not attending."}})

    # ---------------- CATEGORY_SHIFT
    jsds = {}
    for k, r in live.items():
        hc, cc = r["hist_cats"], r["cur_cats"]
        if sum(hc.values()) < 50 or sum(cc.values()) < 20:
            continue
        p = np.array([hc[c] + 0.5 for c in CATS], dtype=float)
        q = np.array([cc[c] + 0.5 for c in CATS], dtype=float)
        jsds[k] = (float(jensenshannon(q / q.sum(), p / p.sum(), base=2) ** 2), p, q)
    by_state = defaultdict(list)
    for k in jsds:
        by_state[live[k]["inst"]["state"]].append(k)
    for k, (jsd, p, q) in jsds.items():
        peers = np.array([jsds[j][0] for j in by_state[live[k]["inst"]["state"]] if j != k] or [0.0])
        peer_z = _robust_z(jsd, peers, 0.005)
        exp = p / p.sum() * q.sum()
        pval = float(chisquare(q, exp).pvalue)
        if jsd >= 0.03 and pval < 1e-3 and peer_z >= 3.0:
            shares_h, shares_c = p / p.sum(), q / q.sum()
            moves = sorted(((CATS[i], shares_h[i], shares_c[i]) for i in range(len(CATS))),
                           key=lambda t: abs(t[2] - t[1]), reverse=True)
            top = moves[0]
            findings.append({
                "institution_id": k, "kind": "CATEGORY_SHIFT",
                "severity": "HIGH" if jsd >= 0.08 else "MEDIUM", "score": round(min(1.0, jsd * 6), 3),
                "title": f"{top[0]} share {'rose' if top[2] > top[1] else 'fell'} from {top[1]:.0%} to {top[2]:.0%}",
                "explanation": {
                    "summary": f"This year's distribution across social categories differs significantly from the "
                               f"institution's five-year history (Jensen-Shannon divergence {jsd:.3f}, chi-square "
                               f"p = {pval:.1e}) and from other institutions in the state.",
                    "moves": [{"category": c, "history": round(h, 3), "current": round(cu, 3)} for c, h, cu in moves],
                    "peer_robust_z": round(peer_z, 2),
                    "pattern": "Large shifts towards categories eligible for fee waivers, scholarships or reserved "
                               "seats should be checked against category certificates."}})

    # ---------------- PROVISIONAL_SHARE
    shares = {k: r["prov"] / r["total"] for k, r in live.items()}
    all_sh = np.array(list(shares.values()) or [0.0])
    for k, sh in shares.items():
        z = _robust_z(sh, all_sh, 0.02)
        if sh >= settings.provisional_share_flag and z >= 3.0:
            findings.append({
                "institution_id": k, "kind": "PROVISIONAL_SHARE", "severity": "HIGH" if sh >= 0.3 else "MEDIUM",
                "score": round(min(1.0, sh * 2), 3),
                "title": f"{sh:.0%} of students reported without an APAAR ID (national median {float(np.median(all_sh)):.0%})",
                "explanation": {
                    "summary": f"{live[k]['prov']} of {live[k]['total']} students were reported without an APAAR ID.",
                    "share": round(sh, 3), "median_share": round(float(np.median(all_sh)), 3), "robust_z": round(z, 2),
                    "pattern": "Reporting students without an APAAR ID avoids identity verification. These records "
                               "are still matched against other institutions, but a high share warrants inspection."}})

    # ---------------- MULTIVARIATE (Isolation Forest)
    keys = list(live)
    # Entropy is compared with the state's own median: Tamil Nadu's 69% reservation makes a
    # concentrated mix normal there, so raw entropy would flag every TN college.
    state_ent = defaultdict(list)
    for k in keys:
        state_ent[live[k]["inst"]["state"]].append(_entropy(live[k]["cur_cats"]))
    state_med = {st: float(np.median(v)) for st, v in state_ent.items()}
    if len(keys) >= 20:
        feats = []
        for k in keys:
            r = live[k]
            tot = max(1, r["total"])
            feats.append({
                "fill_rate": r["fill"], "fill_delta": deltas[k], "provisional_share": r["prov"] / tot,
                "late_share": r["late"] / tot,
                "category_entropy": abs(_entropy(r["cur_cats"]) - state_med[r["inst"]["state"]]),
                "churn_rate": data["churn"].get(k, 0) / tot, "conflict_rate": data["conflicts"].get(k, 0) / tot,
                "mismatch_rate": data["mismatch"].get(k, 0) / tot,
            })
        names = list(feats[0])
        X = np.array([[f[n] for n in names] for f in feats])
        Xs = RobustScaler().fit_transform(X)
        Xs = np.clip(np.nan_to_num(Xs), -50, 50)
        model = IsolationForest(n_estimators=300, contamination=0.05, random_state=7).fit(Xs)
        scores = -model.score_samples(Xs)
        pred = model.predict(Xs)
        med = np.median(X, axis=0)
        for idx, k in enumerate(keys):
            if pred[idx] != -1:
                continue
            contrib = sorted(((names[j], float(Xs[idx, j]), float(X[idx, j]), float(med[j])) for j in range(len(names))),
                             key=lambda t: abs(t[1]), reverse=True)
            top = [c for c in contrib if abs(c[1]) >= 2][:3]
            if not top or abs(top[0][1]) < 3.5:
                continue        # Isolation Forest always isolates *someone*; only report a clear driver
            findings.append({
                "institution_id": k, "kind": "MULTIVARIATE", "severity": "MEDIUM",
                "score": round(float(min(1.0, scores[idx] - 0.35)), 3),
                "title": "Unusual combination of indicators: " + ", ".join(
                    FEATURE_LABELS[c[0]].lower().replace("apaar id", "APAAR ID") for c in top),
                "explanation": {
                    "summary": "This institution differs from most others on several indicators at once (Isolation "
                               "Forest). The main factors are listed with the national median for comparison.",
                    "drivers": [{"feature": FEATURE_LABELS[n], "value": round(v, 3), "median": round(m, 3),
                                 "robust_z": round(z, 1)} for n, z, v, m in top],
                    "anomaly_score": round(float(scores[idx]), 3)}})
    return findings


def _main_discipline(pids, progs, approved, year) -> str:
    acc = defaultdict(int)
    for p in pids:
        acc[progs[p]["discipline"]] += approved[p].get(year, 0)
    return max(acc, key=acc.get) if acc else "?"


def run(db: Session, year: int | None = None) -> dict:
    """Recompute all anomalies. Reads in one pass, computes in memory, writes in one short pass."""
    year = year or settings.current_year
    data = gather(db, year)
    db.rollback()          # plain data only from here on: release the read transaction before compute
    found = compute(data, year)
    seen = set()
    new = 0
    for f in found:
        a, is_new = upsert(db, institution_id=f["institution_id"], program_id=None, kind=f["kind"], source="STATISTICAL",
                           severity=f["severity"], score=f["score"], title=f["title"], explanation=f["explanation"],
                           year=year)
        seen.add(a.id)
        if is_new:
            new += 1
            events.emit(db, "ANOMALY_RAISED", institution_id=None, payload={
                "anomaly_id": a.id, "kind": a.kind, "title": a.title, "institution_id": a.institution_id,
                "institution": data["insts"][a.institution_id]["name"], "severity": a.severity})
    for a in db.execute(select(Anomaly).where(Anomaly.source == "STATISTICAL", Anomaly.year == year,
                                              Anomaly.active.is_(True))).scalars():
        if a.id not in seen:
            a.active, a.updated_at = False, utcnow()
    rule = refresh_programs(db, [p for p in data["progs"]])
    db.commit()
    return {"statistical": len(found), "new": new, "rule_alerts": len(rule)}
