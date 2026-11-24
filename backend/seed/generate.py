"""Synthetic national dataset + demo actors + injected fraud scenarios.

    uv run python -m seed.generate            # resets the database

Baseline data is bulk-inserted (fast). Every fraud scenario, and the demo CSVs, go through
the REAL ingestion pipeline, so the conflicts, issues and anomalies the demo shows are produced
by production code, not hand-placed.
"""
from __future__ import annotations

import csv
import json
import random
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import insert, select, text

from app.analytics import counts
from app.anomaly import engine as anomaly_engine
from app.auth.deps import Principal
from app.auth.security import hash_password, new_api_key
from app.config import DATA_DIR, settings
from app.credentials import keys
from app.db import Base, SessionLocal, engine
from app.identity import apaar_client
from app.identity.apaar_format import generate as gen_apaar, pretty
from app.identity.names import normalize, phonetic_key
from app.ingestion.pipeline import ingest
from app.models import (ApiKey, ApprovedIntake, Enrollment, Event, Institution, IntakeHistory, JobState,
                        MockRegistryRecord, Person, Program, University, User, Webhook)
from app.services import audit
from app.services.events import WEBHOOK_EVENT_TYPES

from .names import REGIONS, STATE_REGION

R = random.Random(2026)
Y = settings.current_year
PAST = list(range(Y - 5, Y))

STATES = {
    "TN": ("Tamil Nadu", ["Coimbatore", "Chennai", "Madurai", "Salem", "Tiruppur", "Erode", "Tiruchirappalli"], 16),
    "MH": ("Maharashtra", ["Pune", "Nagpur", "Nashik", "Mumbai", "Aurangabad"], 14),
    "KA": ("Karnataka", ["Bengaluru", "Mysuru", "Mangaluru", "Belagavi"], 10),
    "AP": ("Andhra Pradesh", ["Visakhapatnam", "Guntur", "Nellore", "Tirupati"], 10),
    "TS": ("Telangana", ["Hyderabad", "Warangal", "Karimnagar"], 9),
    "UP": ("Uttar Pradesh", ["Lucknow", "Kanpur", "Noida", "Agra", "Varanasi"], 12),
    "KL": ("Kerala", ["Kochi", "Thiruvananthapuram", "Kozhikode"], 7),
    "GJ": ("Gujarat", ["Ahmedabad", "Vadodara", "Surat", "Rajkot"], 9),
    "RJ": ("Rajasthan", ["Jaipur", "Jodhpur", "Kota", "Udaipur"], 8),
    "WB": ("West Bengal", ["Kolkata", "Durgapur", "Siliguri"], 7),
    "MP": ("Madhya Pradesh", ["Bhopal", "Indore", "Jabalpur", "Gwalior"], 9),
    "DL": ("Delhi", ["New Delhi", "Dwarka", "Rohini"], 5),
}
ROOTS = ["Aarohan", "Dakshin", "Jyotirmay", "Navoday", "Pragyan", "Sankalp", "Tejasvi", "Unnati", "Vaibhav", "Yashasvi",
         "Amrutha", "Bharati Vidya", "Chandrakala", "Dhanvantri", "Ekalavya", "Gyanodaya", "Himgiri", "Indraprastha",
         "Jnana Deepa", "Kalpataru", "Lokmanya", "Madhuvan", "Nalanda Vihar", "Omkareshwar", "Pratibha", "Ritambhara",
         "Saraswati Vidya", "Tapovan", "Udayagiri", "Vishwakarma", "Arunodaya", "Bodhi", "Chaitanya", "Dhruva",
         "Kaveri", "Shivalik", "Tamraparni", "Vindhya", "Narmada", "Sahyadri", "Aravalli", "Brahmaputra", "Konark",
         "Hampi", "Ajanta", "Sanchi", "Kalinga", "Malabar", "Kongunadu", "Deccan"]
