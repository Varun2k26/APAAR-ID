"""SIMULATED APAAR registry. Same request/response shape a real registry API would have:
GET /mock/apaar/v1/students/{apaar_id} -> {apaar_id, name, dob, gender, status}.
Latency, failure rate and full outage can be toggled to demo graceful degradation."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import MockRegistryRecord


@dataclass
class RegistryControl:
    latency_ms: int = 0
    fail_rate: float = 0.0
    down: bool = False


control = RegistryControl()


class RegistryUnavailable(Exception):
    pass


def lookup(db: Session, apaar_id: str) -> dict | None:
    if control.down or (control.fail_rate and random.random() < control.fail_rate):
        raise RegistryUnavailable("APAAR registry did not respond")
    if control.latency_ms:
        time.sleep(control.latency_ms / 1000)
    r = db.get(MockRegistryRecord, apaar_id)
    if r is None:
        return None
    return {"apaar_id": r.apaar_id, "name": r.name, "dob": r.dob.isoformat(), "gender": r.gender,
            "status": r.status}
