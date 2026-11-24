"""ORM models. Read the docstrings: several tables carry a design decision."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
                        LargeBinary, String, Text, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------------------------------- reference data
class University(Base):
    __tablename__ = "universities"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(4))


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[int] = mapped_column(primary_key=True)
    aicte_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(4), index=True)
    district: Mapped[str] = mapped_column(String(80))
    inst_type: Mapped[str] = mapped_column(String(20))        # GOVT / AIDED / PRIVATE
    university_id: Mapped[int | None] = mapped_column(ForeignKey("universities.id"))
    programs: Mapped[list["Program"]] = relationship(back_populates="institution")


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))             # e.g. BTECH-CSE (unique per institution)
    name: Mapped[str] = mapped_column(String(160))
    discipline: Mapped[str] = mapped_column(String(60))       # AICTE discipline
    level: Mapped[str] = mapped_column(String(12))            # UG / PG / DIPLOMA / PGDM
    duration_years: Mapped[int] = mapped_column(Integer)
    institution: Mapped[Institution] = relationship(back_populates="programs")


class ApprovedIntake(Base):
    """Sanctioned intake per programme per academic year (imported from the AICTE approval feed)."""
    __tablename__ = "approved_intake"
    __table_args__ = (UniqueConstraint("program_id", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    approved: Mapped[int] = mapped_column(Integer)


class IntakeHistory(Base):
    """What AICTE has today for past years: aggregate counts only, no student identity."""
    __tablename__ = "intake_history"
    __table_args__ = (UniqueConstraint("program_id", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    admitted: Mapped[int] = mapped_column(Integer)
    categories: Mapped[dict] = mapped_column(JSON)            # {"GEN": n, "EWS": n, ...}


# ----------------------------------------------------------------------------- identity
class Person(Base):
    """One human. Keyed by APAAR when known; otherwise by a provisional ID bound to a
    demographic fingerprint so the 'no APAAR yet' path cannot hide a duplicate."""
    __tablename__ = "persons"
    id: Mapped[int] = mapped_column(primary_key=True)
    apaar_id: Mapped[str | None] = mapped_column(String(12), unique=True)
    provisional_id: Mapped[str | None] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    name_norm: Mapped[str] = mapped_column(String(160))
    name_key: Mapped[str] = mapped_column(String(160), index=True)      # phonetic key
    dob: Mapped[date] = mapped_column(Date, index=True)
    gender: Mapped[str] = mapped_column(String(1))
    parent_name: Mapped[str | None] = mapped_column(String(160))
    parent_key: Mapped[str | None] = mapped_column(String(160), index=True)
    exam_roll: Mapped[str | None] = mapped_column(String(40), index=True)
    # VERIFIED | PENDING (registry unreachable) | PROVISIONAL (no APAAR yet)
    registry_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    registry_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    link_deadline: Mapped[date | None] = mapped_column(Date)
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Enrollment(Base):
    """A person's enrolment in a programme. History is never overwritten: changes become
    rows in `events`. The partial unique index is the hard guarantee that one person has at
    most one ACTIVE regular enrolment, even when two colleges submit at the same instant."""
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("institution_id", "roll_no", name="uq_inst_roll"),
        Index("uq_one_active_regular", "person_id", unique=True,
              sqlite_where=text("status = 'ACTIVE' AND mode = 'REGULAR'"),
              postgresql_where=text("status = 'ACTIVE' AND mode = 'REGULAR'")),
        Index("ix_enr_inst_year_status", "institution_id", "academic_year", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    roll_no: Mapped[str] = mapped_column(String(40))
    academic_year: Mapped[int] = mapped_column(Integer)
    admission_date: Mapped[date] = mapped_column(Date)
    year_of_study: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(10), default="REGULAR")       # REGULAR / ODL / ONLINE
    seat_type: Mapped[str] = mapped_column(String(12))   # MERIT MANAGEMENT NRI | TFW FOREIGN LATERAL
    social_category: Mapped[str] = mapped_column(String(8))                # GEN EWS OBC-NCL SC ST
    nationality: Mapped[str] = mapped_column(String(18))  # INDIAN NRI OCI PIO FOREIGN_NATIONAL
    # ACTIVE | CONFLICT | TRANSFERRED_OUT | DROPPED | SUSPENDED | GRADUATED | VOID
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(8), default="FORM")         # API / CSV / FORM / SEED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    person: Mapped[Person] = relationship()
    program: Mapped[Program] = relationship()
    institution: Mapped[Institution] = relationship()


class ProgramCount(Base):
    """Incrementally maintained counters (updated in the same transaction as the write).
    Dashboards read these, so 'real-time' is cheap; recompute() rebuilds them from scratch."""
    __tablename__ = "program_counts"
    __table_args__ = (UniqueConstraint("program_id", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer, default=0)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)   # seat:*, cat:*, prov, late


# ----------------------------------------------------------------------------- ingestion
class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    source: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str | None] = mapped_column(String(200))
    actor: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    total: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    conflicts: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("institution_id", "idempotency_key", name="uq_idem"),)


class ValidationIssue(Base):
    """A rule finding. ERROR rows are quarantined here with their raw data so they can be
    fixed in place; WARN/INFO findings point at an accepted enrolment."""
    __tablename__ = "validation_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"))
    enrollment_id: Mapped[int | None] = mapped_column(ForeignKey("enrollments.id"))
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id"))
    row_number: Mapped[int | None] = mapped_column(Integer)
    rule_code: Mapped[str] = mapped_column(String(8))
    severity: Mapped[str] = mapped_column(String(6))           # ERROR / WARN / INFO
    field: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(Text)
    row_data: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")   # OPEN / RESOLVED / WAIVED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class Conflict(Base):
    """Two enrolments that claim the same person. Never decided by arrival order."""
    __tablename__ = "conflicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))               # EXACT (same APAAR) / FUZZY
    score: Mapped[float] = mapped_column(Float, default=1.0)
    enrollment_a_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"))   # existing
    enrollment_b_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"))   # new claim
    person_a_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    person_b_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    reasons: Mapped[list | None] = mapped_column(JSON)
    # OPEN -> STUDENT_CONFIRMED -> RESOLVED | DISMISSED
    status: Mapped[str] = mapped_column(String(18), default="OPEN")
    student_choice_enrollment_id: Mapped[int | None] = mapped_column(Integer)
    student_note: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list | None] = mapped_column(JSON)        # [{by, note, at}]
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    enrollment_a: Mapped[Enrollment] = relationship(foreign_keys=[enrollment_a_id])
    enrollment_b: Mapped[Enrollment] = relationship(foreign_keys=[enrollment_b_id])


class Transfer(Base):
    """Two-sided transfer handshake: destination requests (student consents), source releases.
    The release flips both enrolments in one transaction, so no false duplicate appears."""
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"))
    from_enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"))
    to_institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    to_program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"))
    to_roll_no: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    # PENDING_STUDENT -> PENDING_RELEASE -> COMPLETED | REJECTED
    status: Mapped[str] = mapped_column(String(18), default="PENDING_STUDENT")
    new_enrollment_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (UniqueConstraint("institution_id", "program_id", "kind", "year", name="uq_anom"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id"))
    year: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    # INTAKE_EXCEEDED, SUPERNUMERARY_EXCEEDED, NRI_QUOTA_EXCEEDED (rules, shown to institution)
    # FILL_RATE_JUMP, CATEGORY_SHIFT, PROVISIONAL_SHARE, MULTIVARIATE (statistical, AICTE only)
    source: Mapped[str] = mapped_column(String(10))            # RULE / STATISTICAL
    severity: Mapped[str] = mapped_column(String(8))           # HIGH / MEDIUM / LOW
    score: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(240))
    explanation: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(14), default="OPEN")  # OPEN INVESTIGATING CONFIRMED DISMISSED
    active: Mapped[bool] = mapped_column(Boolean, default=True)      # still detected on the last run
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CensusSnapshot(Base):
    __tablename__ = "census_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    frozen_by: Mapped[str] = mapped_column(String(120))
    data: Mapped[dict] = mapped_column(JSON)


# ----------------------------------------------------------------------------- events / audit
class Event(Base):
    """Transactional outbox. Written in the same transaction as the change it describes;
    the SSE relay and the webhook dispatcher read from here."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    institution_id: Mapped[int | None] = mapped_column(Integer, index=True)
    other_institution_id: Mapped[int | None] = mapped_column(Integer)
    person_id: Mapped[int | None] = mapped_column(Integer, index=True)
    enrollment_id: Mapped[int | None] = mapped_column(Integer, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Append-only, hash-chained. hash = sha256(prev_hash || canonical(entry)). Editing or
    deleting any row breaks every hash after it, which /audit/verify detects."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(120))
    actor_role: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(40), index=True)
    resource: Mapped[str] = mapped_column(String(80))
    subject_person_id: Mapped[int | None] = mapped_column(Integer, index=True)
    purpose: Mapped[str | None] = mapped_column(String(240))
    details: Mapped[dict | None] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AuditHead(Base):
    __tablename__ = "audit_head"
    id: Mapped[int] = mapped_column(primary_key=True)
    last_hash: Mapped[str] = mapped_column(String(64))