CATALOG = {
    "BTECH-CSE": ("B.Tech Computer Science & Engineering", "Engineering & Technology", "UG", 4, [60, 120, 180]),
    "BTECH-ECE": ("B.Tech Electronics & Communication", "Engineering & Technology", "UG", 4, [60, 120]),
    "BTECH-MECH": ("B.Tech Mechanical Engineering", "Engineering & Technology", "UG", 4, [60, 120]),
    "BTECH-CIVIL": ("B.Tech Civil Engineering", "Engineering & Technology", "UG", 4, [60]),
    "BTECH-EEE": ("B.Tech Electrical & Electronics", "Engineering & Technology", "UG", 4, [60]),
    "BTECH-IT": ("B.Tech Information Technology", "Engineering & Technology", "UG", 4, [60]),
    "BTECH-AIDS": ("B.Tech AI & Data Science", "Engineering & Technology", "UG", 4, [60, 120]),
    "MBA": ("Master of Business Administration", "Management", "PG", 2, [60, 120]),
    "PGDM": ("Post Graduate Diploma in Management", "Management", "PGDM", 2, [60, 120]),
    "MCA": ("Master of Computer Applications", "Computer Applications", "PG", 2, [60]),
    "BPHARM": ("B.Pharm", "Pharmacy", "UG", 4, [60, 100]),
    "DPHARM": ("D.Pharm", "Pharmacy", "DIPLOMA", 2, [60]),
    "DIP-MECH": ("Diploma in Mechanical Engineering", "Engineering & Technology", "DIPLOMA", 3, [60]),
    "DIP-CIVIL": ("Diploma in Civil Engineering", "Engineering & Technology", "DIPLOMA", 3, [60]),
    "DIP-EEE": ("Diploma in Electrical Engineering", "Engineering & Technology", "DIPLOMA", 3, [60]),
    "DIP-CSE": ("Diploma in Computer Engineering", "Engineering & Technology", "DIPLOMA", 3, [60]),
}
PROFILES = {
    "ENGG": (["BTECH-CSE", "BTECH-ECE", "BTECH-MECH", "BTECH-CIVIL", "BTECH-EEE", "BTECH-IT", "BTECH-AIDS"],
             ["Institute of Technology", "College of Engineering", "Engineering College"]),
    "MGMT": (["MBA", "PGDM"], ["School of Management", "Institute of Management"]),
    "PHARM": (["BPHARM", "DPHARM"], ["College of Pharmacy"]),
    "POLY": (["DIP-MECH", "DIP-CIVIL", "DIP-EEE", "DIP-CSE"], ["Polytechnic College"]),
}
CAT_BASE = {"TN": [.10, .02, .70, .16, .02], "KL": [.35, .08, .40, .12, .05], "default": [.40, .09, .30, .14, .07]}
CATS = ["GEN", "EWS", "OBC-NCL", "SC", "ST"]
EXAM = {"TN": "TNEA", "MH": "MHTCET", "KA": "KCET", "AP": "APEAPCET", "TS": "TSEAMCET", "KL": "KEAM", "WB": "WBJEE",
        "GJ": "GUJCET", "default": "JEEMAIN"}
SYSTEM = Principal(role="ERP_CLIENT", label="seed:erp-sync")


def pick_name(state: str, gender: str, rng=R) -> tuple[str, str]:
    reg = REGIONS[STATE_REGION[state]]
    first = rng.choice(reg["F" if gender == "F" else "M"])
    sur = rng.choice(reg["S"])
    father = rng.choice(reg["M"])
    if STATE_REGION[state] == "tamil":
        return f"{first} {father}", f"{father} {sur[0]}"
    return f"{first} {sur}", f"{father} {sur}"


def initial_variant(name: str) -> str:
    """'Karthik Ramasamy' -> 'R. Karthik' (Tamil-style initial-first spelling)."""
    parts = name.split()
    return f"{parts[-1][0]}. {' '.join(parts[:-1])}" if len(parts) >= 2 else name


def rand_date(a: date, b: date, rng=R) -> date:
    return a + timedelta(days=rng.randint(0, (b - a).days))


def dirichlet(base, conc=60, rng=R):
    xs = [rng.gammavariate(max(b * conc, 0.05), 1) for b in base]
    s = sum(xs)
    return [x / s for x in xs]


def choose(weights, rng=R):
    return rng.choices(CATS, weights=weights)[0]


class Seeder:
    def __init__(self):
        self.pid = 0
        self.eid = 0
        self.persons: list[dict] = []
        self.enrollments: list[dict] = []
        self.registry: list[dict] = []
        self.apaars: set[str] = set()
        self.exam_seq = 100000

    def apaar(self, rng=R) -> str:
        while True:
            a = gen_apaar(rng)
            if a not in self.apaars:
                self.apaars.add(a)
                return a

    def exam_roll(self, state: str) -> str:
        self.exam_seq += R.randint(1, 37)
        return f"{EXAM.get(state, EXAM['default'])}{Y}-{self.exam_seq}"

    def person(self, state, level, *, gender=None, apaar=True, name=None, parent=None, dob=None, registry=True,
               exempt=False) -> dict:
        gender = gender or ("F" if R.random() < 0.44 else "M")
        if not name:
            name, parent = pick_name(state, gender)
        if dob is None:
            age = {"UG": 18, "DIPLOMA": 16, "PG": 22, "PGDM": 23}.get(level, 18)
            dob = rand_date(date(Y - age - 1, 6, 1), date(Y - age, 5, 31))
        self.pid += 1
        a = self.apaar() if apaar else None
        p = {"id": self.pid, "apaar_id": a,
             "provisional_id": None if a else (f"INTL-{Y}-S{self.pid:06d}" if exempt else f"PROV-{Y}-S{self.pid:06d}"),
             "name": name, "name_norm": normalize(name), "name_key": phonetic_key(name), "dob": dob, "gender": gender,
             "parent_name": parent, "parent_key": phonetic_key(parent) or None, "exam_roll": self.exam_roll(state),
             "registry_status": "VERIFIED" if a else ("EXEMPT" if exempt else "PROVISIONAL"), "registry_checked_at": datetime(Y, 8, 20) if a else None,
             "link_deadline": None if a else date(Y, 12, 31), "created_at": datetime(Y, 8, 1)}
        self.persons.append(p)
        if a and registry:
            self.registry.append({"apaar_id": a, "name": name, "dob": dob, "gender": gender, "status": "ACTIVE"})
        return p

    def enroll(self, p, inst_id, prog, roll, *, year=Y, seat="MERIT", cat="GEN", nat="INDIAN", yos=1, status="ACTIVE",
               adm=None, lag=None, mode="REGULAR") -> dict:
        self.eid += 1
        adm = adm or rand_date(date(year, 7, 15), date(year, 9, 30))
        lag = lag if lag is not None else (R.randint(0, 25) if R.random() > 0.03 else R.randint(46, 70))
        rep = datetime.combine(adm, datetime.min.time()) + timedelta(days=lag, hours=R.randint(9, 18))
        e = {"id": self.eid, "person_id": p["id"], "institution_id": inst_id, "program_id": prog.id, "roll_no": roll,
             "academic_year": year, "admission_date": adm, "year_of_study": yos, "mode": mode, "seat_type": seat,
             "social_category": cat, "nationality": nat, "status": status, "reported_at": rep, "source": "SEED",
             "created_at": rep, "updated_at": rep}
        self.enrollments.append(e)
        return e


