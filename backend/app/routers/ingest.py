from __future__ import annotations

import csv
import gzip
import io
import json

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.deps import Principal, assert_inst, need, scope_inst
from ..db import get_db
from ..ingestion.pipeline import ingest
from ..models import Institution, Program, Submission, ValidationIssue, utcnow
from ..validation.catalog import RULES
from ..validation.rows import ENUMS, FIELDS

router = APIRouter(prefix="/api/v1", tags=["ingestion"])
MAX_ROWS = 20000


def _inst_for(p: Principal, db: Session, institution_id: int | None) -> Institution:
    iid = p.institution_id if p.institution_scoped else institution_id
    if iid is None:
        raise HTTPException(400, "institution_id required")
    assert_inst(p, iid)
    inst = db.get(Institution, iid)
    if not inst:
        raise HTTPException(404, "institution not found")
    return inst


class BatchIn(BaseModel):
    records: list[dict]
    institution_id: int | None = None


@router.post("/enrollments/batch", summary="Bulk submit / update enrolments (ERP integration)")
async def batch(request: Request, p: Principal = Depends(need("enrollment:write")), db: Session = Depends(get_db),
                idempotency_key: str | None = Header(None), content_encoding: str | None = Header(None)):
    """JSON body `{"records": [...]}`. Send `X-API-Key` and an `Idempotency-Key` so retries are safe;
    `Content-Encoding: gzip` is accepted for low-bandwidth links."""
    raw = await request.body()
    if content_encoding == "gzip":
        raw = gzip.decompress(raw)
    try:
        body = BatchIn(**json.loads(raw))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"invalid body: {e}")
    if len(body.records) > MAX_ROWS:
        raise HTTPException(413, f"max {MAX_ROWS} records per batch")
    # Never touch the DB on the event loop: a blocking SQLite lock wait there freezes every request.
    def work():
        inst = _inst_for(p, db, body.institution_id)
        return ingest(db, inst, body.records, source="API", actor=p, idempotency_key=idempotency_key)
    return await run_in_threadpool(work)


@router.post("/enrollments/upload", summary="CSV upload")
async def upload(file: UploadFile = File(...), institution_id: int | None = None,
                 p: Principal = Depends(need("enrollment:write")), db: Session = Depends(get_db)):
    data = await file.read()
    if file.filename and file.filename.endswith(".gz"):
        data = gzip.decompress(data)
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [f for f in ("roll_no", "name", "dob", "program_code") if f not in headers]
    if missing:
        raise HTTPException(400, f"CSV is missing columns: {', '.join(missing)}. Download the template.")
    rows = [{(k or "").strip().lower(): v for k, v in r.items()} for r in reader]
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"max {MAX_ROWS} rows per file; split it")
    def work():
        inst = _inst_for(p, db, institution_id)
        return ingest(db, inst, rows, source="CSV", actor=p, filename=file.filename)
    return await run_in_threadpool(work)


@router.post("/enrollments", summary="Single enrolment (web form)")
def form(body: dict, p: Principal = Depends(need("enrollment:write")), db: Session = Depends(get_db)):
    inst = _inst_for(p, db, body.get("institution_id"))
    return ingest(db, inst, [body], source="FORM", actor=p)


@router.get("/templates/enrollments.csv", tags=["ingestion"])
def template():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(FIELDS)
    w.writerow(["2026CSE001", "", "Asha Ramesh", "2008-04-12", "F", "Ramesh K", "JEE2026-1234567", "BTECH-CSE",
                "2026-08-01", "1", "REGULAR", "MERIT", "GEN", "INDIAN"])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=enrollment_template.csv"})


@router.get("/meta/rules")
def rules():
    return {"rules": RULES, "enums": {k: sorted(v) for k, v in ENUMS.items()}, "fields": FIELDS}


@router.get("/submissions")
def submissions(p: Principal = Depends(need("enrollment:read")), db: Session = Depends(get_db),
                institution_id: int | None = None, limit: int = 30):
    stmt = scope_inst(p, select(Submission), Submission.institution_id).order_by(Submission.id.desc()).limit(limit)
    if institution_id and not p.institution_scoped:
        stmt = stmt.where(Submission.institution_id == institution_id)
    return [{"id": s.id, "source": s.source, "filename": s.filename, "actor": s.actor, "total": s.total,
             "accepted": s.accepted, "updated": s.updated, "rejected": s.rejected, "conflicts": s.conflicts,
             "warnings": s.warnings, "created_at": s.created_at.isoformat()} for s in db.execute(stmt).scalars()]