# ----------------------------------------------------------------------------- credentials
class IssuerKey(Base):
    """Ed25519 signing keys. Private keys sit in the DB for the MVP; production = HSM."""
    __tablename__ = "issuer_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    kid: Mapped[str] = mapped_column(String(64), unique=True)
    issuer_type: Mapped[str] = mapped_column(String(12))      # AICTE / INSTITUTION / UNIVERSITY
    issuer_ref: Mapped[int | None] = mapped_column(Integer)
    issuer_uri: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    public_key: Mapped[str] = mapped_column(String(64))       # base64url raw 32 bytes
    private_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StatusList(Base):
    __tablename__ = "status_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(12), default="revocation")
    bits: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer)
    used: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)     # urn:uuid
    type: Mapped[str] = mapped_column(String(24))                     # ENROLLMENT / DEGREE
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"), index=True)
    issuer_kid: Mapped[str] = mapped_column(String(64))
    status_list_id: Mapped[int] = mapped_column(ForeignKey("status_lists.id"))
    status_index: Mapped[int] = mapped_column(Integer)
    sd_jwt: Mapped[str] = mapped_column(Text)                         # issuer JWT + all disclosures
    claims: Mapped[dict] = mapped_column(JSON)                         # for the holder UI
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revocation_reason: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("status_list_id", "status_index"),)


