"""End-to-end checks of every guarantee the MVP claims. Runs against a freshly seeded DB."""
import os
import random
import threading
from datetime import date

import pytest
from sqlalchemy import func, select, text

from app.analytics import counts
from app.auth.deps import Principal
from app.credentials import sdjwt
from app.db import SessionLocal
from app.identity import apaar_client
from app.identity.apaar_format import generate, is_valid
from app.identity.names import name_similarity
from app.ingestion import pipeline
from app.mocks import registry
from app.models import (Anomaly, Conflict, Enrollment, Institution, MockRegistryRecord, Person, ProgramCount,
                        ValidationIssue)
from app.services import jobs

from .conftest import H

ERP = Principal(role="ERP_CLIENT", label="test:erp")


def new_identity(db, name="Test Student", dob=date(2008, 5, 5), gender="F", seed=None):
    rng = random.Random(seed)
    a = generate(rng)
    while db.get(MockRegistryRecord, a):
        a = generate(rng)
    db.add(MockRegistryRecord(apaar_id=a, name=name, dob=dob, gender=gender))
    db.commit()
    return a


def row(apaar, roll, name="Test Student", dob="2008-05-05", program="BTECH-CSE", **kw):
    r = {"roll_no": roll, "apaar_id": apaar, "name": name, "dob": dob, "gender": "F", "parent_name": "Parent Test",
         "qualifying_exam_roll": "", "program_code": program, "admission_date": "2026-11-15", "year_of_study": 1,
         "mode": "REGULAR", "seat_type": "MERIT", "social_category": "GEN", "nationality": "INDIAN"}
    r.update(kw)
    return r


# ----------------------------------------------------------------------------- identity primitives
def test_apaar_checksum_catches_typos():
    rng = random.Random(7)
    for _ in range(200):
        a = generate(rng)
        assert is_valid(a)[0]
        i = rng.randrange(11)
        swapped = a[:i] + a[i + 1] + a[i] + a[i + 2:]
        if swapped != a:
            assert not is_valid(swapped)[0], "adjacent transposition must be caught"
        d = rng.randrange(12)
        typo = a[:d] + str((int(a[d]) + rng.randint(1, 9)) % 10) + a[d + 1:]
        if not typo.startswith("0"):
            assert not is_valid(typo)[0], "single-digit typo must be caught"


@pytest.mark.parametrize("a,b,same", [
    ("R. Karthik", "Karthik Ramasamy", True), ("Kumar Ramesh", "Ramesh Kumar", True),
    ("Lakshmi Priya", "Laxmi Priya", True), ("Lakshmipriya", "Lakshmi Priya", True),
    ("Rohit Agarwal", "Saurabh Agarwal", False), ("Priya Sharma", "Arun Kumar", False),
])
def test_name_similarity(a, b, same):
    assert (name_similarity(a, b) >= 0.85) is same


