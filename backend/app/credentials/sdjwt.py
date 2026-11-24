"""SD-JWT (selective disclosure) issuance and verification for W3C-style credentials.

Issued form:      <issuer-signed JWT>~<disclosure>~<disclosure>~...~
Presentation:     the same JWT with only the disclosures the holder chooses to reveal.

Each subject claim becomes a disclosure  base64url(JSON([salt, name, value]))  and only its
SHA-256 digest is signed. A verifier can check any revealed claim against the signature but
learns nothing about claims that were not revealed. Two decoy digests hide the claim count.

Not in the MVP: key binding (KB-JWT). Students do not hold device keys yet, so whoever holds a
presentation can show it; the employer still matches the disclosed name to a photo ID.
"""
from __future__ import annotations

import hashlib
import json
import os

from .crypto import b64u, b64u_dec, jws_sign, jws_verify, sha256_b64u

CONTEXT = ["https://www.w3.org/ns/credentials/v2"]


def make_disclosure(name: str, value) -> str:
    salt = b64u(os.urandom(16))
    return b64u(json.dumps([salt, name, value], ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def issue(*, private_key: str, kid: str, issuer_uri: str, issuer_name: str, cred_id: str, vc_type: str,
          subject: dict, status: dict, issued_at: int) -> str:
    disclosures = [make_disclosure(k, v) for k, v in subject.items()]
    digests = [sha256_b64u(d) for d in disclosures]
    digests.append(b64u(hashlib.sha256(os.urandom(32)).digest()))      # decoy hides the exact claim count
    digests.sort()
    # Kept deliberately small so the presentation fits a scannable QR: the issuer's display name
    # comes from the AICTE trust list (looked up by kid), not from the credential.
    payload = {
        "iss": issuer_uri, "iat": issued_at, "jti": cred_id,
        "@context": CONTEXT,
        "type": ["VerifiableCredential", vc_type],
        "_sd_alg": "sha-256",
        "credentialStatus": status,
        "credentialSubject": {"_sd": digests},
    }
    token = jws_sign(payload, private_key, kid, typ="vc+sd-jwt")
    return token + "~" + "".join(d + "~" for d in disclosures)


def split(sd_jwt: str) -> tuple[str, list[str]]:
    parts = sd_jwt.strip().split("~")
    return parts[0], [p for p in parts[1:] if p]


def decode_disclosure(d: str) -> tuple[str, str, object]:
    arr = json.loads(b64u_dec(d))
    if not (isinstance(arr, list) and len(arr) == 3):
        raise ValueError("malformed disclosure")
    return arr[0], arr[1], arr[2]


def present(sd_jwt: str, reveal: list[str]) -> str:
    token, discs = split(sd_jwt)
    keep = [d for d in discs if decode_disclosure(d)[1] in set(reveal)]
    return token + "~" + "".join(d + "~" for d in keep)


def verify(presentation: str, resolve_key) -> dict:
    """resolve_key(kid) -> (public_b64u, issuer_uri, issuer_name) or None.
    Returns {"header","payload","claims"}; raises ValueError with a human reason."""
    token, discs = split(presentation)
    from .crypto import jws_peek
    header, _ = jws_peek(token)
    if header.get("alg") != "EdDSA":
        raise ValueError("unsupported algorithm")
    k = resolve_key(header.get("kid"))
    if not k:
        raise ValueError("issuer is not on the AICTE trust list")
    pub, issuer_uri, _name = k
    header, payload = jws_verify(token, pub)
    if payload.get("iss") != issuer_uri:
        raise ValueError("issuer in credential does not match the trusted key")
    sd = set(payload.get("credentialSubject", {}).get("_sd", []))
    claims, seen = {}, set()
    for d in discs:
        h = sha256_b64u(d)
        if h not in sd:
            raise ValueError("a disclosed field was altered (digest not signed by issuer)")
        if h in seen:
            raise ValueError("duplicate disclosure")
        seen.add(h)
        _salt, name, value = decode_disclosure(d)
        claims[name] = value
    return {"header": header, "payload": payload, "claims": claims}