# ----------------------------------------------------------------------------- consent
class ConsentRequest(Base):
    __tablename__ = "consent_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    requester_role: Mapped[str] = mapped_column(String(24))
    requester_institution_id: Mapped[int | None] = mapped_column(Integer)
    requester_label: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(240))
    fields: Mapped[list] = mapped_column(JSON)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(10), default="PENDING")  # PENDING APPROVED DENIED REVOKED
    transfer_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)


class CorrectionRequest(Base):
    __tablename__ = "correction_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"))
    institution_id: Mapped[int] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(40))
    current_value: Mapped[str | None] = mapped_column(String(200))
    requested_value: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")     # OPEN ACCEPTED REJECTED
    decided_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


# ----------------------------------------------------------------------------- accounts / integration
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(24))
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"))
    university_id: Mapped[int | None] = mapped_column(ForeignKey("universities.id"))
    regulator_body: Mapped[str | None] = mapped_column(String(16))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    url: Mapped[str] = mapped_column(String(400))
    secret: Mapped[str] = mapped_column(String(80))
    event_types: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("webhook_id", "event_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    webhook_id: Mapped[int] = mapped_column(ForeignKey("webhooks.id"), index=True)
    event_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="PENDING")   # PENDING DELIVERED FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)


class JobState(Base):
    """Cursor storage for background jobs (webhook dispatcher, anomaly re-runs)."""
    __tablename__ = "job_state"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


# ----------------------------------------------------------------------------- SIMULATED externals
class MockRegistryRecord(Base):
    """SIMULATED APAAR registry (the real one is not publicly accessible)."""
    __tablename__ = "mock_apaar_registry"
    apaar_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dob: Mapped[date] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String(1))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")


class MockWebhookReceipt(Base):
    """SIMULATED institution ERP that receives our webhooks, so deliveries are visible."""
    __tablename__ = "mock_erp_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    signature_valid: Mapped[bool] = mapped_column(Boolean)
    body: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