@router.get("/submissions/{sid}")
def submission(sid: int, p: Principal = Depends(need("enrollment:read")), db: Session = Depends(get_db)):
    s = db.get(Submission, sid)
    if not s:
        raise HTTPException(404)
    assert_inst(p, s.institution_id)
    return s.report


@router.get("/submissions/{sid}/errors.csv")
def submission_errors_csv(sid: int, p: Principal = Depends(need("enrollment:read")), db: Session = Depends(get_db)):
    s = db.get(Submission, sid)
    if not s:
        raise HTTPException(404)
    assert_inst(p, s.institution_id)
    issues = db.execute(select(ValidationIssue).where(ValidationIssue.submission_id == sid,
                                                      ValidationIssue.severity == "ERROR")
                        .order_by(ValidationIssue.row_number)).scalars().all()
    by_row: dict[int, dict] = {}
    for i in issues:
        r = by_row.setdefault(i.row_number, {**(i.row_data or {}), "_row": i.row_number, "_errors": []})
        r["_errors"].append(f"{i.rule_code}: {i.message}")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["_row", "_errors", *FIELDS])
    for r in by_row.values():
        w.writerow([r["_row"], " | ".join(r["_errors"]), *[r.get(f, "") for f in FIELDS]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=submission_{sid}_errors.csv"})


@router.get("/issues")
def issues(p: Principal = Depends(need("issue:read")), db: Session = Depends(get_db), status: str = "OPEN",
           severity: str | None = None, institution_id: int | None = None, limit: int = 300):
    stmt = scope_inst(p, select(ValidationIssue), ValidationIssue.institution_id).where(ValidationIssue.status == status)
    if severity:
        stmt = stmt.where(ValidationIssue.severity == severity)
    if institution_id and not p.institution_scoped:
        stmt = stmt.where(ValidationIssue.institution_id == institution_id)
    rows = db.execute(stmt.order_by(ValidationIssue.id.desc()).limit(limit)).scalars().all()
    summary = dict(db.execute(scope_inst(p, select(ValidationIssue.severity, func.count()), ValidationIssue.institution_id)
                              .where(ValidationIssue.status == "OPEN").group_by(ValidationIssue.severity)).all())
    return {"summary": summary, "issues": [{
        "id": i.id, "submission_id": i.submission_id, "enrollment_id": i.enrollment_id, "row_number": i.row_number,
        "rule_code": i.rule_code, "rule_title": RULES.get(i.rule_code, {}).get("title"), "severity": i.severity,
        "field": i.field, "message": i.message, "hint": i.hint, "row_data": i.row_data, "status": i.status,
        "institution_id": i.institution_id, "created_at": i.created_at.isoformat()} for i in rows]}


class FixIn(BaseModel):
    row: dict


@router.post("/issues/{iid}/fix", summary="Fix a quarantined row in place and resubmit it")
def fix(iid: int, body: FixIn, p: Principal = Depends(need("issue:fix")), db: Session = Depends(get_db)):
    issue = db.get(ValidationIssue, iid)
    if not issue or issue.severity != "ERROR" or issue.row_data is None:
        raise HTTPException(404, "no quarantined row for this issue")
    assert_inst(p, issue.institution_id)
    if issue.status != "OPEN":
        raise HTTPException(409, "already resolved")
    siblings = db.execute(select(ValidationIssue).where(ValidationIssue.submission_id == issue.submission_id,
                                                        ValidationIssue.row_number == issue.row_number,
                                                        ValidationIssue.status == "OPEN")).scalars().all()
    for s in siblings:          # superseded by the resubmission (its new findings, if any, are new issues)
        s.status, s.resolved_at = "RESOLVED", utcnow()
    inst = db.get(Institution, issue.institution_id)
    report = ingest(db, inst, [body.row], source="FIX", actor=p)
    return report


@router.post("/issues/{iid}/acknowledge")
def acknowledge(iid: int, p: Principal = Depends(need("issue:fix")), db: Session = Depends(get_db)):
    issue = db.get(ValidationIssue, iid)
    if not issue or issue.severity == "ERROR":
        raise HTTPException(400, "only warnings can be acknowledged; errors must be fixed")
    assert_inst(p, issue.institution_id)
    issue.status, issue.resolved_at = "RESOLVED", utcnow()
    db.commit()
    return {"ok": True}


@router.get("/institutions/{iid}/programs/list")
def program_codes(iid: int, p: Principal = Depends(need("institution:read")), db: Session = Depends(get_db)):
    assert_inst(p, iid)
    return [{"id": x.id, "code": x.code, "name": x.name, "level": x.level}
            for x in db.execute(select(Program).where(Program.institution_id == iid).order_by(Program.code)).scalars()]
