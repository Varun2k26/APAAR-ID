"""W3C Bitstring Status List (revocation).

The verifier downloads the whole (gzip-compressed) list, so the server learns nothing about
which credential is being checked ('herd privacy'). Indices are assigned at random for the
same reason. Bit 0 is the left-most bit of the first byte, as in the spec.
"""
from __future__ import annotations

import base64
import gzip
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Credential, StatusList, utcnow
from .crypto import jws_sign
from .keys import ROOT_URI, root_key

SIZE = 131_072          # 16 KiB, the spec's minimum for herd privacy


def current_list(db: Session) -> StatusList:
    sl = db.execute(select(StatusList).where(StatusList.used < StatusList.size * 0.5)
                    .order_by(StatusList.id).with_for_update()).scalars().first()
    if sl is None:
        sl = StatusList(purpose="revocation", bits=bytes(SIZE // 8), size=SIZE, used=0)
        db.add(sl)
        db.flush()
    return sl


def allocate(db: Session) -> tuple[StatusList, int]:
    sl = current_list(db)
    taken = set(db.execute(select(Credential.status_index).where(Credential.status_list_id == sl.id)).scalars())
    while True:
        idx = secrets.randbelow(sl.size)
        if idx not in taken:
            break
    sl.used += 1
    return sl, idx


def set_bit(db: Session, sl: StatusList, idx: int, value: bool = True) -> None:
    b = bytearray(sl.bits)
    if value:
        b[idx // 8] |= 1 << (7 - idx % 8)
    else:
        b[idx // 8] &= ~(1 << (7 - idx % 8))
    sl.bits = bytes(b)
    sl.updated_at = utcnow()


def get_bit(bits: bytes, idx: int) -> bool:
    return bool(bits[idx // 8] >> (7 - idx % 8) & 1)


def list_url(sl_id: int) -> str:
    return f"{settings.public_base_url}/api/v1/status-lists/{sl_id}"


def encoded(sl: StatusList) -> str:
    return "u" + base64.urlsafe_b64encode(gzip.compress(sl.bits, mtime=0)).rstrip(b"=").decode()


def status_credential(db: Session, sl: StatusList) -> str:
    rk = root_key(db)
    now = int(utcnow().timestamp())
    payload = {
        "iss": ROOT_URI, "iat": now,
        "@context": ["https://www.w3.org/ns/credentials/v2"],
        "type": ["VerifiableCredential", "BitstringStatusListCredential"],
        "id": list_url(sl.id),
        "validFrom": utcnow().isoformat() + "Z",
        "credentialSubject": {"id": list_url(sl.id) + "#list", "type": "BitstringStatusList",
                              "statusPurpose": sl.purpose, "encodedList": encoded(sl)},
    }
    return jws_sign(payload, rk.private_key, rk.kid, typ="statuslist+jwt")


def decode(encoded_list: str) -> bytes:
    s = encoded_list[1:] if encoded_list.startswith("u") else encoded_list
    return gzip.decompress(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