# ----------------------------------------------------------------------------- the race
def test_simultaneous_submission_exactly_one_active(client, seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    apaar = new_identity(db, name="Race Condition", seed=101)
    inst_a, inst_b = db.get(Institution, ids["demo_a"]), db.get(Institution, ids["demo_b"])
    db.close()
    barrier = threading.Barrier(2)
    results = {}

    def go(inst, roll):
        s = SessionLocal()
        barrier.wait()
        results[inst.id] = pipeline.ingest(s, s.get(Institution, inst.id), [row(apaar, roll, name="Race Condition")],
                                           source="API", actor=ERP)
        s.close()

    ts = [threading.Thread(target=go, args=(inst_a, "RACE-A")), threading.Thread(target=go, args=(inst_b, "RACE-B"))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    db = SessionLocal()
    p = db.execute(select(Person).where(Person.apaar_id == apaar)).scalar_one()
    statuses = sorted(e.status for e in db.execute(select(Enrollment).where(Enrollment.person_id == p.id)).scalars())
    assert statuses == ["ACTIVE", "CONFLICT"]
    assert db.execute(select(func.count()).select_from(Conflict).where(Conflict.person_a_id == p.id,
                                                                        Conflict.kind == "EXACT")).scalar() == 1
    db.close()


def test_unique_index_is_the_backstop(seeded, monkeypatch):
    """Even if the application-level check is skipped (a race on Postgres), the partial
    unique index forces the second insert into CONFLICT."""
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    apaar = new_identity(db, name="Backstop Case", seed=202)
    pipeline.ingest(db, db.get(Institution, ids["demo_a"]), [row(apaar, "BACK-A", name="Backstop Case")],
                    source="API", actor=ERP)
    monkeypatch.setattr(pipeline, "_policy", lambda a, b: "ALLOWED")       # blind the pre-check
    rep = pipeline.ingest(db, db.get(Institution, ids["demo_b"]), [row(apaar, "BACK-B", name="Backstop Case")],
                          source="API", actor=ERP)
    assert rep["conflict"] == 1
    db.close()


def test_dual_programme_policy_allows_regular_plus_odl(seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    apaar = new_identity(db, name="Dual Degree", seed=303)
    pipeline.ingest(db, db.get(Institution, ids["demo_a"]), [row(apaar, "DUAL-A", name="Dual Degree")], source="API", actor=ERP)
    rep = pipeline.ingest(db, db.get(Institution, ids["demo_b"]), [row(apaar, "DUAL-B", name="Dual Degree", mode="ODL")],
                          source="API", actor=ERP)
    assert rep["created"] == 1 and rep["conflict"] == 0
    assert any(f["code"] == "R12" for r in rep["rows"] for f in r["findings"])
    db.close()


# ----------------------------------------------------------------------------- fuzzy duplicates
def test_provisional_cannot_hide_a_duplicate(seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    apaar = new_identity(db, name="Meenakshi Sundaram", dob=date(2008, 2, 2), seed=404)
    pipeline.ingest(db, db.get(Institution, ids["demo_a"]),
                    [row(apaar, "FZ-A", name="Meenakshi Sundaram", dob="2008-02-02", parent_name="Sundaram K")],
                    source="API", actor=ERP)
    # Same student at another college, APAAR omitted, name written initial-first
    rep = pipeline.ingest(db, db.get(Institution, ids["demo_b"]),
                          [row("", "FZ-B", name="S. Meenakshi", dob="2008-02-02", parent_name="Sundaram K")],
                          source="CSV", actor=ERP)
    codes = {f["code"] for r in rep["rows"] for f in r["findings"]}
    assert {"R44", "R11"} <= codes
    db.close()


def test_shared_surname_is_not_a_duplicate(seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    pipeline.ingest(db, db.get(Institution, ids["demo_a"]),
                    [row("", "SN-A", name="Rohit Agarwal", dob="2008-09-09", parent_name="Suresh Agarwal")],
                    source="API", actor=ERP)
    rep = pipeline.ingest(db, db.get(Institution, ids["demo_b"]),
                          [row("", "SN-B", name="Saurabh Agarwal", dob="2008-09-09", parent_name="Mahesh Agarwal")],
                          source="API", actor=ERP)
    assert not any(f["code"] == "R11" for r in rep["rows"] for f in r["findings"])
    db.close()


# ----------------------------------------------------------------------------- intake rules
def test_supernumerary_seats_are_not_false_positives(client, tokens, seeded):
    ids = seeded["scenario_ids"]
    d = client.get(f"/api/v1/analytics/institutions/{ids['control']}", headers=H(tokens["aicte.admin"])).json()
    mech = next(p for p in d["programs"] if p["code"] == "BTECH-MECH")
    assert mech["approved"] == 60 and mech["total"] == 76 and mech["violations"] == []
    d = client.get(f"/api/v1/analytics/institutions/{ids['tfw_abuse']}", headers=H(tokens["aicte.admin"])).json()
    mech = next(p for p in d["programs"] if p["code"] == "BTECH-MECH")
    assert [v["code"] for v in mech["violations"]] == ["R21"]


# ----------------------------------------------------------------------------- CSV upload, error queue
def test_demo_csv_row_level_report_and_fix(client, tokens, demo_dir):
    with open(os.path.join(demo_dir, "1_aarohan_new_admissions.csv"), "rb") as f:
        rep = client.post("/api/v1/enrollments/upload", headers=H(tokens["operator.aarohan"]),
                          files={"file": ("adm.csv", f, "text/csv")}).json()
    codes = {f["code"] for r in rep["rows"] for f in r["findings"]}
    assert {"R40", "R42", "R44", "R31", "R30", "R02", "R23", "R32"} <= codes
    assert rep["created"] == 7 and rep["rejected"] == 7
    issues = client.get("/api/v1/issues?severity=ERROR", headers=H(tokens["operator.aarohan"])).json()["issues"]
    r23 = next(i for i in issues if i["rule_code"] == "R23")
    fixed = {**r23["row_data"], "year_of_study": "2"}
    rep2 = client.post(f"/api/v1/issues/{r23['id']}/fix", json={"row": fixed}, headers=H(tokens["operator.aarohan"])).json()
    assert rep2["created"] == 1
    csv_text = client.get(f"/api/v1/submissions/{rep['submission_id']}/errors.csv",
                          headers=H(tokens["operator.aarohan"])).text
    assert "R42" in csv_text and "_errors" in csv_text


def test_idempotent_batch(client, seeded):
    key = seeded["erp_api_key"]["key"]
    db = SessionLocal()
    apaar = new_identity(db, name="Idem Potent", seed=505)
    db.close()
    body = {"records": [row(apaar, "IDEM-1", name="Idem Potent")]}
    h = {"X-API-Key": key, "Idempotency-Key": "batch-xyz-1"}
    r1 = client.post("/api/v1/enrollments/batch", json=body, headers=h).json()
    r2 = client.post("/api/v1/enrollments/batch", json=body, headers=h).json()
    assert r1["created"] == 1 and r2["replayed"] is True and r2["submission_id"] == r1["submission_id"]


# ----------------------------------------------------------------------------- registry outage
def test_registry_outage_degrades_gracefully(seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    apaar = new_identity(db, name="Outage Student", seed=606)
    registry.control.down = True
    apaar_client.reset()
    try:
        rep = pipeline.ingest(db, db.get(Institution, ids["demo_a"]), [row(apaar, "OUT-1", name="Outage Student")],
                              source="API", actor=ERP)
    finally:
        registry.control.down = False
        apaar_client.reset()
    assert rep["created"] == 1
    assert any(f["code"] == "R43" for r in rep["rows"] for f in r["findings"])
    assert db.execute(select(Person.registry_status).where(Person.apaar_id == apaar)).scalar() == "PENDING"
    db.close()
    jobs.reverify_pending()
    db = SessionLocal()
    assert db.execute(select(Person.registry_status).where(Person.apaar_id == apaar)).scalar() == "VERIFIED"
    db.close()


def test_linking_apaar_later_merges_provisional(seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    apaar = new_identity(db, name="Late Linker", seed=707)
    inst = db.get(Institution, ids["demo_a"])
    pipeline.ingest(db, inst, [row("", "LINK-1", name="Late Linker")], source="FORM", actor=ERP)
    rep = pipeline.ingest(db, inst, [row(apaar, "LINK-1", name="Late Linker")], source="FORM", actor=ERP)
    assert rep["updated"] == 1
    e = db.execute(select(Enrollment).where(Enrollment.roll_no == "LINK-1")).scalar_one()
    assert db.get(Person, e.person_id).apaar_id == apaar
    db.close()


# ----------------------------------------------------------------------------- RBAC + consent
def test_institution_cannot_read_other_institution(client, tokens, seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    other = db.execute(select(Enrollment.id).where(Enrollment.institution_id == ids["demo_b"])).scalars().first()
    db.close()
    assert client.get(f"/api/v1/enrollments/{other}", headers=H(tokens["operator.aarohan"])).status_code == 403
    lst = client.get("/api/v1/enrollments?size=200", headers=H(tokens["operator.aarohan"])).json()
    assert {i["institution_id"] for i in lst["items"]} == {ids["demo_a"]}
    assert client.get(f"/api/v1/analytics/institutions/{ids['demo_b']}", headers=H(tokens["operator.aarohan"])).status_code == 403
    assert client.get("/api/v1/audit", headers=H(tokens["operator.aarohan"])).status_code == 403


def test_consent_enforced_at_read_time(client, tokens, seeded, student_token):
    kavya = seeded["students"][0]["apaar_id"].replace(" ", "")
    dak = H(tokens["admin.dakshin"])
    assert client.get(f"/api/v1/records/{kavya}", headers=dak).status_code == 403
    c = client.post("/api/v1/consents", headers=dak, json={"apaar_id": kavya, "purpose": "Lateral entry verification",
                                                           "fields": ["name", "program", "institution"]}).json()
    st = H(student_token(kavya))
    assert client.post(f"/api/v1/consents/{c['id']}/decide", headers=st, json={"approve": True}).status_code == 200
    rec = client.get(f"/api/v1/records/{kavya}", headers=dak)
    assert rec.status_code == 200
    body = rec.json()
    assert body["name"] == "Kavya Senthil" and "dob" not in body and "social_category" not in body["enrollments"][0]
    client.post(f"/api/v1/consents/{c['id']}/revoke", headers=st)
    assert client.get(f"/api/v1/records/{kavya}", headers=dak).status_code == 403
    log = client.get("/api/v1/me/access-log", headers=st).json()
    actions = {a["action"] for a in log}
    assert {"RECORD_READ", "RECORD_READ_DENIED", "CONSENT_APPROVE", "CONSENT_REVOKE"} <= actions


# ----------------------------------------------------------------------------- credentials
def test_credential_selective_disclosure_tamper_and_revocation(client, tokens, seeded, student_token):
    kavya = seeded["students"][0]["apaar_id"].replace(" ", "")
    st = H(student_token(kavya))
    me = client.get("/api/v1/me/record", headers=st).json()
    eid = next(e["enrollment_id"] for e in me["enrollments"] if e["enrollment_status"] == "ACTIVE")
    cred = client.post("/api/v1/me/credentials", headers=st, json={"enrollment_id": eid}).json()
    vp = sdjwt.present(cred["sd_jwt"], ["name", "program"])
    ok = client.post("/api/v1/verify", json={"presentation": vp, "verifier": "Acme HR"}).json()
    assert ok["valid"] and set(ok["claims"]) == {"name", "program"}          # category/DOB never left the wallet
    jwt_part, *discs = vp.split("~")
    import base64
    import json as _j
    salt, k, v = _j.loads(base64.urlsafe_b64decode(discs[0] + "=="))
    forged = base64.urlsafe_b64encode(_j.dumps([salt, k, "Someone Else"]).encode()).rstrip(b"=").decode()
    bad = client.post("/api/v1/verify", json={"presentation": "~".join([jwt_part, forged, *discs[1:]])}).json()
    assert not bad["valid"] and "altered" in bad["reason"]
    sig_flip = jwt_part[:-3] + ("A" if jwt_part[-3] != "A" else "B") + jwt_part[-2:]
    assert not client.post("/api/v1/verify", json={"presentation": "~".join([sig_flip, *discs])}).json()["valid"]
    r = client.post(f"/api/v1/credentials/{cred['id']}/revoke", headers=H(tokens["admin.aarohan"]), json={"reason": "test"})
    assert r.status_code == 200
    rev = client.post("/api/v1/verify", json={"presentation": vp}).json()
    assert not rev["valid"] and "revoked" in rev["reason"]
    log = client.get("/api/v1/me/access-log", headers=st).json()
    assert any(a["action"] == "VERIFY_ONLINE" and "Acme HR" in a["actor"] for a in log)


def test_degree_certificate(client, tokens, seeded):
    reg = H(tokens["registrar.tnstu"])
    grads = client.get("/api/v1/university/graduates", headers=reg).json()
    divya = next(g for g in grads if g["name"] == "Divya Krishnan")
    d = client.post("/api/v1/university/degrees", headers=reg,
                    json={"enrollment_id": divya["enrollment_id"], "class_awarded": "First Class with Distinction",
                          "cgpa": 8.9}).json()
    pdf = client.get(f"/api/v1/credentials/{d['id']}/certificate.pdf", headers=reg)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


# ----------------------------------------------------------------------------- audit
def test_audit_chain_detects_tampering(client, tokens):
    h = H(tokens["aicte.admin"])
    assert client.get("/api/v1/audit/verify", headers=h).json()["ok"]
    db = SessionLocal()
    target = db.execute(text("SELECT id, actor FROM audit_log ORDER BY id LIMIT 1 OFFSET 5")).one()
    db.execute(text("UPDATE audit_log SET actor = 'nobody' WHERE id = :i"), {"i": target.id})
    db.commit()
    res = client.get("/api/v1/audit/verify", headers=h).json()
    assert not res["ok"] and res["broken_at"] == target.id
    db.execute(text("UPDATE audit_log SET actor = :a WHERE id = :i"), {"a": target.actor, "i": target.id})
    db.commit()
    db.close()
    assert client.get("/api/v1/audit/verify", headers=h).json()["ok"]


def test_mfa_required_for_aicte(client, seeded):
    r = client.post("/api/v1/auth/login", json={"username": "aicte.admin", "password": "Aicte@2026"}).json()
    assert r.get("mfa_required") and "access_token" not in r
    bad = client.post("/api/v1/auth/mfa", json={"mfa_token": r["mfa_token"], "code": "000000"})
    assert bad.status_code == 401


# ----------------------------------------------------------------------------- anomalies + counters
def test_every_seeded_fraud_scenario_is_detected(seeded):
    ids = seeded["scenario_ids"]
    db = SessionLocal()
    found = {(a.institution_id, a.kind) for a in db.execute(select(Anomaly).where(Anomaly.active.is_(True))).scalars()}
    conflicts = db.execute(select(func.count()).select_from(Conflict).where(Conflict.kind == "EXACT")).scalar()
    db.close()
    assert (ids["ghost"], "FILL_RATE_JUMP") in found and (ids["ghost"], "PROVISIONAL_SHARE") in found
    assert (ids["jump"], "FILL_RATE_JUMP") in found
    assert (ids["ews"], "CATEGORY_SHIFT") in found
    assert (ids["tfw_abuse"], "SUPERNUMERARY_EXCEEDED") in found
    assert (ids["overflow"], "INTAKE_EXCEEDED") in found
    assert not any(i == ids["control"] for i, _ in found), "the legal 76-on-60 college must not be flagged"
    assert conflicts >= 25


def test_transfer_handshake_is_atomic(client, tokens, seeded, student_token):
    ids = seeded["scenario_ids"]
    vig = seeded["students"][1]["apaar_id"].replace(" ", "")
    progs = client.get(f"/api/v1/institutions/{ids['demo_b']}/programs/list", headers=H(tokens["admin.dakshin"])).json()
    cse = next(p for p in progs if p["code"] == "BTECH-CSE")
    t = client.post("/api/v1/transfers", headers=H(tokens["admin.dakshin"]),
                    json={"apaar_id": vig, "to_program_id": cse["id"], "to_roll_no": "26TRF001"}).json()
    st = H(student_token(vig))
    consent = next(c for c in client.get("/api/v1/consents", headers=st).json() if c["transfer_id"] == t["id"])
    client.post(f"/api/v1/consents/{consent['id']}/decide", headers=st, json={"approve": True})
    r = client.post(f"/api/v1/transfers/{t['id']}/release", headers=H(tokens["admin.aarohan"]))
    assert r.status_code == 200, r.text
    me = client.get("/api/v1/me/record", headers=st).json()
    by_inst = {e["institution_id"]: e["enrollment_status"] for e in me["enrollments"]}
    assert by_inst[ids["demo_a"]] == "TRANSFERRED_OUT" and by_inst[ids["demo_b"]] == "ACTIVE"


def test_incremental_counters_equal_recompute(seeded):
    db = SessionLocal()
    snap = {(pc.program_id): (pc.total, {k: v for k, v in pc.counts.items() if v})
            for pc in db.execute(select(ProgramCount).where(ProgramCount.year == 2026)).scalars()}
    counts.recompute(db, 2026)
    db.flush()
    again = {(pc.program_id): (pc.total, {k: v for k, v in pc.counts.items() if v})
             for pc in db.execute(select(ProgramCount).where(ProgramCount.year == 2026)).scalars()}
    db.rollback()
    db.close()
    diff = {k: (snap.get(k), again.get(k)) for k in set(snap) | set(again) if snap.get(k) != again.get(k)}
    assert not diff, f"counter drift: {list(diff.items())[:3]}"


def test_webhooks_are_signed_and_delivered(client, seeded):
    from app.services import webhooks
    db = SessionLocal()
    webhooks.enqueue(db)
    n = webhooks.deliver_due(db, client)
    db.close()
    assert n > 0
    got = client.get(f"/mock/erp/{seeded['scenario_ids']['demo_a']}/received").json()
    assert got and all(g["signature_valid"] for g in got)


def test_issue_open_warnings_visible_to_institution_only_rules(client, tokens, seeded):
    ids = seeded["scenario_ids"]
    an = client.get("/api/v1/anomalies", headers=H(tokens["operator.aarohan"]))
    assert an.status_code == 200 and all(a["source"] == "RULE" for a in an.json())
    db = SessionLocal()
    assert db.execute(select(func.count()).select_from(ValidationIssue)).scalar() > 0
    db.close()
