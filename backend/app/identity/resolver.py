"""Identity resolution: turn a submitted row into a Person.

  APAAR given  -> must exist in the registry and match name (fuzzy) + DOB (exact).
                  Registry down -> accept as PENDING; a background job re-checks.
  APAAR absent -> provisional ID bound to a demographic fingerprint, with a link deadline.
"""
from __future__ import annotations

import secrets
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Person, utcnow
from ..validation.catalog import Finding
from . import apaar_client
from .names import name_similarity, normalize, phonetic_key


def _demographics_match(row: dict, name: str, dob: date) -> tuple[bool, float]:
    sim = name_similarity(row["name"], name)
    return (row["dob"] == dob and sim >= settings.registry_name_threshold), sim


def new_person(row: dict, **kw) -> Person:
    return Person(name=row["name"], name_norm=normalize(row["name"]), name_key=phonetic_key(row["name"]),
                  dob=row["dob"], gender=row["gender"], parent_name=row.get("parent_name"),
                  parent_key=phonetic_key(row.get("parent_name")) or None, exam_roll=row.get("exam_roll"), **kw)


def provisional_id() -> str:
    return f"PROV-{settings.current_year}-{secrets.token_hex(4).upper()}"


def registry_check(db: Session, apaar_id: str, row: dict) -> tuple[str, dict | None, list[Finding]]:
    """Returns (status, registry_record, findings). status in VERIFIED/PENDING/NOT_FOUND/MISMATCH."""
    try:
        rec = apaar_client.lookup(db, apaar_id)
    except apaar_client.RegistryUnavailable:
        return "PENDING", None, [Finding(
            "R43", "WARN", "APAAR registry unavailable. Accepted pending verification", "apaar_id",
            "No action needed. The record will be checked again automatically.")]
    if rec is None:
        return "NOT_FOUND", None, [Finding("R41", "ERROR", f"APAAR ID {apaar_id} was not found in the APAAR registry",
                                           "apaar_id", "Check for typing errors, or ask the student to confirm their APAAR ID in DigiLocker.")]
    ok, sim = _demographics_match(row, rec["name"], date.fromisoformat(rec["dob"]))
    if not ok:
        why = []
        if row["dob"] != date.fromisoformat(rec["dob"]):
            why.append("date of birth does not match")
        if sim < settings.registry_name_threshold:
            why.append(f"name does not match (similarity {sim:.2f})")
        # Deliberately do not reveal the registry's name/DOB to the submitter.
        return "MISMATCH", rec, [Finding("R42", "ERROR", "APAAR ID belongs to a different student: " + "; ".join(why),
                                         "apaar_id", "Either the APAAR ID or the name and date of birth were entered "
                                         "incorrectly. Confirm against the student's DigiLocker record.")]
    return "VERIFIED", rec, []


def resolve(db: Session, row: dict) -> tuple[Person | None, list[Finding], bool]:
    """Returns (person, findings, created). person None means the row must be quarantined."""
    apaar = row.get("apaar_id")
    if not apaar and row.get("nationality") in ("OCI", "PIO", "FOREIGN_NATIONAL"):
        p = new_person(row, provisional_id=f"INTL-{settings.current_year}-{secrets.token_hex(4).upper()}",
                       registry_status="EXEMPT")
        db.add(p)
        db.flush()
        return p, [Finding("R44", "INFO", f"Foreign national: APAAR ID not applicable. Recorded under {p.provisional_id}",
                           "apaar_id")], True
    if not apaar:
        p = new_person(row, provisional_id=provisional_id(), registry_status="PROVISIONAL",
                       link_deadline=date.today() + timedelta(days=settings.provisional_link_days))
        db.add(p)
        db.flush()
        return p, [Finding("R44", "WARN", f"No APAAR ID provided. Provisional ID {p.provisional_id} assigned; link an "
                           f"APAAR ID by {p.link_deadline}", "apaar_id",
                           "Resubmit this roll number with the APAAR ID once issued. The records will be merged.")], True

    existing = db.execute(select(Person).where(Person.apaar_id == apaar)).scalar_one_or_none()
    if existing:
        if existing.registry_status == "VERIFIED":
            ok, sim = _demographics_match(row, existing.name, existing.dob)
            if not ok:
                return None, [Finding("R42", "ERROR", "APAAR ID belongs to a different student (name or date of "
                                      "birth does not match the verified record)", "apaar_id",
                                      "Confirm against the student's DigiLocker record.")], False
        elif existing.registry_status == "PENDING":
            status, rec, f = registry_check(db, apaar, row)
            if status in ("NOT_FOUND", "MISMATCH"):
                return None, f, False
            if status == "VERIFIED":
                existing.registry_status, existing.registry_checked_at = "VERIFIED", utcnow()
        if not existing.parent_name and row.get("parent_name"):
            existing.parent_name = row["parent_name"]
            existing.parent_key = phonetic_key(row["parent_name"]) or None
        if not existing.exam_roll and row.get("exam_roll"):
            existing.exam_roll = row["exam_roll"]
        return existing, [], False

    status, rec, f = registry_check(db, apaar, row)
    if status in ("NOT_FOUND", "MISMATCH"):
        return None, f, False
    p = new_person(row, apaar_id=apaar, registry_status=status,
                   registry_checked_at=utcnow() if status == "VERIFIED" else None)
    if rec:   # the registry's spelling is canonical
        p.name, p.name_norm, p.name_key = rec["name"], normalize(rec["name"]), phonetic_key(rec["name"])
    db.add(p)
    db.flush()
    return p, f, True
