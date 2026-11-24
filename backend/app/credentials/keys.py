"""Issuer keys and the AICTE trust list (the set of issuers a verifier should accept)."""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Institution, IssuerKey, University, utcnow
from .crypto import b64u_dec, jwk, jws_sign, new_keypair

ROOT_KID = "aicte-root-1"
ROOT_URI = "urn:aicte:root"


def ensure_key(db: Session, issuer_type: str, ref: int | None, uri: str, name: str, kid: str) -> IssuerKey:
    k = db.execute(select(IssuerKey).where(IssuerKey.kid == kid)).scalar_one_or_none()
    if k:
        return k
    priv, pub = new_keypair()
    k = IssuerKey(kid=kid, issuer_type=issuer_type, issuer_ref=ref, issuer_uri=uri, name=name,
                  public_key=pub, private_key=priv)
    db.add(k)
    db.flush()
    return k


def root_key(db: Session) -> IssuerKey:
    return ensure_key(db, "AICTE", None, ROOT_URI, "All India Council for Technical Education (SIMULATED root)", ROOT_KID)


def institution_key(db: Session, inst: Institution) -> IssuerKey:
    return ensure_key(db, "INSTITUTION", inst.id, f"urn:aicte:institution:{inst.aicte_code}", inst.name,
                      f"inst-{inst.aicte_code.lower()}")


def university_key(db: Session, uni: University) -> IssuerKey:
    return ensure_key(db, "UNIVERSITY", uni.id, f"urn:aicte:university:{uni.code}", uni.name,
                      f"univ-{uni.code.lower()}")


def fingerprint(public_b64u: str) -> str:
    h = hashlib.sha256(b64u_dec(public_b64u)).hexdigest()[:20].upper()
    return " ".join(h[i:i + 4] for i in range(0, 20, 4))


def trust_list(db: Session) -> dict:
    rk = root_key(db)
    issuers = [{"kid": k.kid, "issuer": k.issuer_uri, "name": k.name, "type": k.issuer_type,
                "jwk": jwk(k.public_key, k.kid)}
               for k in db.execute(select(IssuerKey).where(IssuerKey.issuer_type != "AICTE")
                                   .order_by(IssuerKey.id)).scalars()]
    now = int(utcnow().timestamp())
    payload = {"iss": ROOT_URI, "iat": now, "type": "AICTEIssuerTrustList", "issuers": issuers}
    return {"jwt": jws_sign(payload, rk.private_key, rk.kid, typ="trust-list+jwt"),
            "count": len(issuers)}


def root_info(db: Session) -> dict:
    rk = root_key(db)
    return {"issuer": ROOT_URI, "name": rk.name, "jwk": jwk(rk.public_key, rk.kid),
            "fingerprint": fingerprint(rk.public_key)}
