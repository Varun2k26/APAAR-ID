from __future__ import annotations

import asyncio
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.deps import Principal, current, need, resolve_principal
from ..auth.security import new_api_key
from ..config import settings
from ..db import SessionLocal, get_db
from ..models import ApiKey, Event, Webhook, WebhookDelivery
from ..services import audit
from ..services.events import WEBHOOK_EVENT_TYPES

router = APIRouter(prefix="/api/v1", tags=["integration"])


class KeyIn(BaseModel):
    label: str


@router.get("/integration/api-keys")
def list_keys(p: Principal = Depends(need("integration:manage")), db: Session = Depends(get_db)):
    return [{"id": k.id, "label": k.label, "prefix": k.prefix, "revoked": k.revoked, "created_at": k.created_at.isoformat(),
             "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}
            for k in db.execute(select(ApiKey).where(ApiKey.institution_id == p.institution_id)).scalars()]


@router.post("/integration/api-keys", summary="Create an ERP API key (shown once)")
def create_key(body: KeyIn, p: Principal = Depends(need("integration:manage")), db: Session = Depends(get_db)):
    raw, prefix, h = new_api_key()
    k = ApiKey(institution_id=p.institution_id, label=body.label, prefix=prefix, key_hash=h)
    db.add(k)
    db.flush()
    audit.record(db, actor=p.label, role=p.role, action="API_KEY_CREATE", resource=f"api_key:{k.id}",
                 details={"label": body.label})
    db.commit()
    return {"id": k.id, "label": k.label, "prefix": prefix, "key": raw,
            "note": "Copy it now. Only a SHA-256 hash is stored."}


@router.delete("/integration/api-keys/{kid}")
def revoke_key(kid: int, p: Principal = Depends(need("integration:manage")), db: Session = Depends(get_db)):
    k = db.get(ApiKey, kid)
    if not k or k.institution_id != p.institution_id:
        raise HTTPException(404)
    k.revoked = True
    audit.record(db, actor=p.label, role=p.role, action="API_KEY_REVOKE", resource=f"api_key:{k.id}")
    db.commit()
    return {"ok": True}


class HookIn(BaseModel):
    url: str | None = None
    event_types: list[str] | None = None


@router.get("/integration/webhooks")
def list_hooks(p: Principal = Depends(need("integration:manage")), db: Session = Depends(get_db)):
    out = []
    for h in db.execute(select(Webhook).where(Webhook.institution_id == p.institution_id)).scalars():
        ds = db.execute(select(WebhookDelivery).where(WebhookDelivery.webhook_id == h.id)
                        .order_by(WebhookDelivery.id.desc()).limit(15)).scalars().all()
        out.append({"id": h.id, "url": h.url, "event_types": h.event_types, "active": h.active,
                    "secret_hint": h.secret[:6] + "...",
                    "deliveries": [{"id": d.id, "event_id": d.event_id, "event_type": db.get(Event, d.event_id).type,
                                    "status": d.status, "attempts": d.attempts, "response_code": d.response_code,
                                    "last_error": d.last_error} for d in ds]})
    return {"webhooks": out, "event_types": WEBHOOK_EVENT_TYPES}


@router.post("/integration/webhooks")
def create_hook(body: HookIn, p: Principal = Depends(need("integration:manage")), db: Session = Depends(get_db)):
    url = body.url or f"{settings.public_base_url.rstrip('/')}/mock/erp/{p.institution_id}/webhook"
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must be http(s)")
    types = body.event_types or WEBHOOK_EVENT_TYPES
    h = Webhook(institution_id=p.institution_id, url=url, secret="whsec_" + secrets.token_urlsafe(24), event_types=types)
    db.add(h)
    db.flush()
    audit.record(db, actor=p.label, role=p.role, action="WEBHOOK_CREATE", resource=f"webhook:{h.id}", details={"url": url})
    db.commit()
    return {"id": h.id, "url": h.url, "secret": h.secret, "event_types": types,
            "note": "Verify X-Registry-Signature = 'sha256=' + HMAC_SHA256(secret, raw_body)."}


# ---------------------------------------------------------------- live events (SSE over the outbox)
def _visible(ev: Event, role: str, inst: int | None, person: int | None) -> bool:
    if role in ("AICTE_ADMIN", "REGULATOR"):
        return True
    if role in ("INSTITUTION_ADMIN", "DATA_OPERATOR", "ERP_CLIENT"):
        return inst in (ev.institution_id, ev.other_institution_id) and ev.type != "ANOMALY_RAISED"
    if role == "STUDENT":
        return ev.person_id == person
    return False


def _ev_out(ev: Event) -> dict:
    return {"id": ev.id, "type": ev.type, "institution_id": ev.institution_id, "payload": ev.payload,
            "actor": ev.actor, "at": ev.created_at.isoformat()}


def _fetch(after: int, role, inst, person, limit=200) -> list[dict]:
    db = SessionLocal()
    try:
        evs = db.execute(select(Event).where(Event.id > after).order_by(Event.id).limit(limit)).scalars().all()
        return [_ev_out(e) for e in evs if _visible(e, role, inst, person)] + ([{"_cursor": evs[-1].id}] if evs else [])
    finally:
        db.close()


@router.get("/events/recent")
def recent(p: Principal = Depends(current), db: Session = Depends(get_db), limit: int = 40, types: str | None = None):
    stmt = select(Event).order_by(Event.id.desc()).limit(2000)
    if p.institution_scoped:
        stmt = stmt.where(or_(Event.institution_id == p.institution_id, Event.other_institution_id == p.institution_id))
    if p.role == "STUDENT":
        stmt = stmt.where(Event.person_id == p.person_id)
    if types:
        stmt = stmt.where(Event.type.in_(types.split(",")))
    out = [_ev_out(e) for e in db.execute(stmt).scalars() if _visible(e, p.role, p.institution_id, p.person_id)]
    return out[:limit]


@router.get("/events/stream", summary="Server-Sent Events over the outbox (near-real-time, ~1 s)")
async def stream(request: Request, token: str | None = None):
    # Resolve auth with a short-lived session: a long-lived one would hold a DB transaction open.
    def auth():
        db = SessionLocal()
        try:
            pr = resolve_principal(db, request.headers.get("authorization"), request.headers.get("x-api-key"), token)
            return pr, db.execute(select(Event.id).order_by(Event.id.desc())).scalars().first() or 0
        finally:
            db.close()
    p, last = await asyncio.to_thread(auth)        # no DB work on the event loop
    if p is None:
        raise HTTPException(401)
    role, inst, person = p.role, p.institution_id, p.person_id

    async def gen():
        nonlocal last
        idle = 0
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                break
            rows = await asyncio.to_thread(_fetch, last, role, inst, person)
            for r in rows:
                if "_cursor" in r:
                    last = r["_cursor"]
                    continue
                yield f"id: {r['id']}\nevent: spine\ndata: {json.dumps(r)}\n\n"
            idle += 1
            if idle >= 15:
                idle = 0
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
