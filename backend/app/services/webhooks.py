"""Outbound webhooks to institution ERPs: HMAC-SHA256 signed, retried with backoff.
Reads the outbox (`events`) with a cursor, so nothing is lost if the process restarts."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Event, JobState, Webhook, WebhookDelivery, utcnow

log = logging.getLogger("webhooks")
MAX_ATTEMPTS = 6


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _cursor(db: Session) -> int:
    js = db.get(JobState, "webhook_cursor")
    if js is None:
        last = db.execute(select(Event.id).order_by(Event.id.desc())).scalars().first() or 0
        js = JobState(name="webhook_cursor", value=str(last))
        db.add(js)
        db.flush()
    return int(js.value)


def enqueue(db: Session) -> int:
    cur = _cursor(db)
    evs = db.execute(select(Event).where(Event.id > cur).order_by(Event.id).limit(500)).scalars().all()
    if not evs:
        return 0
    hooks = db.execute(select(Webhook).where(Webhook.active.is_(True))).scalars().all()
    n = 0
    for ev in evs:
        for h in hooks:
            if ev.type in h.event_types and h.institution_id in (ev.institution_id, ev.other_institution_id):
                db.add(WebhookDelivery(webhook_id=h.id, event_id=ev.id))
                n += 1
    db.get(JobState, "webhook_cursor").value = str(evs[-1].id)
    db.commit()
    return n


def body_for(ev: Event, h: Webhook) -> bytes:
    data = {"id": ev.id, "type": ev.type, "created_at": ev.created_at.isoformat() + "Z", "institution_id": h.institution_id,
            "enrollment_id": ev.enrollment_id, "data": ev.payload}
    return json.dumps(data, separators=(",", ":")).encode()


def deliver_due(db: Session, client: httpx.Client) -> int:
    now = utcnow()
    due = db.execute(select(WebhookDelivery).where(WebhookDelivery.status == "PENDING",
                                                   WebhookDelivery.next_attempt_at <= now).limit(50)).scalars().all()
    jobs = []
    for d in due:
        h, ev = db.get(Webhook, d.webhook_id), db.get(Event, d.event_id)
        jobs.append((d.id, h.url, h.secret, ev.type, body_for(ev, h)))
    db.rollback()                         # never hold a DB transaction across network I/O
    results = []
    for did, url, secret, etype, body in jobs:
        try:
            r = client.post(url, content=body, timeout=5.0, headers={
                "Content-Type": "application/json", "X-Registry-Event": etype, "X-Registry-Delivery": str(did),
                "X-Registry-Signature": sign(secret, body)})
            results.append((did, r.status_code, None))
        except httpx.HTTPError as e:
            results.append((did, None, str(e)[:300]))
    for did, code, err in results:
        d = db.get(WebhookDelivery, did)
        d.attempts += 1
        d.response_code = code
        if code and 200 <= code < 300:
            d.status, d.delivered_at, d.last_error = "DELIVERED", utcnow(), None
        else:
            d.last_error = err or f"HTTP {code}"
            if d.attempts >= MAX_ATTEMPTS:
                d.status = "FAILED"
            else:
                d.next_attempt_at = utcnow() + timedelta(seconds=5 * 2 ** d.attempts)
    db.commit()
    return len(results)


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(sign(secret, body), header)


def webhooks_for(db: Session, institution_id: int):
    return db.execute(select(Webhook).where(or_(Webhook.institution_id == institution_id))).scalars().all()
