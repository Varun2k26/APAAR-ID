from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Principal, current, need
from ..credentials import certificate, keys, service, status_list
from ..db import get_db
from ..identity.apaar_format import mask
from ..models import Credential, Enrollment, Institution, Person, StatusList, University
from ..services import audit, events

router = APIRouter(prefix="/api/v1", tags=["credentials"])


def cred_out(c: Credential, include_token: bool) -> dict:
    d = {"id": c.id, "type": c.type, "enrollment_id": c.enrollment_id, "issuer_kid": c.issuer_kid,
         "issued_at": c.issued_at.isoformat(), "revoked": bool(c.revoked_at),
         "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None, "revocation_reason": c.revocation_reason,
         "claims": c.claims, "default_reveal": service.DEFAULT_REVEAL[c.type], "sensitive": sorted(service.SENSITIVE)}
    if include_token:
        d["sd_jwt"] = c.sd_jwt
    return d


# ---------------------------------------------------------------- public trust infrastructure
@router.get("/trust/root", tags=["public"])
def trust_root(db: Session = Depends(get_db)):
    info = keys.root_info(db)
    db.commit()
    return info


@router.get("/trust/list", tags=["public"])
def trust_list(db: Session = Depends(get_db)):
    out = keys.trust_list(db)
    db.commit()
    return out


@router.get("/status-lists/{sid}", tags=["public"])
def get_status_list(sid: int, db: Session = Depends(get_db)):
    sl = db.get(StatusList, sid)
    if not sl:
        raise HTTPException(404)
    return Response(status_list.status_credential(db, sl), media_type="application/statuslist+jwt",
                    headers={"Cache-Control": "public, max-age=60", "Access-Control-Allow-Origin": "*"})


class VerifyIn(BaseModel):
    presentation: str
    verifier: str | None = None


@router.post("/verify", tags=["public"], summary="Online verification for HR/ERP integrations (logged)")
def verify_online(body: VerifyIn, db: Session = Depends(get_db)):
    """The browser verifier works offline and tells nobody. This endpoint is for systems that
    want a server answer; because it runs here, it is logged and the student can see it."""
    res = service.verify(db, body.presentation)
    cid = res.get("credential_id")
    c = db.get(Credential, cid) if cid else None
    if c:
        audit.record(db, actor=f"verifier:{(body.verifier or 'anonymous')[:60]}", role="VERIFIER", action="VERIFY_ONLINE",
                     resource=f"credential:{c.id}", subject_person_id=c.person_id, purpose="credential verification",
                     details={"valid": res["valid"], "fields_disclosed": sorted(res.get("claims", {}))})
        db.commit()
    return res


# ---------------------------------------------------------------- student wallet
@router.get("/me/credentials")
def my_credentials(p: Principal = Depends(need("credential:self")), db: Session = Depends(get_db)):
    rows = db.execute(select(Credential).where(Credential.person_id == p.person_id).order_by(Credential.issued_at.desc())).scalars()
    return [cred_out(c, True) for c in rows]


class IssueIn(BaseModel):
    enrollment_id: int


@router.post("/me/credentials", summary="Student asks their institution to issue an enrolment credential")
def issue_mine(body: IssueIn, p: Principal = Depends(need("credential:self")), db: Session = Depends(get_db)):
    e = db.get(Enrollment, body.enrollment_id)
    if not e or e.person_id != p.person_id:
        raise HTTPException(404, "enrolment not found")
    try:
        c = service.issue_enrollment(db, e)
    except ValueError as ex:
        raise HTTPException(409, str(ex))
    events.emit(db, "CREDENTIAL_ISSUED", institution_id=e.institution_id, person_id=e.person_id, enrollment_id=e.id,
                payload={"type": "ENROLLMENT"}, actor=p.label)
    audit.record(db, actor=p.label, role=p.role, action="CREDENTIAL_ISSUE", resource=f"credential:{c.id}",
                 subject_person_id=e.person_id, details={"type": "ENROLLMENT", "issuer": c.issuer_kid})
    db.commit()
    return cred_out(c, True)


