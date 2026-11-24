# APAAR Registry

A student-level national enrolment data layer for AICTE, keyed on the APAAR ID. Institutions report
each student once, by API, CSV or web form. Every row is validated as it arrives, checked against
every other institution, counted in real time, and turned into a credential the student controls
and anyone can verify.

MVP built for the AICTE problem statement. **All data is synthetic.** The APAAR registry,
DigiLocker, the AICTE approval feed and an institution ERP are simulated with the request/response
shape the real systems would have.

## Run it

```bash
./dev.sh            # installs deps, seeds on first run, builds the web app, serves on :8000
./dev.sh --reset    # wipe and re-seed
```

Open http://localhost:8000. The sign-in page lists demo accounts. AICTE uses password + TOTP; in
demo mode the current code is shown on the page. Students sign in through the simulated
DigiLocker (OTP `123456`). API docs are at `/docs`.

Requirements: [uv](https://docs.astral.sh/uv/) and Node 18+. A Docker image is also provided
(`docker compose up --build`); it is written but was not built on the development machine.

To scan credential QRs from a phone, set `PUBLIC_BASE_URL=http://<your-LAN-ip>:8000` and open the
app at that address.

Tests: `cd backend && uv run pytest` (28 tests; they seed their own temporary database).

## How each sub-problem is handled

| # | Problem | What the MVP does | Where |
|---|---|---|---|
| 1 | Ingestion | REST batch API (API key, `Idempotency-Key`, gzip), CSV upload with in-browser pre-check, and a web form with a locally saved draft. All three use **one pipeline**. Each row runs in its own savepoint, so bad rows are quarantined with their raw data and fixed in place. Re-submissions become typed events (history is never overwritten). Lifecycle changes: drop / suspend / graduate / re-enrol. | `ingestion/pipeline.py`, `routers/ingest.py` |
| 2 | Identity | Verhoeff check digit (assumed; swappable), registry lookup with fuzzy name + exact DOB match (VERIFIED / MISMATCH / NOT_FOUND), TTL cache + circuit breaker. If the registry is down, the record is accepted as PENDING and re-checked by a background job. Students with no APAAR get a **provisional ID** tied to a demographic fingerprint and a link deadline; resubmitting with the APAAR merges the records. | `identity/` |
| 2b | Same APAAR, two colleges, same instant | A partial unique index allows only one ACTIVE regular enrolment per person, so exactly one insert wins inside the database. The other is stored as a CONFLICT, not rejected. **Arrival order decides nothing**: the student confirms, institutions attach evidence, AICTE adjudicates. | `models.py` (`uq_one_active_regular`), `routers/conflicts.py` |
| 3 | Validation & anomalies | A catalogue of 28 rules (`/api/v1/meta/rules`). The intake check understands supernumerary seats (TFW / FN-OCI-PIO / lateral each have their own cap), so a legal "76 on 60" is not flagged. The cross-institution duplicate rule depends on study mode (UGC 2022 dual-programme policy). Fuzzy duplicates use multi-pass blocking (DOB · exam roll · phonetic name + parent). The statistical layer: fill-rate jump (robust z vs own history and peers), category shift (JS divergence + chi-square), provisional share, and an Isolation Forest. **Every finding carries an explanation.** | `validation/`, `anomaly/` |
| 4 | Verification | Institutions (or universities, for degrees) sign SD-JWT credentials (W3C VC 2.0 vocabulary, Ed25519). The student picks which fields to reveal; category, DOB and marks are hidden by default. The QR link keeps the credential after `#`, so it never reaches a server. The browser verifies offline against a cached, AICTE-signed trust list and a Bitstring Status List (revocation). Other institutions get access through consent; regulators get pseudonymised bulk audit. | `credentials/`, `frontend/src/lib/verify.ts` |
| 5 | Dashboards | Counters are updated in the same transaction as each write. A transactional outbox feeds Server-Sent Events, so dashboards update within about a second. AICTE: national KPIs, state tile map, trend from aggregate returns to student-level data, live feed, anomaly triage, conflicts, drill-down. Institution: intake vs approval per programme, error queue, conflicts. | `analytics/counts.py`, `routers/integration.py` (SSE) |
| 6 | Security, consent, audit | Permission matrix + one row-scoping helper. Staff log in with password + TOTP; students via simulated DigiLocker OAuth. A hash-chained audit log covers every write, read and verification, and `/audit/verify` detects tampering. Consent is **enforced at read time**, and students see "who accessed my data" from the same log. Right to correction is included; Aadhaar is never stored. | `auth/`, `services/audit.py`, `services/records.py` |
| 7 | Interoperability & lifecycle | The web app uses only the public `/api/v1` (OpenAPI). HMAC-signed webhooks are sent from the outbox with retries. Approved intake is imported from the AICTE approval feed. Transfers are a two-sided handshake with an atomic hand-off. A university-signed degree credential produces a PDF with the APAAR and a QR. | `routers/`, `services/webhooks.py`, `services/lifecycle.py`, `credentials/certificate.py`, `tools/erp_client.py` |

## Seeded fraud scenarios

The seeded scenarios are pushed through the real pipeline, so the detections come from production code:

| Scenario | Caught by |
|---|---|
| Ghost-student college: 30% → 95% fill, half of the new students without APAAR, reported late | FILL_RATE_JUMP, PROVISIONAL_SHARE, MULTIVARIATE |
| 25 students enrolled at two colleges (same APAAR) + 8 re-submitted without APAAR under initial-first names | 25 EXACT conflicts + FUZZY conflicts |
| 13 TFW seats on a 60-seat programme (cap 3) | SUPERNUMERARY_EXCEEDED |
| 68 regular admissions on 60 approved | INTAKE_EXCEEDED |
| 3× fill jump with valid APAARs | FILL_RATE_JUMP |
| EWS share 8% → 50% | CATEGORY_SHIFT |
| Control: 60 regular + 3 TFW + 8 FN + 5 lateral = 76 on 60 | **not flagged** (legal) |

The Isolation Forest also flags one non-injected college for unusually high mid-year churn. That is
a genuine statistical outlier in the synthetic data, the kind an officer reviews and may dismiss.

## Simulated, assumed, or not built

- **Simulated:** APAAR registry, DigiLocker, AICTE approval feed, ERP webhook receiver.
- **Assumed:** a Verhoeff APAAR check digit (the real algorithm is not public); supernumerary cap
  values (configurable in `config.py`; confirm against the current AICTE Approval Process Handbook).
- **Not built:**
  - SD-JWT key binding: students hold no device keys, so the employer matches the disclosed name to a photo ID.
  - HSM-held issuer keys.
  - MeriPehchaan / DigiLocker partner onboarding.
  - A streaming warehouse (the outbox → Debezium/Kafka → ClickHouse path is the production scale-up).
- **Scope:** student-level data covers the current admission cohort; earlier years are the aggregate
  returns AICTE already has.
- **Database:** runs on SQLite (writers serialised with `BEGIN IMMEDIATE`). The code targets Postgres
  via `DATABASE_URL` (partial index and row locks included), but it has only been tested on SQLite.

See `docs/DEMO.md` for a step-by-step demo script.

## Browser walkthrough (E2E)

`tools/e2e` drives the full demo as real users in headless Chromium/Brave: uploads, fix-in-place,
the live conflict, the student's answer, adjudication, credential verify / tamper / offline /
revoke, consent, regulator, degree, audit chain and registry outage. Run it against a freshly reset
server (`./dev.sh --reset`):

```bash
cd tools/e2e && npm install && CHROME_PATH="/path/to/chrome" npm run e2e   # screenshots land in tools/e2e/shots
```
