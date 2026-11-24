"""Row parsing + the row-level (no database) rules: formats, enums, category consistency,
lateral entry, age and admission window."""
from __future__ import annotations

import re
from datetime import date, datetime

from ..config import settings
from ..identity import apaar_format
from .catalog import Finding

FIELDS = ["roll_no", "apaar_id", "name", "dob", "gender", "parent_name", "qualifying_exam_roll",
          "program_code", "admission_date", "year_of_study", "mode", "seat_type", "social_category",
          "nationality"]
REQUIRED = ["roll_no", "name", "dob", "gender", "program_code", "admission_date", "seat_type",
            "social_category", "nationality"]

ENUMS = {
    "gender": {"M", "F", "O"},
    "mode": {"REGULAR", "ODL", "ONLINE"},
    "seat_type": {"MERIT", "MANAGEMENT", "NRI", "TFW", "FOREIGN", "LATERAL"},
    "social_category": {"GEN", "EWS", "OBC-NCL", "SC", "ST"},
    "nationality": {"INDIAN", "NRI", "OCI", "PIO", "FOREIGN_NATIONAL"},
}
ALIASES = {
    "gender": {"MALE": "M", "FEMALE": "F", "OTHER": "O", "TRANSGENDER": "O"},
    "social_category": {"GENERAL": "GEN", "UR": "GEN", "OPEN": "GEN", "OBC": "OBC-NCL", "OBCNCL": "OBC-NCL",
                        "OBC_NCL": "OBC-NCL"},
    "nationality": {"IN": "INDIAN", "INDIA": "INDIAN", "FN": "FOREIGN_NATIONAL", "FOREIGN": "FOREIGN_NATIONAL",
                    "FOREIGN NATIONAL": "FOREIGN_NATIONAL"},
    "seat_type": {"GENERAL": "MERIT", "CONVENER": "MERIT", "GOVT": "MERIT", "MGMT": "MANAGEMENT",
                  "FN": "FOREIGN", "OCI": "FOREIGN", "PIO": "FOREIGN", "LE": "LATERAL"},
    "mode": {"FULL-TIME": "REGULAR", "FULLTIME": "REGULAR", "DISTANCE": "ODL"},
}
RESERVED = {"EWS", "OBC-NCL", "SC", "ST"}
REGULAR_SEATS = {"MERIT", "MANAGEMENT", "NRI"}
SUPERNUMERARY = {"TFW", "FOREIGN", "LATERAL"}

LABEL = {"roll_no": "Roll number", "apaar_id": "APAAR ID", "name": "Name", "dob": "Date of birth", "gender": "Gender",
         "parent_name": "Parent or guardian", "qualifying_exam_roll": "Qualifying exam roll number",
         "program_code": "Programme code", "admission_date": "Date of admission", "year_of_study": "Year of study",
         "mode": "Mode of study", "seat_type": "Seat type", "social_category": "Social category", "nationality": "Nationality"}
NAT_LABEL = {"INDIAN": "an Indian", "NRI": "an NRI", "OCI": "an OCI", "PIO": "a PIO", "FOREIGN_NATIONAL": "a foreign national"}

_SPLIT = re.compile(r"\s*[;,/|+&]\s*|\s+AND\s+", re.I)


def parse_date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _enum(field: str, raw: str, findings: list[Finding]) -> str | None:
    v = (raw or "").strip().upper()
    if not v:
        return None
    parts = [p for p in _SPLIT.split(v) if p]
    if len(parts) > 1:
        mapped = {ALIASES.get(field, {}).get(p, p) for p in parts}
        valid = mapped & ENUMS[field]
        if len(valid) > 1:
            findings.append(Finding("R30", "ERROR",
                                    f"{LABEL[field]} has more than one value ({', '.join(sorted(valid))}); only one is allowed",
                                    field, "Use the value shown on the admission record."))
            return None
    v = ALIASES.get(field, {}).get(v, v)
    if v not in ENUMS[field]:
        findings.append(Finding("R50", "ERROR", f"{LABEL[field]} '{raw}' is not a valid value. Allowed values: "
                                f"{', '.join(sorted(ENUMS[field]))}", field, "Use the values listed in the template."))
        return None
    return v


