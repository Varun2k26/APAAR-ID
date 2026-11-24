"""The single ingestion pipeline. API, CSV upload and the web form all call `ingest()`.

    parse/normalise -> row rules -> identity resolution -> duplicate checks -> persist
    -> counters + outbox event + audit entry -> program-level intake rules

Each row runs in its own SAVEPOINT: a bad row is quarantined (with its raw data, so it can
be fixed in place) and never sinks the rest of the file.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..analytics import counts
from ..auth.deps import Principal
from ..config import settings
from ..identity import apaar_format, resolver
from ..identity.names import name_similarity, normalize, phonetic_key
from ..models import (Conflict, Enrollment, Institution, Person, Program, Submission, ValidationIssue, utcnow)
from ..services import audit, events
from ..validation import duplicates, intake
from ..validation.catalog import Finding
from ..validation.rows import FIELDS, REGULAR_SEATS, parse_row

log = logging.getLogger("pipeline")


@dataclass
class RowResult:
    row_number: int
    roll_no: str | None
    outcome: str                      # CREATED UPDATED UNCHANGED CONFLICT REJECTED
    enrollment_id: int | None = None
    person_ref: str | None = None
    findings: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"row": self.row_number, "roll_no": self.roll_no, "outcome": self.outcome,
                "enrollment_id": self.enrollment_id, "person_ref": self.person_ref,
                "findings": [f.as_dict() for f in self.findings]}


def _raw(raw: dict) -> dict:
    return {k: ("" if raw.get(k) is None else str(raw.get(k))) for k in FIELDS}


def _person_ref(p: Person) -> str:
    return apaar_format.mask(p.apaar_id) if p.apaar_id else (p.provisional_id or "")


def _policy(existing_mode: str, new_mode: str) -> str:
    return settings.dual_policy.get((existing_mode, new_mode), "CONFLICT")


def ingest(db: Session, inst: Institution, records: list[dict], *, source: str, actor: Principal,
           filename: str | None = None, idempotency_key: str | None = None, commit: bool = True) -> dict:
    if idempotency_key:
        prev = db.execute(select(Submission).where(Submission.institution_id == inst.id,
                                                   Submission.idempotency_key == idempotency_key)).scalar_one_or_none()
        if prev:
            return {**(prev.report or {}), "replayed": True}
    sub = Submission(institution_id=inst.id, source=source, filename=filename, actor=actor.label,
                     idempotency_key=idempotency_key, total=len(records))
    db.add(sub)
    db.flush()
    programs = {p.code.upper(): p for p in db.execute(select(Program).where(Program.institution_id == inst.id)).scalars()}
    seen_roll: dict[str, int] = {}
    seen_apaar: dict[str, int] = {}
    touched: set[int] = set()
    results = [_process(db, sub, inst, programs, raw, i, actor, seen_roll, seen_apaar, touched)
               for i, raw in enumerate(records, start=1)]

    from ..anomaly.rules import refresh_programs     # local import: anomaly imports pipeline helpers
    alerts = refresh_programs(db, touched)

    tally = {k: sum(1 for r in results if r.outcome == k) for k in
             ("CREATED", "UPDATED", "UNCHANGED", "CONFLICT", "REJECTED")}
    sub.accepted, sub.updated = tally["CREATED"], tally["UPDATED"]
    sub.rejected, sub.conflicts = tally["REJECTED"], tally["CONFLICT"]
    sub.warnings = sum(1 for r in results if r.outcome != "REJECTED" for f in r.findings if f.severity == "WARN")
    report = {
        "submission_id": sub.id, "institution_id": inst.id, "source": source, "filename": filename,
        "total": len(records), **{k.lower(): v for k, v in tally.items()}, "warnings": sub.warnings,
        "intake_alerts": alerts,
        "rows": [r.as_dict() for r in results if r.findings or r.outcome in ("REJECTED", "CONFLICT")][:2000],
        "replayed": False,
    }
    sub.report = report
    events.emit(db, "SUBMISSION_PROCESSED", institution_id=inst.id, actor=actor.label,
                payload={"submission_id": sub.id, "source": source, "total": len(records),
                         **{k.lower(): v for k, v in tally.items()}})
    audit.record(db, actor=actor.label, role=actor.role, action="SUBMISSION", resource=f"submission:{sub.id}",
                 details={"source": source, "filename": filename, "total": len(records), **tally})
    if commit:
        db.commit()
    return report


def _process(db, sub, inst, programs, raw, i, actor, seen_roll, seen_apaar, touched) -> RowResult:
    clean, findings = parse_row(raw, programs)
    roll = (str(raw.get("roll_no") or "")).strip() or None
    if clean is None:
        return _quarantine(db, sub, inst, raw, i, roll, findings)
    if roll in seen_roll:
        findings.append(Finding("R02", "ERROR", f"Roll number {roll} also appears in row {seen_roll[roll]} of this file",
                                "roll_no", "Each student should appear only once in a file."))
        return _quarantine(db, sub, inst, raw, i, roll, findings)
    seen_roll[roll] = i
    if clean["apaar_id"]:
        if clean["apaar_id"] in seen_apaar:
            findings.append(Finding("R01", "ERROR", f"The same APAAR ID appears in row {seen_apaar[clean['apaar_id']]} "
                                    "of this file", "apaar_id", "Each student should appear only once in a file."))
            return _quarantine(db, sub, inst, raw, i, roll, findings)
        seen_apaar[clean["apaar_id"]] = i

    existing = db.execute(select(Enrollment).where(Enrollment.institution_id == inst.id,
                                                   Enrollment.roll_no == roll)).scalar_one_or_none()
    sp = db.begin_nested()
    try:
        if existing:
            res = _update(db, sub, inst, existing, clean, findings, actor, i, touched)
        else:
            res = _create(db, sub, inst, clean, findings, actor, i, touched)
        if res.outcome == "REJECTED":
            sp.rollback()
            return _quarantine(db, sub, inst, raw, i, roll, res.findings)
        sp.commit()
        _store_findings(db, sub, inst, res, i)
        return res
    except Exception as ex:  # noqa: BLE001 - quarantine instead of failing the whole file
        log.exception("row %s failed", i)
        if sp.is_active:
            sp.rollback()
        findings.append(Finding("R50", "ERROR", f"This row could not be processed ({type(ex).__name__}: {ex})"[:300]))
        return _quarantine(db, sub, inst, raw, i, roll, findings)


def _new_enrollment(person: Person, inst: Institution, clean: dict, status: str, source: str) -> Enrollment:
    return Enrollment(person_id=person.id, institution_id=inst.id, program_id=clean["program"].id,
                      roll_no=clean["roll_no"], academic_year=settings.current_year,
                      admission_date=clean["admission_date"], year_of_study=clean["year_of_study"],
                      mode=clean["mode"], seat_type=clean["seat_type"], social_category=clean["social_category"],
                      nationality=clean["nationality"], status=status, reported_at=utcnow(), source=source)


def _open_exact_conflict(db, inst, existing_active: Enrollment, new: Enrollment, person: Person, actor,
                         findings: list[Finding], why: str) -> Conflict:
    c = Conflict(kind="EXACT", score=1.0, enrollment_a_id=existing_active.id, enrollment_b_id=new.id,
                 person_a_id=person.id, person_b_id=person.id,
                 reasons=[why, f"both enrolments are in {new.mode.lower()} mode, where concurrent enrolment is not permitted"])
    db.add(c)
    db.flush()
    findings.append(Finding(
        "R10", "WARN", f"This student is already enrolled at another institution. Recorded as duplicate "
        f"enrolment case #{c.id}", "apaar_id",
        "Cases are decided on the student's confirmation and supporting evidence, not on which report arrived "
        "first. For a transfer, use a transfer request instead."))
    events.emit(db, "CONFLICT_OPENED", institution_id=inst.id, other_institution_id=existing_active.institution_id,
                person_id=person.id, enrollment_id=new.id, actor=actor.label,
                payload={"conflict_id": c.id, "kind": "EXACT", "score": 1.0})
    return c


def _create(db, sub, inst, clean, findings, actor, i, touched) -> RowResult:
    person, f, created = resolver.resolve(db, clean)
    findings.extend(f)
    roll = clean["roll_no"]
    if person is None:
        return RowResult(i, roll, "REJECTED", findings=findings)

    dup_here = db.execute(select(Enrollment).where(Enrollment.person_id == person.id,
                                                   Enrollment.institution_id == inst.id,
                                                   Enrollment.status.in_(("ACTIVE", "CONFLICT", "SUSPENDED")))).scalars().first()
    if dup_here:
        findings.append(Finding("R01", "ERROR", f"This APAAR ID is already enrolled here under roll number {dup_here.roll_no}",
                                "apaar_id", "Update that record instead of adding a new one."))
        return RowResult(i, roll, "REJECTED", findings=findings)

    if created:
        for oe, score, reasons in duplicates.find_matches(db, person, same_institution_id=inst.id):
            findings.append(Finding("R03", "WARN", f"May be the same student as roll number {oe.roll_no} "
                                    f"({score:.0%} similarity: {', '.join(reasons)})", "name",
                                    "If so, remove one of the records. Twins can share a date of birth and parent's name."))

    status, conflict_with = "ACTIVE", None
    others = db.execute(select(Enrollment).where(Enrollment.person_id == person.id, Enrollment.status == "ACTIVE",
                                                 Enrollment.institution_id != inst.id)).scalars().all()
    for o in others:
        if _policy(o.mode, clean["mode"]) == "CONFLICT":
            status, conflict_with = "CONFLICT", o
            break
        findings.append(Finding("R12", "INFO", f"Also enrolled at another institution in {o.mode.lower()} mode, which is "
                                "permitted for concurrent programmes", "mode"))

    e = _new_enrollment(person, inst, clean, status, sub.source)
    try:
        with db.begin_nested():
            db.add(e)            # added *inside* the savepoint so a rollback expunges it
            db.flush()
    except IntegrityError:
        # Lost a race: another institution's ACTIVE regular row for this person committed
        # between our check and our insert. The unique index caught it; record a conflict.
        e = _new_enrollment(person, inst, clean, "CONFLICT", sub.source)
        db.add(e)
        db.flush()
        status = "CONFLICT"
        conflict_with = db.execute(select(Enrollment).where(Enrollment.person_id == person.id,
                                                            Enrollment.status == "ACTIVE",
                                                            Enrollment.mode == "REGULAR")).scalars().first()
    if status == "CONFLICT":
        _open_exact_conflict(db, inst, conflict_with, e, person, actor, findings, "same APAAR ID")
    else:
        counts.apply(db, e, person, +1)

    for oe, score, reasons in duplicates.find_matches(db, person, exclude_institution_id=inst.id):
        if _policy(oe.mode, e.mode) != "CONFLICT":
            continue
        dup = db.execute(select(Conflict).where(Conflict.enrollment_a_id == oe.id,
                                                Conflict.enrollment_b_id == e.id)).scalar_one_or_none()
        if dup:
            continue
        c = Conflict(kind="FUZZY", score=score, enrollment_a_id=oe.id, enrollment_b_id=e.id,
                     person_a_id=oe.person_id, person_b_id=person.id, reasons=reasons)
        db.add(c)
        db.flush()
        findings.append(Finding("R11", "WARN", f"May be the same student as one enrolled at another institution "
                                f"({score:.0%} similarity). Referred for review as case #{c.id}", "name",
                                "No action is needed unless you are contacted."))
        events.emit(db, "CONFLICT_OPENED", institution_id=inst.id, other_institution_id=oe.institution_id,
                    person_id=person.id, enrollment_id=e.id, actor=actor.label,
                    payload={"conflict_id": c.id, "kind": "FUZZY", "score": score})

    if status == "ACTIVE":
        _intake_findings(db, e, findings)
    if counts.is_late(e):
        findings.append(Finding("R54", "WARN", f"Reported {(e.reported_at.date() - e.admission_date).days} days after "
                                "admission", "admission_date", f"Admissions should be reported within {settings.late_report_days} days."))
    touched.add(e.program_id)
    events.emit(db, "ENROLLMENT_CREATED", institution_id=inst.id, person_id=person.id, enrollment_id=e.id,
                actor=actor.label, payload={"roll_no": roll, "status": status, "program_id": e.program_id,
                                            "provisional": not person.apaar_id})
    audit.record(db, actor=actor.label, role=actor.role, action="ENROLLMENT_CREATE", resource=f"enrollment:{e.id}",
                 subject_person_id=person.id, details={"institution_id": inst.id, "roll_no": roll, "status": status,
                                                       "source": sub.source})
    return RowResult(i, roll, "CONFLICT" if status == "CONFLICT" else "CREATED", e.id, _person_ref(person), findings)


def _intake_findings(db, e: Enrollment, findings: list[Finding]) -> None:
    st = intake.program_status(db, e.program_id)
    bucket = "REGULAR" if e.seat_type in REGULAR_SEATS else e.seat_type
    for v in st["violations"]:
        if v["bucket"] == bucket or (v["bucket"] == "NRI" and e.seat_type == "NRI"):
            label = {"REGULAR": "Regular admissions", "TFW": "Tuition fee waiver seats", "FOREIGN": "FN/OCI/PIO seats",
                     "LATERAL": "Lateral entry seats", "NRI": "NRI seats"}[v["bucket"]]
            findings.append(Finding(v["code"], "WARN", f"{label} now {v['count']} against a limit of {v['limit']} "
                                    f"(approved intake {st['approved']})", "seat_type",
                                    "Supernumerary seats are counted separately. Check the seat type; otherwise "
                                    "admissions exceed the sanctioned intake."))


def _update(db, sub, inst, e: Enrollment, clean, findings, actor, i, touched) -> RowResult:
    p = db.get(Person, e.person_id)
    roll = clean["roll_no"]
    changed: list[str] = []
    if clean["apaar_id"] and p.apaar_id and p.apaar_id != clean["apaar_id"]:
        findings.append(Finding("R45", "ERROR", f"Roll number {roll} is already linked to APAAR ID {apaar_format.mask(p.apaar_id)}",
                                "apaar_id", "A roll number cannot be reassigned to another student. Contact AICTE to correct it."))
        return RowResult(i, roll, "REJECTED", findings=findings)

    if clean["apaar_id"] and not p.apaar_id:                      # linking an APAAR to a provisional record
        status, rec, f = resolver.registry_check(db, clean["apaar_id"], clean)
        if status in ("NOT_FOUND", "MISMATCH"):
            findings.extend(f)
            return RowResult(i, roll, "REJECTED", findings=findings)
        findings.extend(f)
        counts.apply(db, e, p, -1)
        db.flush()
        target = db.execute(select(Person).where(Person.apaar_id == clean["apaar_id"])).scalar_one_or_none()
        if target and target.id != p.id:
            p.merged_into_id = target.id
            e.person_id = target.id
            old_p, p = p, target
            other = db.execute(select(Enrollment).where(Enrollment.person_id == target.id, Enrollment.status == "ACTIVE",
                                                        Enrollment.id != e.id)).scalars().first()
            if other and e.status == "ACTIVE" and _policy(other.mode, e.mode) == "CONFLICT":
                e.status = "CONFLICT"
                db.flush()
                _open_exact_conflict(db, inst, other, e, target, actor, findings,
                                     f"APAAR linked to provisional {old_p.provisional_id}, which was already enrolled elsewhere")
        else:
            p.apaar_id, p.registry_status = clean["apaar_id"], status
            p.registry_checked_at = utcnow() if status == "VERIFIED" else None
            if rec:
                p.name, p.name_norm, p.name_key = rec["name"], normalize(rec["name"]), phonetic_key(rec["name"])
        db.flush()
        counts.apply(db, e, p, +1)
        changed.append("apaar_linked")
        events.emit(db, "APAAR_LINKED", institution_id=inst.id, person_id=p.id, enrollment_id=e.id, actor=actor.label,
                    payload={"roll_no": roll})
        for iss in db.execute(select(ValidationIssue).where(ValidationIssue.enrollment_id == e.id,
                                                            ValidationIssue.rule_code == "R44",
                                                            ValidationIssue.status == "OPEN")).scalars():
            iss.status, iss.resolved_at = "RESOLVED", utcnow()

    if p.registry_status == "VERIFIED":
        if clean["dob"] != p.dob or name_similarity(clean["name"], p.name) < settings.registry_name_threshold:
            findings.append(Finding("R46", "WARN", "Name or date of birth differs from the APAAR record; identity "
                                    "details were not changed", "name", "Identity details can only be corrected through APAAR."))
    else:
        for fld, val in (("name", clean["name"]), ("dob", clean["dob"]), ("gender", clean["gender"]),
                         ("parent_name", clean.get("parent_name")), ("exam_roll", clean.get("exam_roll"))):
            if val and getattr(p, fld) != val:
                setattr(p, fld, val)
                changed.append(fld)
        p.name_norm, p.name_key = normalize(p.name), phonetic_key(p.name)
        p.parent_key = phonetic_key(p.parent_name) or None

    new_vals = {"program_id": clean["program"].id, "admission_date": clean["admission_date"],
                "year_of_study": clean["year_of_study"], "mode": clean["mode"], "seat_type": clean["seat_type"],
                "social_category": clean["social_category"], "nationality": clean["nationality"]}
    diffs = {k: (getattr(e, k), v) for k, v in new_vals.items() if getattr(e, k) != v}
    if diffs:
        touched.add(e.program_id)
        counts.apply(db, e, p, -1)
        db.flush()
        for k, (_, v) in diffs.items():
            setattr(e, k, v)
        e.updated_at = utcnow()
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            findings.append(Finding("R10", "ERROR", "This change would enrol the student in two regular programmes "
                                    "at the same time", "mode"))
            return RowResult(i, roll, "REJECTED", findings=findings)
        counts.apply(db, e, p, +1)
        touched.add(e.program_id)
        if "social_category" in diffs:
            old, new = diffs["social_category"]
            findings.append(Finding("R35", "WARN", f"Category changed after admission from {old} to {new}", "social_category",
                                    "Keep the supporting certificate on file. Category changes are reviewed."))
            events.emit(db, "CATEGORY_CHANGED", institution_id=inst.id, person_id=p.id, enrollment_id=e.id,
                        actor=actor.label, payload={"from": old, "to": new, "roll_no": roll})
        printable = {k: [str(a), str(b)] for k, (a, b) in diffs.items()}
        events.emit(db, "ENROLLMENT_UPDATED", institution_id=inst.id, person_id=p.id, enrollment_id=e.id,
                    actor=actor.label, payload={"roll_no": roll, "changes": printable})
        changed.extend(diffs)
        if e.status == "ACTIVE":
            _intake_findings(db, e, findings)
    if changed:
        audit.record(db, actor=actor.label, role=actor.role, action="ENROLLMENT_UPDATE", resource=f"enrollment:{e.id}",
                     subject_person_id=p.id, details={"changed": changed})
    return RowResult(i, roll, "UPDATED" if changed else "UNCHANGED", e.id, _person_ref(p), findings)


def _quarantine(db, sub, inst, raw, i, roll, findings: list[Finding]) -> RowResult:
    data = _raw(raw)
    codes = []
    for f in findings:
        if f.severity != "ERROR":
            continue
        codes.append(f.code)
        db.add(ValidationIssue(institution_id=inst.id, submission_id=sub.id, row_number=i, rule_code=f.code,
                               severity="ERROR", field=f.field, message=f.message, hint=f.hint, row_data=data))
    events.emit(db, "ISSUE_RAISED", institution_id=inst.id, payload={"submission_id": sub.id, "row": i,
                                                                     "roll_no": roll, "codes": codes})
    return RowResult(i, roll, "REJECTED", findings=findings)


def _store_findings(db, sub, inst, res: RowResult, i) -> None:
    for f in res.findings:
        if f.severity == "ERROR":
            continue
        db.add(ValidationIssue(institution_id=inst.id, submission_id=sub.id, enrollment_id=res.enrollment_id,
                               row_number=i, rule_code=f.code, severity=f.severity, field=f.field, message=f.message,
                               hint=f.hint, status="OPEN" if f.severity == "WARN" else "RESOLVED"))