def main(reset: bool = True) -> None:
    t0 = time.time()
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    apaar_client.reset()
    S = Seeder()
    db = SessionLocal()

    # ------------------------------------------------------------------ universities, institutions, programs
    unis = {}
    for code, (sname, _d, _n) in STATES.items():
        u = University(code=f"{code}STU", name=f"{sname} State Technical University", state=code)
        db.add(u)
        unis[code] = u
    db.flush()

    roots = ROOTS[:]
    R.shuffle(roots)
    forced = {("TN", 0): ("Aarohan", "ENGG", "Coimbatore", "PRIVATE"), ("TN", 1): ("Dakshin", "ENGG", "Salem", "PRIVATE"),
              ("TN", 2): ("Kaveri", "ENGG", "Madurai", "PRIVATE"), ("TN", 3): ("Tamraparni", "ENGG", "Tiruppur", "PRIVATE"),
              ("UP", 0): ("Gyanodaya", "ENGG", "Kanpur", "PRIVATE"), ("MH", 0): ("Sahyadri", "ENGG", "Nashik", "PRIVATE"),
              ("KA", 0): ("Hampi", "ENGG", "Mysuru", "PRIVATE"), ("GJ", 0): ("Narmada", "ENGG", "Vadodara", "PRIVATE"),
              ("RJ", 0): ("Aravalli", "ENGG", "Kota", "PRIVATE"), ("MP", 0): ("Vindhya", "ENGG", "Indore", "PRIVATE")}
    used_roots = {v[0] for v in forced.values()}
    roots = [r for r in roots if r not in used_roots]
    insts, progs_by_inst, inst_meta = [], defaultdict(list), {}
    seq = defaultdict(int)
    for st, (sname, districts, n) in STATES.items():
        for k in range(n):
            if (st, k) in forced:
                root, prof, dist, typ = forced[(st, k)]
            else:
                root = roots.pop() if roots else R.choice(ROOTS) + " " + R.choice(["Vidyapeeth", "Gurukulam"])
                prof = R.choices(list(PROFILES), weights=[60, 12, 10, 18])[0]
                dist = R.choice(districts)
                typ = R.choices(["PRIVATE", "GOVT", "AIDED"], weights=[70, 18, 12])[0]
            seq[st] += 1
            noun = R.choice(PROFILES[prof][1]) if (st, k) not in forced else "Institute of Technology" \
                if root == "Aarohan" else "College of Engineering"
            inst = Institution(aicte_code=f"AIC-{st}-{seq[st]:04d}", name=f"{root} {noun}, {dist}", state=st, district=dist,
                               inst_type=typ, university_id=unis[st].id)
            db.add(inst)
            insts.append(inst)
            inst_meta[inst.aicte_code] = {"profile": prof, "forced": (st, k) in forced, "key": root}
    db.flush()

    approved = defaultdict(dict)
    hist_rows, appr_rows = [], []
    for inst in insts:
        meta = inst_meta[inst.aicte_code]
        codes, _ = PROFILES[meta["profile"]]
        if meta["forced"]:
            chosen = ["BTECH-CSE", "BTECH-ECE", "BTECH-MECH", "BTECH-CIVIL"]
        else:
            chosen = R.sample(codes, k=min(len(codes), R.randint(2, 5) if meta["profile"] == "ENGG" else R.randint(1, len(codes))))
            if meta["profile"] == "ENGG" and R.random() < 0.3:
                chosen.append(R.choice(["MBA", "MCA"]))
        for code in chosen:
            name, disc, level, dur, intakes = CATALOG[code]
            p = Program(institution_id=inst.id, code=code, name=name, discipline=disc, level=level, duration_years=dur)
            db.add(p)
            progs_by_inst[inst.id].append(p)
    db.flush()

    # ------------------------------------------------------------------ approved intake + 5-year aggregate history
    base_fill, cat_mix = {}, {}
    for inst in insts:
        f0 = R.uniform(0.62, 0.97) if inst.inst_type != "GOVT" else R.uniform(0.85, 1.0)
        base_fill[inst.id] = f0
        cat_mix[inst.id] = dirichlet(CAT_BASE.get(inst.state, CAT_BASE["default"]))
        for p in progs_by_inst[inst.id]:
            a0 = R.choice(CATALOG[p.code][4])
            if inst_meta[inst.aicte_code]["forced"]:
                a0 = 60
            grow_year = R.choice(PAST[1:]) if R.random() < 0.15 and not inst_meta[inst.aicte_code]["forced"] else None
            for y in PAST + [Y]:
                ap = a0 * (2 if grow_year and y >= grow_year else 1)
                approved[p.id][y] = ap
                appr_rows.append({"program_id": p.id, "year": y, "approved": ap})
            adj = {"BTECH-CSE": .08, "BTECH-AIDS": .06, "BTECH-CIVIL": -.12, "BTECH-MECH": -.08}.get(p.code, 0)
            for y in PAST:
                fill = min(1.0, max(0.15, f0 + adj + R.gauss(0, 0.035)))
                adm = round(approved[p.id][y] * fill)
                mix = dirichlet(cat_mix[inst.id], conc=200)
                cats = {c: 0 for c in CATS}
                for _ in range(adm):
                    cats[choose(mix)] += 1
                hist_rows.append({"program_id": p.id, "year": y, "admitted": adm, "categories": cats})

    # ------------------------------------------------------------------ scenario shaping (history + current)
    by_key = {inst_meta[i.aicte_code]["key"]: i for i in insts if inst_meta[i.aicte_code]["forced"]}
    ghost, twins_a, twins_b = by_key["Gyanodaya"], by_key["Kaveri"], by_key["Tamraparni"]
    tfw_abuse, control, overflow = by_key["Sahyadri"], by_key["Hampi"], by_key["Narmada"]
    jump, ews = by_key["Aravalli"], by_key["Vindhya"]
    demo_a, demo_b = by_key["Aarohan"], by_key["Dakshin"]

    def set_history_fill(inst, fill):
        ids = {p.id for p in progs_by_inst[inst.id]}
        for h in hist_rows:
            if h["program_id"] in ids:
                f = min(1.0, max(0.1, fill + R.gauss(0, 0.02)))
                h["admitted"] = round(approved[h["program_id"]][h["year"]] * f)
                mix = cat_mix[inst.id]
                h["categories"] = {c: 0 for c in CATS}
                for _ in range(h["admitted"]):
                    h["categories"][choose(mix)] += 1

    set_history_fill(ghost, 0.30)
    set_history_fill(jump, 0.28)
    base_fill[ghost.id] = 0.30
    base_fill[jump.id] = 0.93           # current year only (history says ~28%)
    cat_mix[ews.id] = [.62, .06, .20, .09, .03]
    set_history_fill(ews, 0.80)
    # non-scenario forced colleges: history consistent with this year (no false fill-rate jumps);
    # demo colleges keep headroom so the live demo uploads do not start over intake
    for inst, f in ((demo_a, .72), (demo_b, .72), (twins_a, .82), (twins_b, .70), (tfw_abuse, .85), (control, .85),
                    (overflow, .85)):
        base_fill[inst.id] = f
        set_history_fill(inst, f)

    db.execute(insert(ApprovedIntake), appr_rows)
    db.execute(insert(IntakeHistory), hist_rows)

    # ------------------------------------------------------------------ current cohort (student level), bulk
    roll_seq = defaultdict(int)

    def roll(inst, prog, year=Y):
        roll_seq[(inst.id, prog.code, year)] += 1
        short = prog.code.split("-")[-1][:4]
        return f"{year % 100}{short}{roll_seq[(inst.id, prog.code, year)]:03d}"

    prov_rate = {i.id: R.choice([0, 0, 0.01, 0.02, 0.03, 0.04, 0.06]) for i in insts}
    for inst in insts:
        f0 = base_fill[inst.id]
        mix = cat_mix[inst.id]
        if inst.id == ews.id:
            mix = [.30, .45, .15, .07, .03]
        for p in progs_by_inst[inst.id]:
            ap = approved[p.id][Y]
            if inst.id in (tfw_abuse.id, control.id, overflow.id) and p.code in ("BTECH-MECH", "BTECH-CIVIL"):
                n_reg = 60
            else:
                adj = {"BTECH-CSE": .08, "BTECH-AIDS": .06, "BTECH-CIVIL": -.12, "BTECH-MECH": -.08}.get(p.code, 0)
                n_reg = min(ap, round(ap * min(1.0, max(0.12, f0 + adj + R.gauss(0, 0.03)))))
            private = inst.inst_type == "PRIVATE"
            for _ in range(n_reg):
                seat = "MANAGEMENT" if private and R.random() < 0.22 else "MERIT"
                if private and R.random() < 0.02:
                    seat = "NRI"
                nat = "NRI" if seat == "NRI" and R.random() < 0.8 else "INDIAN"
                pr = S.person(inst.state, p.level, apaar=R.random() >= prov_rate[inst.id])
                cat = "GEN" if nat == "NRI" else choose(mix)
                S.enroll(pr, inst.id, p, roll(inst, p), seat=seat, cat=cat, nat=nat)
            special = inst.id in (tfw_abuse.id, control.id, overflow.id, jump.id, ghost.id)
            if not special and p.level in ("UG", "DIPLOMA") and R.random() < 0.4:
                for _ in range(R.randint(0, max(0, int(ap * 0.05)))):
                    pr = S.person(inst.state, p.level)
                    S.enroll(pr, inst.id, p, roll(inst, p), seat="TFW", cat=choose(mix))
            if not special and p.level == "UG" and p.code.startswith("BTECH") and R.random() < 0.5:
                for _ in range(R.randint(0, int(ap * 0.10))):
                    pr = S.person(inst.state, "UG", dob=rand_date(date(Y - 21, 1, 1), date(Y - 19, 12, 31)))
                    S.enroll(pr, inst.id, p, roll(inst, p), seat="LATERAL", cat=choose(mix), yos=2)
            if not special and R.random() < 0.05:
                for _ in range(R.randint(1, 3)):
                    pr = S.person(inst.state, p.level, apaar=False, registry=False, exempt=True)
                    S.enroll(pr, inst.id, p, roll(inst, p), seat="FOREIGN", cat="GEN", nat=R.choice(["OCI", "PIO", "FOREIGN_NATIONAL"]))

    # control college: 60 regular + 3 TFW + 8 FN + 5 LE on MECH = 76 against 60 approved, all legal
    cmech = next(p for p in progs_by_inst[control.id] if p.code == "BTECH-MECH")
    for _ in range(3):
        S.enroll(S.person("KA", "UG"), control.id, cmech, roll(control, cmech), seat="TFW", cat=choose(cat_mix[control.id]))
    for _ in range(8):
        S.enroll(S.person("KA", "UG", apaar=False, registry=False, exempt=True), control.id, cmech, roll(control, cmech), seat="FOREIGN",
                 cat="GEN", nat=R.choice(["OCI", "PIO", "FOREIGN_NATIONAL"]))
    for _ in range(5):
        S.enroll(S.person("KA", "UG", dob=rand_date(date(Y - 21, 1, 1), date(Y - 19, 12, 31))), control.id, cmech,
                 roll(control, cmech), seat="LATERAL", cat=choose(cat_mix[control.id]), yos=2)

    # demo actors (fixed people)
    a_cse = next(p for p in progs_by_inst[demo_a.id] if p.code == "BTECH-CSE")
    kavya = S.person("TN", "UG", gender="F", name="Kavya Senthil", parent="Senthil Kumar R", dob=date(2008, 3, 14))
    S.enroll(kavya, demo_a.id, a_cse, roll(demo_a, a_cse), seat="MERIT", cat="OBC-NCL", adm=date(Y, 7, 28), lag=3)
    vignesh = S.person("TN", "UG", gender="M", name="Vignesh Murugan", parent="Murugan Palanisamy", dob=date(2008, 1, 9))
    S.enroll(vignesh, demo_a.id, a_cse, roll(demo_a, a_cse), seat="MERIT", cat="OBC-NCL", adm=date(Y, 8, 4), lag=2)
    karthik = S.person("TN", "UG", gender="M", name="Karthik Ramasamy", parent="Ramasamy Velu", dob=date(2008, 6, 21))
    S.enroll(karthik, demo_a.id, a_cse, roll(demo_a, a_cse), seat="MERIT", cat="SC", adm=date(Y, 8, 2), lag=4)

    # graduated 2022 cohort (degree demo) at the demo college and two TN peers
    grads = []
    for inst in (demo_a, twins_a, twins_b):
        cse = next(p for p in progs_by_inst[inst.id] if p.code == "BTECH-CSE")
        for k in range(18 if inst is demo_a else 8):
            pr = S.person("TN", "UG", dob=rand_date(date(2003, 6, 1), date(2004, 5, 31)))
            S.enroll(pr, inst.id, cse, roll(inst, cse, 2022), year=2022, status="GRADUATED", adm=date(2022, 8, 10), lag=5)
            grads.append(pr)
    divya = S.person("TN", "UG", gender="F", name="Divya Krishnan", parent="Krishnan Selvam", dob=date(2004, 2, 2))
    S.enroll(divya, demo_a.id, a_cse, roll(demo_a, a_cse, 2022), year=2022, status="GRADUATED", adm=date(2022, 8, 10), lag=5)

    # churn
    scenario_ids = {i.id for i in (ghost, twins_a, twins_b, tfw_abuse, control, overflow, jump, ews, demo_a, demo_b)}
    for e in R.sample(S.enrollments, k=len(S.enrollments) // 60):
        if e["status"] == "ACTIVE" and e["institution_id"] not in scenario_ids:
            e["status"] = R.choice(["DROPPED", "DROPPED", "DROPPED", "TRANSFERRED_OUT"])

    # spare registry identities for demo uploads (not enrolled anywhere yet)
    spare = []
    for _ in range(400):
        g = "F" if R.random() < 0.45 else "M"
        name, parent = pick_name("TN", g)
        a = S.apaar()
        d = rand_date(date(2007, 6, 1), date(2008, 12, 31))
        S.registry.append({"apaar_id": a, "name": name, "dob": d, "gender": g, "status": "ACTIVE"})
        spare.append({"apaar_id": a, "name": name, "parent": parent, "dob": d, "gender": g})

    for chunk in range(0, len(S.persons), 5000):
        db.execute(insert(Person), S.persons[chunk:chunk + 5000])
    for chunk in range(0, len(S.enrollments), 5000):
        db.execute(insert(Enrollment), S.enrollments[chunk:chunk + 5000])
    for chunk in range(0, len(S.registry), 5000):
        db.execute(insert(MockRegistryRecord), S.registry[chunk:chunk + 5000])
    if engine.dialect.name == "postgresql":
        for t in ("persons", "enrollments"):
            db.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT MAX(id) FROM {t}))"))
    counts.recompute(db, Y)
    db.commit()
    print(f"baseline: {len(insts)} institutions, {len(S.persons)} persons, {len(S.enrollments)} enrolments "
          f"({time.time() - t0:.1f}s)")

    # ------------------------------------------------------------------ keys, users, integration
    keys.root_key(db)
    for inst in insts:
        keys.institution_key(db, inst)
    for u in unis.values():
        keys.university_key(db, u)
    totp_secret = "JBSWY3DPEHPK3PXPAPAARSPINEDEMO22"
    users = [
        ("aicte.admin", "Aicte@2026", "AICTE_ADMIN", "AICTE Data Cell", {}),
        ("admin.aarohan", "Inst@2026", "INSTITUTION_ADMIN", "Admissions Office", {"institution_id": demo_a.id}),
        ("operator.aarohan", "Oper@2026", "DATA_OPERATOR", "Data Entry Desk", {"institution_id": demo_a.id}),
        ("admin.dakshin", "Inst@2026", "INSTITUTION_ADMIN", "Admissions Office", {"institution_id": demo_b.id}),
        ("operator.dakshin", "Oper@2026", "DATA_OPERATOR", "Data Entry Desk", {"institution_id": demo_b.id}),
        ("registrar.tnstu", "Univ@2026", "UNIVERSITY_REGISTRAR", "Office of the Registrar", {"university_id": unis["TN"].id}),
        ("naac.auditor", "Naac@2026", "REGULATOR", "NAAC Audit Officer", {"regulator_body": "NAAC"}),
    ]
    for un, pw, role, disp, extra in users:
        u = User(username=un, display_name=disp, password_hash=hash_password(pw), role=role, **extra)
        if un == "aicte.admin":
            u.totp_secret, u.mfa_enabled = totp_secret, True
        db.add(u)
    raw_key, prefix, h = new_api_key()
    db.add(ApiKey(institution_id=demo_a.id, label="Aarohan ERP (demo)", prefix=prefix, key_hash=h))
    db.add(Webhook(institution_id=demo_a.id, url=f"{settings.public_base_url}/mock/erp/{demo_a.id}/webhook",
                   secret="whsec_demo_" + prefix, event_types=WEBHOOK_EVENT_TYPES))
    db.add(Webhook(institution_id=demo_b.id, url=f"{settings.public_base_url}/mock/erp/{demo_b.id}/webhook",
                   secret="whsec_demo_b_" + prefix, event_types=WEBHOOK_EVENT_TYPES))
    db.commit()

    # ------------------------------------------------------------------ fraud scenarios through the REAL pipeline
    def row(pr: dict, prog, rno, *, name=None, apaar=True, seat="MERIT", cat="GEN", nat="INDIAN", yos=1, adm=None):
        return {"roll_no": rno, "apaar_id": pr.get("apaar_id") if apaar else "", "name": name or pr["name"],
                "dob": pr["dob"].isoformat(), "gender": pr["gender"], "parent_name": pr.get("parent_name") or pr.get("parent"),
                "qualifying_exam_roll": pr.get("exam_roll") or "", "program_code": prog.code,
                "admission_date": (adm or rand_date(date(Y, 7, 20), date(Y, 9, 15))).isoformat(), "year_of_study": yos,
                "mode": "REGULAR", "seat_type": seat, "social_category": cat, "nationality": nat}

    def fresh(state, level, gender=None, apaar=True, dob=None):
        g = gender or ("F" if R.random() < 0.44 else "M")
        name, parent = pick_name(state, g)
        d = dob or rand_date(date(Y - 19, 6, 1), date(Y - 18, 5, 31))
        rec = {"name": name, "parent_name": parent, "dob": d, "gender": g, "exam_roll": S.exam_roll(state)}
        if apaar:
            a = S.apaar()
            rec["apaar_id"] = a
            db.add(MockRegistryRecord(apaar_id=a, name=name, dob=d, gender=g, status="ACTIVE"))
        return rec

    # S1 ghost college: pads to ~95% fill, 45% of the padding without APAAR, reported late
    rows = []
    for p in progs_by_inst[ghost.id]:
        have = sum(1 for e in S.enrollments if e["program_id"] == p.id and e["status"] == "ACTIVE")
        for _ in range(int(approved[p.id][Y] * 0.95) - have):
            prov = R.random() < 0.62
            rows.append(row(fresh("UP", "UG", apaar=not prov), p, roll(ghost, p), apaar=not prov,
                            cat=choose(cat_mix[ghost.id]), adm=rand_date(date(Y, 7, 15), date(Y, 8, 20))))
    db.commit()
    r1 = ingest(db, ghost, rows, source="API", actor=SYSTEM)

    # S2 same students at two colleges: 25 exact (same APAAR) + 8 provisional fuzzy variants
    a_active = [e for e in S.enrollments if e["institution_id"] == twins_a.id and e["status"] == "ACTIVE"
                and e["academic_year"] == Y and e["seat_type"] == "MERIT"]
    pmap = {p["id"]: p for p in S.persons}
    victims = [pmap[e["person_id"]] for e in R.sample(a_active, 33) if pmap[e["person_id"]]["apaar_id"]]
    b_cse = next(p for p in progs_by_inst[twins_b.id] if p.code == "BTECH-CSE")
    rows = [row(v, b_cse, roll(twins_b, b_cse), cat=choose(cat_mix[twins_b.id])) for v in victims[:25]]
    rows += [row(v, b_cse, roll(twins_b, b_cse), name=initial_variant(v["name"]), apaar=False,
                 cat=choose(cat_mix[twins_b.id])) for v in victims[25:33]]
    db.commit()
    r2 = ingest(db, twins_b, rows, source="CSV", actor=SYSTEM, filename="tamraparni_admissions_batch2.csv")

    # S3 supernumerary abuse: 13 TFW on a 60-seat programme (cap 3); plus regular overflow at another college
    smech = next(p for p in progs_by_inst[tfw_abuse.id] if p.code == "BTECH-MECH")
    rows = [row(fresh("MH", "UG"), smech, roll(tfw_abuse, smech), seat="TFW", cat=choose(cat_mix[tfw_abuse.id]))
            for _ in range(13)]
    db.commit()
    r3 = ingest(db, tfw_abuse, rows, source="API", actor=SYSTEM)
    ociv = next(p for p in progs_by_inst[overflow.id] if p.code == "BTECH-CIVIL")
    rows = [row(fresh("GJ", "UG"), ociv, roll(overflow, ociv), cat=choose(cat_mix[overflow.id])) for _ in range(8)]
    db.commit()
    r4 = ingest(db, overflow, rows, source="API", actor=SYSTEM)

    # a few category changes after admission (R35) and dropouts, for texture
    db.commit()
    print(f"scenarios: ghost {r1['created']} rows, twins conflicts {r2['conflict']} + fuzzy, "
          f"tfw {r3['created']}, overflow {r4['created']}")

    # ------------------------------------------------------------------ anomaly run + cursors
    res = anomaly_engine.run(db)
    last_ev = db.execute(select(Event.id).order_by(Event.id.desc())).scalars().first() or 0
    db.merge(JobState(name="anomaly_cursor", value=str(last_ev)))
    db.merge(JobState(name="webhook_cursor", value=str(last_ev)))
    audit.record(db, actor="seed", role="SYSTEM", action="SEED", resource="database",
                 details={"institutions": len(insts), "persons": len(S.persons), "enrollments": len(S.enrollments)})
    db.commit()
    print(f"anomalies: {res}")

    # ------------------------------------------------------------------ demo files
    demo_dir = DATA_DIR / "demo"
    demo_dir.mkdir(exist_ok=True)
    fields = ["roll_no", "apaar_id", "name", "dob", "gender", "parent_name", "qualifying_exam_roll", "program_code",
              "admission_date", "year_of_study", "mode", "seat_type", "social_category", "nationality"]
    sp = iter(spare)

    def srow(rno, prog_code, *, adm_day, **over):
        s = next(sp)
        base = {"roll_no": rno, "apaar_id": pretty(s["apaar_id"]), "name": s["name"], "dob": s["dob"].isoformat(),
                "gender": s["gender"], "parent_name": s["parent"], "qualifying_exam_roll": S.exam_roll("TN"),
                "program_code": prog_code, "admission_date": date(Y, 11, adm_day).isoformat(), "year_of_study": 1,
                "mode": "REGULAR", "seat_type": "MERIT", "social_category": R.choice(["OBC-NCL", "OBC-NCL", "SC", "GEN"]),
                "nationality": "INDIAN"}
        base.update(over)
        return base

    other = next(sp)
    a_rows = [srow(f"26CSE9{k:02d}", "BTECH-CSE", adm_day=10 + k % 8) for k in range(6)]
    bad = srow("26ECE901", "BTECH-ECE", adm_day=12)
    bad["apaar_id"] = bad["apaar_id"][:-1] + str((int(bad["apaar_id"][-1]) + 3) % 10)      # typo -> R40
    a_rows.append(bad)
    a_rows.append(srow("26ECE902", "BTECH-ECE", adm_day=12, apaar_id=pretty(other["apaar_id"])))  # someone else's -> R42
    a_rows.append(srow("26ECE903", "BTECH-ECE", adm_day=13, apaar_id=""))                         # provisional -> R44
    a_rows.append(srow("26MEC901", "BTECH-MECH", adm_day=13, nationality="OCI", social_category="SC"))  # R31
    a_rows.append(srow("26MEC902", "BTECH-MECH", adm_day=14, social_category="EWS/OBC-NCL"))         # R30
    a_rows.append(srow("26CSE901", "BTECH-CSE", adm_day=14))                                          # dup roll -> R02
    a_rows.append(srow("26CIV901", "BTECH-CIVIL", adm_day=15, seat_type="LATERAL", year_of_study=1))  # R23
    a_rows.append(srow("26CIV902", "BTECH-CIVIL", adm_day=15, seat_type="FOREIGN"))                   # R32
    with open(demo_dir / "1_aarohan_new_admissions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(a_rows)

    b_rows = [srow(f"26CSE7{k:02d}", "BTECH-CSE", adm_day=16 + k) for k in range(3)]
    b_rows.append({"roll_no": "26CSE777", "apaar_id": pretty(vignesh["apaar_id"]), "name": "Vignesh M",
                   "dob": vignesh["dob"].isoformat(), "gender": "M", "parent_name": "Murugan P",
                   "qualifying_exam_roll": vignesh["exam_roll"], "program_code": "BTECH-CSE",
                   "admission_date": date(Y, 11, 18).isoformat(), "year_of_study": 1, "mode": "REGULAR",
                   "seat_type": "MANAGEMENT", "social_category": "OBC-NCL", "nationality": "INDIAN"})
    b_rows.append({"roll_no": "26CSE778", "apaar_id": "", "name": "R. Karthik", "dob": karthik["dob"].isoformat(),
                   "gender": "M", "parent_name": "Ramasamy V", "qualifying_exam_roll": "", "program_code": "BTECH-CSE",
                   "admission_date": date(Y, 11, 18).isoformat(), "year_of_study": 1, "mode": "REGULAR",
                   "seat_type": "MANAGEMENT", "social_category": "GEN", "nationality": "INDIAN"})
    with open(demo_dir / "2_dakshin_upload_with_duplicates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(b_rows)

    accounts = {
        "accounts": [{"username": un, "password": pw, "role": role, "display_name": disp} for un, pw, role, disp, _ in users],
        "students": [
            {"name": kavya["name"], "apaar_id": pretty(kavya["apaar_id"]), "note": f"Active, B.Tech CSE at {demo_a.name}"},
            {"name": vignesh["name"], "apaar_id": pretty(vignesh["apaar_id"]),
             "note": "Active at Aarohan; the Dakshin demo CSV re-submits him (live conflict)"},
            {"name": divya["name"], "apaar_id": pretty(divya["apaar_id"]), "note": "Graduated 2022 cohort (degree demo)"},
        ],
        "digilocker_otp": "123456",
        "erp_api_key": {"institution": demo_a.name, "key": raw_key},
        "demo_files": ["1_aarohan_new_admissions.csv", "2_dakshin_upload_with_duplicates.csv"],
        "scenarios": {"ghost_college": ghost.name, "twin_enrolment": [twins_a.name, twins_b.name],
                      "tfw_abuse": tfw_abuse.name, "legal_76_on_60": control.name, "regular_overflow": overflow.name,
                      "fill_jump": jump.name, "ews_spike": ews.name},
        "scenario_ids": {"ghost": ghost.id, "twins_a": twins_a.id, "twins_b": twins_b.id, "tfw_abuse": tfw_abuse.id,
                         "control": control.id, "overflow": overflow.id, "jump": jump.id, "ews": ews.id,
                         "demo_a": demo_a.id, "demo_b": demo_b.id},
    }
    (DATA_DIR / "demo_accounts.json").write_text(json.dumps(accounts, indent=2))
    db.close()
    print(f"done in {time.time() - t0:.1f}s -> {DATA_DIR}")


if __name__ == "__main__":
    main(reset="--no-reset" not in sys.argv)
