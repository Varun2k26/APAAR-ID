from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..identity.apaar_format import pretty
from ..models import Credential, Enrollment, IssuerKey, StatusList, University, utcnow
from . import keys, sdjwt, status_list
from .crypto import jws_peek, jws_verify

DEGREE_BY_CODE = {"BTECH": ("Bachelor of Technology", "B.Tech "), "BPHARM": ("Bachelor of Pharmacy", None),
                  "MBA": ("Master of Business Administration", None), "MCA": ("Master of Computer Applications", None),
                  "PGDM": ("Post Graduate Diploma in Management", None), "DPHARM": ("Diploma in Pharmacy", None),
                  "DIP": ("Diploma", "Diploma in ")}


def degree_title(code: str, program_name: str) -> tuple[str, str | None]:
    """('Bachelor of Technology', 'Computer Science & Engineering') from programme code + name."""
    title, strip = DEGREE_BY_CODE.get(code.split("-")[0], (program_name, None))
    if strip and program_name.startswith(strip):
        return title, program_name[len(strip):]
    return title, None

# Fields an employer sees by default. Everything else stays hidden unless the student opts in.
DEFAULT_REVEAL = {"ENROLLMENT": ["name", "institution", "program", "enrollment_status", "admission_year"],
                  "DEGREE": ["name", "apaar_id", "degree", "program", "institution", "university",
                             "class_awarded", "year_of_award"]}
SENSITIVE = {"social_category", "dob", "gender", "cgpa"}


def _status_entry(sl: StatusList, idx: int) -> dict:
    return {"type": "BitstringStatusListEntry", "statusPurpose": "revocation", "statusListIndex": str(idx),
            "statusListCredential": status_list.list_url(sl.id)}


def _issue(db: Session, key: IssuerKey, vc_type: str, cred_type: str, e: Enrollment, subject: dict) -> Credential:
    sl, idx = status_list.allocate(db)
    cid = f"urn:uuid:{uuid.uuid4()}"
    token = sdjwt.issue(private_key=key.private_key, kid=key.kid, issuer_uri=key.issuer_uri, issuer_name=key.name,
                        cred_id=cid, vc_type=vc_type, subject=subject, status=_status_entry(sl, idx),
                        issued_at=int(utcnow().timestamp()))
    c = Credential(id=cid, type=cred_type, person_id=e.person_id, enrollment_id=e.id, issuer_kid=key.kid,
                   status_list_id=sl.id, status_index=idx, sd_jwt=token, claims=subject)
    db.add(c)
    db.flush()
    return c


def issue_enrollment(db: Session, e: Enrollment) -> Credential:
    if e.status != "ACTIVE":
        raise ValueError(f"only ACTIVE enrolments can be credentialed (this one is {e.status})")
    existing = db.execute(select(Credential).where(Credential.enrollment_id == e.id, Credential.type == "ENROLLMENT",
                                                   Credential.revoked_at.is_(None))).scalar_one_or_none()
    if existing:
        return existing
    p, prog, inst = e.person, e.program, e.institution
    subject = {
        "name": p.name, "apaar_id": pretty(p.apaar_id) if p.apaar_id else p.provisional_id,
        "dob": p.dob.isoformat(), "gender": p.gender,
        "institution": f"{inst.name} ({inst.aicte_code})", "program": prog.name, "level": prog.level,
        "admission_year": f"{e.academic_year}-{(e.academic_year + 1) % 100:02d}",
        "year_of_study": e.year_of_study, "roll_no": e.roll_no, "enrollment_status": e.status,
        "social_category": e.social_category,
    }
    return _issue(db, keys.institution_key(db, inst), "EnrollmentCredential", "ENROLLMENT", e, subject)


def issue_degree(db: Session, e: Enrollment, uni: University, class_awarded: str, cgpa: float | None) -> Credential:
    if e.status != "GRADUATED":
        raise ValueError("a degree can only be issued for a GRADUATED enrolment")
    existing = db.execute(select(Credential).where(Credential.enrollment_id == e.id, Credential.type == "DEGREE",
                                                   Credential.revoked_at.is_(None))).scalar_one_or_none()
    if existing:
        raise ValueError("a valid degree credential already exists for this enrolment")
    p, prog, inst = e.person, e.program, e.institution
    subject = {
        "name": p.name, "apaar_id": pretty(p.apaar_id) if p.apaar_id else None, "dob": p.dob.isoformat(),
        "degree": degree_title(prog.code, prog.name)[0], "program": prog.name,
        "specialisation": degree_title(prog.code, prog.name)[1],
        "institution": inst.name, "university": uni.name, "class_awarded": class_awarded,
        "cgpa": cgpa, "year_of_award": datetime.now().year,
    }
    return _issue(db, keys.university_key(db, uni), "DegreeCredential", "DEGREE", e, subject)


def revoke(db: Session, c: Credential, reason: str) -> None:
    if c.revoked_at:
        return
    sl = db.get(StatusList, c.status_list_id)
    status_list.set_bit(db, sl, c.status_index, True)
    c.revoked_at, c.revocation_reason = utcnow(), reason


def revoke_for_enrollment(db: Session, enrollment_id: int, reason: str, types=("ENROLLMENT",)) -> int:
    n = 0
    for c in db.execute(select(Credential).where(Credential.enrollment_id == enrollment_id,
                                                 Credential.type.in_(types), Credential.revoked_at.is_(None))).scalars():
        revoke(db, c, reason)
        n += 1
    return n


def presentation_url(presentation: str) -> str:
    return f"{settings.public_base_url}/verify#vp={presentation}"


def verify(db: Session, presentation: str) -> dict:
    """Server-side mirror of the in-browser verifier (for ERP/HR integrations and tests)."""
    steps = []

    def resolve(kid):
        k = db.execute(select(IssuerKey).where(IssuerKey.kid == kid, IssuerKey.issuer_type != "AICTE")).scalar_one_or_none()
        return (k.public_key, k.issuer_uri, k.name) if k else None

    try:
        res = sdjwt.verify(presentation, resolve)
    except Exception as ex:      # noqa: BLE001 - every failure is a verification failure
        return {"valid": False, "reason": str(ex), "steps": steps}
    steps.append({"check": "issuer signature", "ok": True})
    payload = res["payload"]
    st = payload.get("credentialStatus", {})
    try:
        sl_id = int(st["statusListCredential"].rstrip("/").split("/")[-1])
        sl = db.get(StatusList, sl_id)
        rk = keys.root_key(db)
        _, sp = jws_verify(status_list.status_credential(db, sl), rk.public_key)
        bits = status_list.decode(sp["credentialSubject"]["encodedList"])
        revoked = status_list.get_bit(bits, int(st["statusListIndex"]))
    except Exception as ex:  # noqa: BLE001
        return {"valid": False, "reason": f"could not check revocation status: {ex}", "steps": steps}
    steps.append({"check": "not revoked", "ok": not revoked})
    hdr, _ = jws_peek(presentation.split("~")[0])
    k = db.execute(select(IssuerKey).where(IssuerKey.kid == hdr.get("kid"))).scalar_one()
    issuer = {"id": k.issuer_uri, "name": k.name}
    return {"valid": not revoked, "reason": "credential has been revoked" if revoked else None, "steps": steps,
            "issuer": issuer, "kid": hdr.get("kid"), "type": payload.get("type"), "credential_id": payload.get("jti"),
            "issued_at": payload.get("iat"), "claims": res["claims"]}
