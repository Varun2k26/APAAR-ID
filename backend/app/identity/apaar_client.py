"""Client for the APAAR registry: TTL cache + circuit breaker.

If the registry is slow or down, callers get `RegistryUnavailable` immediately (breaker open)
instead of hanging; ingestion then accepts the record as PENDING verification and a
background job re-checks it later. Institutions are never blocked by an outage.
"""
from __future__ import annotations

import threading
import time

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..mocks import registry as mock_registry
from ..mocks.registry import RegistryUnavailable

__all__ = ["lookup", "breaker_state", "RegistryUnavailable", "reset"]

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict | None]] = {}
_CACHE_TTL = 3600
_state = {"failures": 0, "opened_at": 0.0}


def breaker_state() -> dict:
    with _lock:
        open_ = _state["failures"] >= settings.breaker_failures and \
            time.time() - _state["opened_at"] < settings.breaker_cooldown_s
        return {"open": open_, "consecutive_failures": _state["failures"],
                "cooldown_s": settings.breaker_cooldown_s, "cached_ids": len(_cache)}


def reset() -> None:
    with _lock:
        _cache.clear()
        _state.update(failures=0, opened_at=0.0)


def _remote(apaar_id: str) -> dict | None:
    r = httpx.get(f"{settings.apaar_registry_url}/v1/students/{apaar_id}", timeout=3.0)
    if r.status_code == 404:
        return None
    if r.status_code >= 500:
        raise RegistryUnavailable(f"registry HTTP {r.status_code}")
    r.raise_for_status()
    return r.json()


def lookup(db: Session, apaar_id: str) -> dict | None:
    now = time.time()
    with _lock:
        hit = _cache.get(apaar_id)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
        if _state["failures"] >= settings.breaker_failures and now - _state["opened_at"] < settings.breaker_cooldown_s:
            raise RegistryUnavailable("circuit breaker open: registry recently failing")
    try:
        result = _remote(apaar_id) if settings.apaar_registry_url else mock_registry.lookup(db, apaar_id)
    except (RegistryUnavailable, httpx.HTTPError) as e:
        with _lock:
            _state["failures"] += 1
            if _state["failures"] >= settings.breaker_failures:
                _state["opened_at"] = time.time()
        raise RegistryUnavailable(str(e)) from e
    with _lock:
        _state["failures"] = 0
        if result is not None:          # do not cache negatives: a just-issued APAAR must resolve
            _cache[apaar_id] = (time.time(), result)
    return result
