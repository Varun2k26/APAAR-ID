"""Hash-chained, append-only audit log."""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..credentials.crypto import canonical
from ..models import AuditHead, AuditLog, utcnow

GENESIS = "0" * 64


def _entry_hash(prev: str, e: AuditLog) -> str:
    body = {
        "ts": e.ts.isoformat(timespec="microseconds"), "actor": e.actor, "role": e.actor_role,
        "action": e.action, "resource": e.resource, "subject": e.subject_person_id,
        "purpose": e.purpose, "details": e.details,
    }
    return hashlib.sha256(prev.encode() + canonical(body)).hexdigest()


def record(db: Session, *, actor: str, role: str, action: str, resource: str,
           subject_person_id: int | None = None, purpose: str | None = None,
           details: dict | None = None) -> AuditLog:
    """Append one entry. Caller commits. The head row is locked (FOR UPDATE on Postgres;
    SQLite already serialises writers) so concurrent appends cannot fork the chain."""
    head = db.execute(select(AuditHead).where(AuditHead.id == 1).with_for_update()).scalar_one_or_none()
    if head is None:
        head = AuditHead(id=1, last_hash=GENESIS)
        db.add(head)
        db.flush()
    e = AuditLog(ts=utcnow(), actor=actor, actor_role=role, action=action, resource=resource,
                 subject_person_id=subject_person_id, purpose=purpose, details=details,
                 prev_hash=head.last_hash, hash="")
    e.hash = _entry_hash(head.last_hash, e)
    head.last_hash = e.hash
    db.add(e)
    return e


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    n = 0
    for e in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        n += 1
        if e.prev_hash != prev:
            return {"ok": False, "entries_checked": n, "broken_at": e.id,
                    "reason": "prev_hash does not match the previous entry (row removed or reordered)"}
        if _entry_hash(prev, e) != e.hash:
            return {"ok": False, "entries_checked": n, "broken_at": e.id,
                    "reason": "entry content does not match its hash (row was edited)"}
        prev = e.hash
    head = db.get(AuditHead, 1)
    if head and n and head.last_hash != prev:
        return {"ok": False, "entries_checked": n, "broken_at": None,
                "reason": "chain head does not match the last entry (tail truncated)"}
    return {"ok": True, "entries_checked": n, "head": prev}