# ---------------------------------------------------------------- issuer-side revocation
class RevokeIn(BaseModel):
    reason: str


@router.post("/credentials/{cid:path}/revoke")
def revoke(cid: str, body: RevokeIn, p: Principal = Depends(need("credential:revoke")), db: Session = Depends(get_db)):
    c = db.get(Credential, cid)
    if not c:
        raise HTTPException(404)
    e = db.get(Enrollment, c.enrollment_id)
    if p.institution_scoped and (c.type != "ENROLLMENT" or e.institution_id != p.institution_id):
        raise HTTPException(403, "you can only revoke credentials your institution issued")
    if p.role == "UNIVERSITY_REGISTRAR" and (c.type != "DEGREE" or e.institution.university_id != p.university_id):
        raise HTTPException(403, "you can only revoke degrees your university issued")
    service.revoke(db, c, body.reason)
    audit.record(db, actor=p.label, role=p.role, action="CREDENTIAL_REVOKE", resource=f"credential:{c.id}",
                 subject_person_id=c.person_id, details={"reason": body.reason})
    db.commit()
    return cred_out(c, False)


# ---------------------------------------------------------------- university: degrees
@router.get("/university/graduates")
def graduates(p: Principal = Depends(need("degree:read")), db: Session = Depends(get_db)):
    rows = db.execute(select(Enrollment, Person, Institution).join(Person, Person.id == Enrollment.person_id)
                      .join(Institution, Institution.id == Enrollment.institution_id)
                      .where(Institution.university_id == p.university_id, Enrollment.status == "GRADUATED")
                      .order_by(Institution.name, Enrollment.roll_no)).all()
    degrees = {c.enrollment_id: c for c in db.execute(select(Credential).where(Credential.type == "DEGREE")).scalars()}
    out = []
    for e, pe, i in rows:
        c = degrees.get(e.id)
        out.append({"enrollment_id": e.id, "name": pe.name, "apaar": mask(pe.apaar_id), "institution": i.name,
                    "program": e.program.name, "roll_no": e.roll_no, "admission_year": e.academic_year,
                    "degree": cred_out(c, False) if c else None})
    audit.record(db, actor=p.label, role=p.role, action="ENROLLMENT_LIST", resource="university:graduates",
                 details={"rows": len(out)})
    db.commit()
    return out


class DegreeIn(BaseModel):
    enrollment_id: int
    class_awarded: str = "First Class"
    cgpa: float | None = None


@router.post("/university/degrees")
def issue_degree(body: DegreeIn, p: Principal = Depends(need("degree:issue")), db: Session = Depends(get_db)):
    e = db.get(Enrollment, body.enrollment_id)
    if not e or e.institution.university_id != p.university_id:
        raise HTTPException(404, "not a graduate of your affiliated institutions")
    uni = db.get(University, p.university_id)
    try:
        c = service.issue_degree(db, e, uni, body.class_awarded, body.cgpa)
    except ValueError as ex:
        raise HTTPException(409, str(ex))
    events.emit(db, "CREDENTIAL_ISSUED", institution_id=e.institution_id, person_id=e.person_id, enrollment_id=e.id,
                payload={"type": "DEGREE"}, actor=p.label)
    audit.record(db, actor=p.label, role=p.role, action="DEGREE_ISSUE", resource=f"credential:{c.id}",
                 subject_person_id=e.person_id, details={"class": body.class_awarded})
    db.commit()
    return cred_out(c, False)


@router.get("/credentials/{cid:path}/certificate.pdf")
def certificate_pdf(cid: str, p: Principal = Depends(current), db: Session = Depends(get_db)):
    c = db.get(Credential, cid)
    if not c or c.type != "DEGREE":
        raise HTTPException(404)
    e = db.get(Enrollment, c.enrollment_id)
    allowed = (p.role == "STUDENT" and p.person_id == c.person_id) or \
              (p.role == "UNIVERSITY_REGISTRAR" and e.institution.university_id == p.university_id)
    if not allowed:
        raise HTTPException(403)
    pdf = certificate.render(c)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="degree-{c.id[-8:]}.pdf"'})
