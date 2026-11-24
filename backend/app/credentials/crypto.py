"""Ed25519 + compact JWS (EdDSA) helpers, kept dependency-light so the browser verifier
(@noble/ed25519) can mirror it exactly."""
from __future__ import annotations

import base64
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False, default=str).encode()


def sha256_b64u(s: str) -> str:
    return b64u(hashlib.sha256(s.encode("ascii")).digest())


def new_keypair() -> tuple[str, str]:
    """Returns (private_b64u, public_b64u) as raw 32-byte keys."""
    sk = Ed25519PrivateKey.generate()
    priv = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b64u(priv), b64u(pub)


def jwk(public_b64u: str, kid: str) -> dict:
    return {"kty": "OKP", "crv": "Ed25519", "x": public_b64u, "kid": kid, "alg": "EdDSA"}


def jws_sign(payload: dict, private_b64u: str, kid: str, typ: str = "JWT") -> str:
    header = {"alg": "EdDSA", "typ": typ, "kid": kid}
    signing_input = f"{b64u(canonical(header))}.{b64u(canonical(payload))}"
    sk = Ed25519PrivateKey.from_private_bytes(b64u_dec(private_b64u))
    return f"{signing_input}.{b64u(sk.sign(signing_input.encode('ascii')))}"


def jws_verify(token: str, public_b64u: str) -> tuple[dict, dict]:
    """Returns (header, payload); raises ValueError on a bad signature."""
    try:
        h, p, s = token.split(".")
    except ValueError as e:
        raise ValueError("malformed JWS") from e
    pk = Ed25519PublicKey.from_public_bytes(b64u_dec(public_b64u))
    try:
        pk.verify(b64u_dec(s), f"{h}.{p}".encode("ascii"))
    except Exception as e:  # InvalidSignature
        raise ValueError("signature does not verify") from e
    return json.loads(b64u_dec(h)), json.loads(b64u_dec(p))


def jws_peek(token: str) -> tuple[dict, dict]:
    h, p, _ = token.split(".")
    return json.loads(b64u_dec(h)), json.loads(b64u_dec(p))
