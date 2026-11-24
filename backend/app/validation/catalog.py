"""The rule catalogue. Every finding the system produces carries one of these codes."""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field


@dataclass
class Finding:
    code: str
    severity: str            # ERROR (row quarantined) / WARN (accepted, flagged) / INFO
    message: str
    field: str | None = None
    hint: str | None = None
    extra: dict = dc_field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "field": self.field,
                "message": self.message, "hint": self.hint, "title": RULES.get(self.code, {}).get("title")}


RULES: dict[str, dict] = {
    # duplicates
    "R01": {"title": "APAAR ID repeated within the institution", "group": "Duplicates", "severity": "ERROR"},
    "R02": {"title": "Roll number repeated in the file", "group": "Duplicates", "severity": "ERROR"},
    "R03": {"title": "Possible duplicate within the institution", "group": "Duplicates", "severity": "WARN"},
    "R10": {"title": "Enrolled at another institution", "group": "Duplicates", "severity": "WARN"},
    "R11": {"title": "Possible duplicate at another institution", "group": "Duplicates", "severity": "WARN"},
    "R12": {"title": "Concurrent programme permitted", "group": "Duplicates", "severity": "INFO"},
    # intake
    "R20": {"title": "Admissions over approved intake", "group": "Intake", "severity": "WARN"},
    "R21": {"title": "Supernumerary seats over cap", "group": "Intake", "severity": "WARN"},
    "R22": {"title": "NRI seats over cap", "group": "Intake", "severity": "WARN"},
    "R23": {"title": "Invalid lateral entry", "group": "Intake", "severity": "ERROR"},
    # categories
    "R30": {"title": "More than one value", "group": "Categories", "severity": "ERROR"},
    "R31": {"title": "Reservation for a non-Indian national", "group": "Categories", "severity": "ERROR"},
    "R32": {"title": "Seat type does not match nationality", "group": "Categories", "severity": "ERROR"},
    "R33": {"title": "NRI seat for a resident Indian", "group": "Categories", "severity": "WARN"},
    "R34": {"title": "Foreign national with an APAAR ID", "group": "Categories", "severity": "WARN"},
    "R35": {"title": "Category changed after admission", "group": "Categories", "severity": "WARN"},
    # identity
    "R40": {"title": "Invalid APAAR ID", "group": "Identity", "severity": "ERROR"},
    "R41": {"title": "APAAR ID not found", "group": "Identity", "severity": "ERROR"},
    "R42": {"title": "APAAR ID belongs to another student", "group": "Identity", "severity": "ERROR"},
    "R43": {"title": "Verification pending", "group": "Identity", "severity": "WARN"},
    "R44": {"title": "Provisional ID assigned", "group": "Identity", "severity": "WARN"},
    "R45": {"title": "Roll number linked to another APAAR ID", "group": "Identity", "severity": "ERROR"},
    "R46": {"title": "Identity details differ from APAAR", "group": "Identity", "severity": "WARN"},
    # hygiene
    "R50": {"title": "Missing or invalid value", "group": "Hygiene", "severity": "ERROR"},
    "R51": {"title": "Programme not approved", "group": "Hygiene", "severity": "ERROR"},
    "R52": {"title": "Implausible age", "group": "Hygiene", "severity": "WARN"},
    "R53": {"title": "Date of admission outside the admission period", "group": "Hygiene", "severity": "ERROR"},
    "R54": {"title": "Reported late", "group": "Hygiene", "severity": "WARN"},
}
