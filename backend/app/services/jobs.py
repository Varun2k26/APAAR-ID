"""Background jobs: registry re-verification, webhook delivery, anomaly re-runs."""
from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import func, select

from ..analytics import counts
from ..db import SessionLocal
from ..identity import resolver
from ..models import Enrollment, Event, JobState, Person, ValidationIssue, utcnow
from . import audit, events, webhooks

log = logging.getLogger("jobs")


def reverify_pending() -> dict:
    """Retry registry checks for records accepted while the registry was down."""
    db = SessionLocal()
    done = {"verified": 0, "failed": 0, "still_pending": 0}
    try:
        pending = db.execute(select(Person).where(Person.registry_status == "PENDING", Person.apaar_id.is_not(None))
                             .limit(200)).scalars().all()
        for p in pending:
            status, _rec, f = resolver.registry_check(db, p.apaar_id, {"name": p.name, "dob": p.dob})
            if status == "PENDING":
                done["still_pending"] += 1
                break                       # breaker is open; try again next tick
            ens = db.execute(select(Enrollment).where(Enrollment.person_id == p.id)).scalars().all()
            for e in ens:
                counts.apply(db, e, p, -1)
            db.flush()
            # the "verification pending" warning is settled either way
            for iss in db.execute(select(ValidationIssue).where(
                    ValidationIssue.enrollment_id.in_([e.id for e in ens]), ValidationIssue.rule_code == "R43",
                    ValidationIssue.status == "OPEN")).scalars():
                iss.status, iss.resolved_at = "RESOLVED", utcnow()
            if status == "VERIFIED":
                p.registry_status, p.registry_checked_at = "VERIFIED", utcnow()
                done["verified"] += 1
            else:
                p.registry_status = "FAILED"
                done["failed"] += 1
                for e in ens:
                    db.add(ValidationIssue(institution_id=e.institution_id, enrollment_id=e.id, rule_code=f[0].code,
                                           severity="ERROR", field="apaar_id", message=f"Deferred registry check failed: "
                                           f"{f[0].message}", hint=f[0].hint))
                    events.emit(db, "ISSUE_RAISED", institution_id=e.institution_id, enrollment_id=e.id,
                                person_id=p.id, payload={"codes": [f[0].code], "roll_no": e.roll_no, "deferred": True})
            db.flush()
            for e in ens:
                counts.apply(db, e, p, +1)
            audit.record(db, actor="system:registry-retry", role="SYSTEM", action="REGISTRY_RECHECK",
                         resource=f"person:{p.id}", subject_person_id=p.id, details={"result": status})
            db.commit()
    finally:
        db.close()
    return done


def anomaly_rerun_if_changed() -> dict | None:
    from ..anomaly import engine
    db = SessionLocal()
    try:
        last = db.execute(select(func.max(Event.id)).where(Event.type.in_(
            ("ENROLLMENT_CREATED", "ENROLLMENT_UPDATED", "STATUS_CHANGED", "CONFLICT_OPENED", "CATEGORY_CHANGED",
             "APAAR_LINKED", "TRANSFER_COMPLETED")))).scalar() or 0
        js = db.get(JobState, "anomaly_cursor")
        if js and int(js.value) >= last:
            return None
        result = engine.run(db)
        js = db.get(JobState, "anomaly_cursor") or JobState(name="anomaly_cursor", value="0")
        js.value = str(last)
        db.add(js)
        db.commit()
        return result
    finally:
        db.close()


def webhook_tick(client: httpx.Client) -> None:
    db = SessionLocal()
    try:
        webhooks.enqueue(db)
        webhooks.deliver_due(db, client)
    finally:
        db.close()


async def loop(stop: asyncio.Event) -> None:
    client = httpx.Client()
    tick = 0
    try:
        while not stop.is_set():
            try:
                await asyncio.to_thread(webhook_tick, client)
                if tick % 7 == 0:
                    await asyncio.to_thread(reverify_pending)
                if tick % 15 == 0:
                    r = await asyncio.to_thread(anomaly_rerun_if_changed)
                    if r:
                        log.info("anomaly re-run: %s", r)
            except Exception:  # noqa: BLE001 - a failing job must not kill the loop
                log.exception("background job failed")
            tick += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass
    finally:
        client.close()
