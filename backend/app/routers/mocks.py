"""SIMULATED external systems: APAAR registry, AICTE approval feed, an institution ERP that
receives webhooks. Each has the request/response shape the real system would have."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Principal, need
from ..db import get_db
from ..identity import apaar_client
from ..mocks import registry
from ..models import ApprovedIntake, Institution, MockWebhookReceipt, Program, Webhook
from ..services import webhooks

router = APIRouter(prefix="/mock", tags=["simulated"])


@router.get("/apaar/v1/students/{apaar_id}")
def registry_lookup(apaar_id: str, db: Session = Depends(get_db)):
    try:
        r = registry.lookup(db, apaar_id)
    except registry.RegistryUnavailable:
        raise HTTPException(503, "registry unavailable")
    if not r:
        raise HTTPException(404, "not found")
    return r


class RegistryControlIn(BaseModel):
    latency_ms: int = 0
    fail_rate: float = 0.0
    down: bool = False


@router.get("/apaar/control")
def registry_control_get():
    return {**registry.control.__dict__, "client_breaker": apaar_client.breaker_state()}


@router.post("/apaar/control")
def registry_control_set(body: RegistryControlIn, p: Principal = Depends(need("approvals:manage"))):
    registry.control.latency_ms, registry.control.fail_rate, registry.control.down = body.latency_ms, body.fail_rate, body.down
    if not body.down:
        apaar_client.reset()
    return registry_control_get()


@router.get("/aicte/approvals")
def approval_feed(year: int, db: Session = Depends(get_db)):
    """SIMULATED AICTE approval-process feed (the existing portal is the source of truth)."""
    rows = db.execute(select(ApprovedIntake, Program, Institution).join(Program, Program.id == ApprovedIntake.program_id)
                      .join(Institution, Institution.id == Program.institution_id)
                      .where(ApprovedIntake.year == year)).all()
    return {"year": year, "approvals": [{"aicte_code": i.aicte_code, "program_code": p.code, "approved_intake": a.approved}
                                        for a, p, i in rows]}


@router.post("/erp/{institution_id}/webhook")
async def erp_receiver(institution_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    sig, etype = request.headers.get("X-Registry-Signature"), request.headers.get("X-Registry-Event", "?")

    def work() -> bool:
        import json
        hooks = db.execute(select(Webhook).where(Webhook.institution_id == institution_id)).scalars().all()
        ok = any(webhooks.verify_signature(h.secret, body, sig) for h in hooks)
        try:
            data = json.loads(body)
        except ValueError:
            data = {"raw": body.decode(errors="replace")[:500]}
        db.add(MockWebhookReceipt(institution_id=institution_id, event_type=etype, signature_valid=ok, body=data))
        db.commit()
        return ok
    valid = await run_in_threadpool(work)
    if not valid:
        raise HTTPException(401, "bad signature")
    return {"received": True}


@router.get("/erp/{institution_id}/received")
def erp_received(institution_id: int, db: Session = Depends(get_db)):
    rows = db.execute(select(MockWebhookReceipt).where(MockWebhookReceipt.institution_id == institution_id)
                      .order_by(MockWebhookReceipt.id.desc()).limit(50)).scalars()
    return [{"id": r.id, "event_type": r.event_type, "signature_valid": r.signature_valid, "body": r.body,
             "received_at": r.received_at.isoformat()} for r in rows]
