from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pyotp

from ..config import settings


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=10)).decode()


def check_password(pw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_token(sub: str, kind: str = "access", ttl_minutes: int | None = None, **extra) -> str:
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=ttl_minutes) if ttl_minutes else timedelta(hours=settings.jwt_ttl_hours)
    payload = {"sub": sub, "kind": kind, "iat": now, "exp": now + ttl, **extra}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_token(token: str, kind: str = "access") -> dict:
    data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if data.get("kind") != kind:
        raise jwt.InvalidTokenError("wrong token kind")
    return data


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_ok(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1)


def totp_now(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="APAAR Registry")


def new_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, sha256_hash). Only the hash is stored."""
    raw = "ask_" + secrets.token_urlsafe(32)
    return raw, raw[:12], hashlib.sha256(raw.encode()).hexdigest()


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
