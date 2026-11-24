"""APAAR ID format check.

APAAR IDs are 12 digits. The real check-digit algorithm is not public, so this MVP assumes a
Verhoeff check digit (the scheme Aadhaar uses). It is isolated here so the real algorithm can
be dropped in without touching anything else. Verhoeff catches every single-digit typo and
every adjacent transposition, which are the two most common data-entry errors.
"""
from __future__ import annotations

import random

_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def _checksum(num: str) -> int:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c


def check_digit(body: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(body)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def clean(apaar: str | None) -> str:
    return "".join(ch for ch in (apaar or "") if ch.isdigit())


def is_valid(apaar: str | None) -> tuple[bool, str | None]:
    """Returns (ok, reason)."""
    raw = (apaar or "").strip()
    if not raw:
        return False, "missing"
    if any(not (c.isdigit() or c in " -") for c in raw):
        return False, "it must contain digits only"
    digits = clean(raw)
    if len(digits) != 12:
        return False, f"it must have 12 digits, not {len(digits)}"
    if digits[0] == "0":
        return False, "it cannot start with 0"
    if _checksum(digits) != 0:
        return False, "the check digit does not match, usually a typing error or two swapped digits"
    return True, None


def generate(rng: random.Random) -> str:
    body = str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(10))
    return body + check_digit(body)


def pretty(apaar: str | None) -> str:
    d = clean(apaar)
    return f"{d[:4]} {d[4:8]} {d[8:]}" if len(d) == 12 else (apaar or "")


def mask(apaar: str | None) -> str:
    d = clean(apaar)
    return f"XXXX XXXX {d[8:]}" if len(d) == 12 else "—"
