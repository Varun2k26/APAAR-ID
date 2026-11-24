"""Runtime configuration. Everything policy-like lives here so it can be tuned without code changes."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root
DATA_DIR = Path(os.environ.get("APAAR_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret() -> str:
    env = os.environ.get("JWT_SECRET")
    if env:
        return env
    f = DATA_DIR / ".jwt_secret"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48))
    return f.read_text().strip()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'apaar.db'}")
    jwt_secret: str = field(default_factory=_secret)
    jwt_ttl_hours: int = 12
    # Base URL printed into QR codes / certificates. Set to a LAN IP to scan from a phone.
    public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    demo_mode: bool = os.environ.get("DEMO_MODE", "1") == "1"
    run_background_jobs: bool = os.environ.get("BACKGROUND_JOBS", "1") == "1"

    # ---- academic calendar for the current admission cycle --------------------------
    current_year: int = 2026                      # academic year 2026-27 (admission cohort)
    admission_open: date = date(2026, 6, 15)
    admission_cutoff: date = date(2026, 11, 30)   # last date of admission (AICTE calendar)
    census_date: date = date(2026, 12, 15)        # intake checks become binding; snapshot frozen
    late_report_days: int = 45                    # reported this long after admission = late
    provisional_link_days: int = 90               # deadline to link an APAAR to a provisional ID

    # ---- supernumerary / quota caps, as a fraction of approved intake ---------------
    # Values follow the AICTE Approval Process Handbook pattern; confirm against the
    # current edition before relying on them. Configurable on purpose.
    caps: dict = field(default_factory=lambda: {
        "TFW": 0.05,        # Tuition Fee Waiver, supernumerary
        "FOREIGN": 0.15,    # Foreign Nationals / OCI / PIO / Children of Indian Workers in Gulf, supernumerary
        "LATERAL": 0.10,    # Lateral entry into 2nd year (diploma holders), supernumerary
        "NRI": 0.15,        # NRI quota, *within* sanctioned intake
    })

    # ---- concurrent-enrolment policy (UGC 2022 dual-programme guidelines) -------------
    # (existing_mode, new_mode) -> CONFLICT | ALLOWED
    dual_policy: dict = field(default_factory=lambda: {
        ("REGULAR", "REGULAR"): "CONFLICT",
        ("REGULAR", "ODL"): "ALLOWED",
        ("REGULAR", "ONLINE"): "ALLOWED",
        ("ODL", "REGULAR"): "ALLOWED",
        ("ONLINE", "REGULAR"): "ALLOWED",
        ("ODL", "ODL"): "ALLOWED",
        ("ODL", "ONLINE"): "ALLOWED",
        ("ONLINE", "ODL"): "ALLOWED",
        ("ONLINE", "ONLINE"): "ALLOWED",
    })

    # ---- identity matching thresholds ------------------------------------------------
    registry_name_threshold: float = 0.85   # submitted name vs registry name
    fuzzy_dup_threshold: float = 0.88       # cross-institution suspected duplicate
    provisional_share_flag: float = 0.15    # institution provisional share that is flagged

    # ---- APAAR registry client ---------------------------------------------------------
    apaar_registry_url: str | None = os.environ.get("APAAR_REGISTRY_URL")  # None -> in-process mock
    breaker_failures: int = 3
    breaker_cooldown_s: int = 30


settings = Settings()
