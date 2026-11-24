from __future__ import annotations

import io
import json

import jwt
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import PERMISSIONS, Principal, current
from ..auth.security import (check_password, make_token, new_totp_secret, read_token, totp_now, totp_ok, totp_uri)
from ..config import DATA_DIR, settings
from ..db import get_db
from ..identity.apaar_format import clean
from ..models import Institution, Person, University, User
from ..services import audit

router = APIRouter(prefix="/api/v1", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class MfaIn(BaseModel):
    mfa_token: str
    code: str


class CodeIn(BaseModel):
    code: str


def user_out(db: Session, u: User) -> dict:
    inst = db.get(Institution, u.institution_id) if u.institution_id else None
    uni = db.get(University, u.university_id) if u.university_id else None
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
            "institution": {"id": inst.id, "name": inst.name, "code": inst.aicte_code, "state": inst.state} if inst else None,
            "university": {"id": uni.id, "name": uni.name} if uni else None, "regulator_body": u.regulator_body,
            "person_id": u.person_id, "mfa_enabled": u.mfa_enabled, "permissions": sorted(PERMISSIONS.get(u.role, []))}


def _issue(db: Session, u: User) -> dict:
    audit.record(db, actor=u.username, role=u.role, action="LOGIN", resource=f"user:{u.id}",
                 subject_person_id=u.person_id, details={"mfa": u.mfa_enabled})
    db.commit()
    return {"access_token": make_token(str(u.id)), "user": user_out(db, u)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.username == body.username.strip().lower())).scalar_one_or_none()
    if not u or not check_password(body.password, u.password_hash):
        raise HTTPException(401, "wrong username or password")
    if u.mfa_enabled:
        return {"mfa_required": True, "mfa_token": make_token(str(u.id), kind="mfa", ttl_minutes=5)}
    return _issue(db, u)


@router.post("/auth/mfa")
def mfa(body: MfaIn, db: Session = Depends(get_db)):
    try:
        data = read_token(body.mfa_token, kind="mfa")
    except jwt.PyJWTError:
        raise HTTPException(401, "MFA step expired; log in again")
    u = db.get(User, int(data["sub"]))
    if not u or not u.totp_secret or not totp_ok(u.totp_secret, body.code):
        raise HTTPException(401, "invalid authenticator code")
    return _issue(db, u)


@router.get("/auth/me")
def me(p: Principal = Depends(current), db: Session = Depends(get_db)):
    if p.user_id is None:
        return {"role": p.role, "label": p.label, "institution_id": p.institution_id}
    return user_out(db, db.get(User, p.user_id))


@router.post("/auth/mfa/setup")
def mfa_setup(p: Principal = Depends(current), db: Session = Depends(get_db)):
    if p.user_id is None or p.role == "STUDENT":
        raise HTTPException(400, "MFA applies to staff accounts")
    u = db.get(User, p.user_id)
    u.totp_secret = new_totp_secret()
    u.mfa_enabled = False
    db.commit()
    uri = totp_uri(u.totp_secret, u.username)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return {"otpauth_uri": uri, "secret": u.totp_secret, "qr_svg": buf.getvalue().decode()}


@router.post("/auth/mfa/enable")
def mfa_enable(body: CodeIn, p: Principal = Depends(current), db: Session = Depends(get_db)):
    u = db.get(User, p.user_id)
    if not u or not u.totp_secret or not totp_ok(u.totp_secret, body.code):
        raise HTTPException(400, "code does not match; check the authenticator app's clock")
    u.mfa_enabled = True
    audit.record(db, actor=u.username, role=u.role, action="MFA_ENABLED", resource=f"user:{u.id}")
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- SIMULATED DigiLocker (OAuth2 code flow)
class DlAuthorizeIn(BaseModel):
    apaar_id: str
    otp: str
    state: str | None = None


@router.post("/mock/digilocker/authorize", tags=["simulated"])
def digilocker_authorize(body: DlAuthorizeIn, db: Session = Depends(get_db)):
    """SIMULATED DigiLocker consent screen. The real flow: student authenticates with DigiLocker
    (Aadhaar OTP), DigiLocker redirects back with ?code=, we exchange the code for the APAAR."""
    if body.otp.strip() != "123456":
        raise HTTPException(401, "wrong OTP (the simulated DigiLocker accepts 123456)")
    apaar = clean(body.apaar_id)
    code = make_token(apaar, kind="dl_code", ttl_minutes=5)
    return {"code": code, "state": body.state, "redirect": f"/auth/digilocker/callback?code={code}&state={body.state or ''}"}


@router.post("/auth/digilocker/token")
def digilocker_token(body: CodeIn, db: Session = Depends(get_db)):
    try:
        data = read_token(body.code, kind="dl_code")
    except jwt.PyJWTError:
        raise HTTPException(401, "authorization code invalid or expired")
    apaar = data["sub"]
    person = db.execute(select(Person).where(Person.apaar_id == apaar)).scalar_one_or_none()
    if not person:
        raise HTTPException(404, "DigiLocker confirmed this APAAR, but no institution has reported an enrolment for it yet")
    u = db.execute(select(User).where(User.person_id == person.id)).scalar_one_or_none()
    if not u:
        u = User(username=f"student-{apaar}", display_name=person.name, role="STUDENT", person_id=person.id)
        db.add(u)
        db.flush()
    return _issue(db, u)


# ---------------------------------------------------------------- demo helper
@router.get("/dev/demo-accounts", tags=["demo"])
def demo_accounts(db: Session = Depends(get_db)):
    if not settings.demo_mode:
        raise HTTPException(404)
    f = DATA_DIR / "demo_accounts.json"
    if not f.exists():
        return {"accounts": [], "students": []}
    data = json.loads(f.read_text())
    for a in data.get("accounts", []):
        u = db.execute(select(User).where(User.username == a["username"])).scalar_one_or_none()
        a["mfa_enabled"] = bool(u and u.mfa_enabled)
        if u:
            inst = db.get(Institution, u.institution_id) if u.institution_id else None
            uni = db.get(University, u.university_id) if u.university_id else None
            a["display_name"] = u.display_name
            a["org"] = inst.name if inst else uni.name if uni else u.regulator_body or "AICTE"
        a["totp_now"] = totp_now(u.totp_secret) if u and u.mfa_enabled and u.totp_secret else None
    return data


@router.get("/dev/demo-files/{name}", tags=["demo"])
def demo_file(name: str):
    from fastapi.responses import FileResponse
    if not settings.demo_mode:
        raise HTTPException(404)
    f = (DATA_DIR / "demo" / name).resolve()
    if f.parent != (DATA_DIR / "demo").resolve() or not f.is_file() or f.suffix != ".csv":
        raise HTTPException(404)
    return FileResponse(f, media_type="text/csv", filename=name)
