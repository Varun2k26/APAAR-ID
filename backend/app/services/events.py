"""Outbox writer. Call inside the same transaction as the change."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Event

# Event types that institutions may subscribe to via webhooks.
WEBHOOK_EVENT_TYPES = [
    "ISSUE_RAISED", "CONFLICT_OPENED", "CONFLICT_RESOLVED", "CONSENT_REQUESTED",
    "CONSENT_DECIDED", "TRANSFER_REQUESTED", "TRANSFER_COMPLETED", "SUBMISSION_PROCESSED",
    "CORRECTION_REQUESTED", "INTAKE_ALERT",
]


def emit(db: Session, type_: str, *, institution_id: int | None = None, other_institution_id: int | None = None,
         person_id: int | None = None, enrollment_id: int | None = None, payload: dict | None = None,
         actor: str = "system") -> Event:
    ev = Event(type=type_, institution_id=institution_id, other_institution_id=other_institution_id,
               person_id=person_id, enrollment_id=enrollment_id, payload=payload or {}, actor=actor)
    db.add(ev)
    return ev