def parse_row(raw: dict, programs_by_code: dict) -> tuple[dict | None, list[Finding]]:
    """Returns (clean_row, findings). clean_row is None when there are ERROR findings."""
    f: list[Finding] = []
    r = {k: (str(raw.get(k)).strip() if raw.get(k) is not None else "") for k in FIELDS}
    for k in REQUIRED:
        if not r[k]:
            f.append(Finding("R50", "ERROR", f"{LABEL[k]} is required", k))
    out: dict = {"roll_no": r["roll_no"], "name": " ".join(r["name"].split()),
                 "parent_name": " ".join(r["parent_name"].split()) or None,
                 "exam_roll": r["qualifying_exam_roll"].upper() or None}

    out["apaar_id"] = apaar_format.clean(r["apaar_id"]) if r["apaar_id"] else None
    if r["apaar_id"]:
        ok, why = apaar_format.is_valid(r["apaar_id"])
        if not ok:
            f.append(Finding("R40", "ERROR", f"APAAR ID {r['apaar_id']} is not valid: {why}", "apaar_id",
                             "Check it against the student's APAAR card or DigiLocker. If the student does not yet "
                             "have one, leave it blank and a provisional ID will be assigned."))
    for k in ("dob", "admission_date"):
        if r[k]:
            d = parse_date(r[k])
            if not d:
                f.append(Finding("R50", "ERROR", f"{LABEL[k]} '{r[k]}' is not a valid date", k, "Use the format YYYY-MM-DD."))
            out[k] = d
    for k in ("gender", "mode", "seat_type", "social_category", "nationality"):
        out[k] = _enum(k, r[k], f) if r[k] else None
    out["mode"] = out["mode"] or "REGULAR"
    try:
        out["year_of_study"] = int(r["year_of_study"] or 1)
        if not 1 <= out["year_of_study"] <= 5:
            raise ValueError
    except ValueError:
        f.append(Finding("R50", "ERROR", f"Year of study '{r['year_of_study']}' must be between 1 and 5", "year_of_study"))
    prog = programs_by_code.get(r["program_code"].upper()) if r["program_code"] else None
    if r["program_code"] and not prog:
        f.append(Finding("R51", "ERROR", f"Programme code '{r['program_code']}' is not approved for this institution",
                         "program_code", "Approved codes: " + ", ".join(sorted(programs_by_code)[:12])))
    out["program"] = prog

    if not any(x.severity == "ERROR" for x in f):
        f.extend(row_rules(out))
    if any(x.severity == "ERROR" for x in f):
        return None, f
    return out, f


def row_rules(r: dict) -> list[Finding]:
    f: list[Finding] = []
    nat, cat, seat = r["nationality"], r["social_category"], r["seat_type"]
    non_indian = nat in {"OCI", "PIO", "FOREIGN_NATIONAL"}
    if cat in RESERVED and non_indian:
        f.append(Finding("R31", "ERROR", f"{cat} reservation claimed for {NAT_LABEL.get(nat, nat)} student", "social_category",
                         "Reservation categories apply only to Indian nationals. Correct the category or the nationality."))
    if seat == "FOREIGN" and nat in {"INDIAN"}:
        f.append(Finding("R32", "ERROR", "FN/OCI/PIO supernumerary seat allotted to a resident Indian",
                         "seat_type", "These seats are reserved for foreign nationals, OCI and PIO candidates."))
    if seat == "TFW" and nat != "INDIAN":
        f.append(Finding("R32", "ERROR", f"Tuition fee waiver seat allotted to {NAT_LABEL.get(nat, nat)} student", "seat_type",
                         "Tuition fee waiver seats are for resident Indian students who meet the income criterion."))
    if seat == "NRI" and nat == "INDIAN":
        f.append(Finding("R33", "WARN", "NRI seat allotted to a resident Indian", "seat_type",
                         "Permitted only for NRI-sponsored candidates. Keep the sponsorship documents on file."))
    if r.get("apaar_id") and nat == "FOREIGN_NATIONAL":
        f.append(Finding("R34", "WARN", "Foreign national reported with an APAAR ID", "apaar_id",
                         "APAAR IDs are issued to students in the Indian education system. Check the nationality."))
    prog = r.get("program")
    if seat == "LATERAL" and (r["year_of_study"] != 2 or (prog and prog.level != "UG")):
        f.append(Finding("R23", "ERROR", "Lateral entry is permitted only into the second year of an undergraduate programme",
                         "seat_type", "Set the year of study to 2, or choose a different seat type."))
    dob, adm = r.get("dob"), r.get("admission_date")
    if dob and adm:
        age = (adm - dob).days / 365.25
        if age < 14 or age > 60:
            f.append(Finding("R50", "ERROR", f"Age at admission would be {age:.1f} years", "dob", "Check the date of birth."))
        elif age < 15 or age > 40:
            f.append(Finding("R52", "WARN", f"Unusual age at admission ({age:.1f} years)", "dob"))
    if adm:
        if adm > date.today():
            f.append(Finding("R53", "ERROR", f"Date of admission {adm} is in the future", "admission_date"))
        elif adm < settings.admission_open:
            f.append(Finding("R53", "ERROR", f"Date of admission {adm} is before admissions opened on "
                             f"{settings.admission_open}", "admission_date",
                             f"Submissions are for the {settings.current_year}-{(settings.current_year + 1) % 100:02d} academic year."))
        elif adm > settings.admission_cutoff:
            f.append(Finding("R53", "WARN", f"Date of admission {adm} is after the last date of admission "
                             f"({settings.admission_cutoff})", "admission_date"))
    return f
