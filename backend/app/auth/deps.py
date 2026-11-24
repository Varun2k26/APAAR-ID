"""Principal resolution, the permission matrix and row scoping.

Every endpoint declares the permission it needs via `need("perm")`. Every query over
institution-owned rows goes through `scope_inst()` / `assert_inst()`, so an endpoint cannot
'forget' to scope: institution users and ERP keys only ever see their own institution.
"""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ApiKey, User, utcnow
from .security import hash_api_key, read_token

ROLES = ["AICTE_ADMIN", "INSTITUTION_ADMIN", "DATA_OPERATOR", "UNIVERSITY_REGISTRAR",
         "REGULATOR", "STUDENT", "ERP_CLIENT"]

PERMISSIONS: dict[str, set[str]] = {
    "AICTE_ADMIN": {"national:read", "institution:read", "enrollment:read", "record:read", "anomaly:manage",
                    "conflict:resolve", "conflict:read", "audit:read", "approvals:manage", "census:manage",
                    "issue:read", "credential:revoke", "transfer:read"},
    "INSTITUTION_ADMIN": {"institution:read", "enrollment:read", "enrollment:write", "issue:read", "issue:fix",
                          "conflict:read", "conflict:evidence", "integration:manage", "consent:request",
                          "record:read", "transfer:manage", "correction:decide", "credential:revoke"},
    "DATA_OPERATOR": {"institution:read", "enrollment:read", "enrollment:write", "issue:read", "issue:fix",
                      "conflict:read"},
    "UNIVERSITY_REGISTRAR": {"degree:issue", "degree:read", "credential:revoke"},
    "REGULATOR": {"national:read", "audit:query", "audit:read", "institution:read"},
    "STUDENT": {"self:read", "consent:decide", "credential:self", "conflict:confirm", "correction:request"},
    "ERP_CLIENT": {"enrollment:read", "enrollment:write", "institution:read", "issue:read"},
}

INSTITUTION_SCOPED = {"INSTITUTION_ADMIN", "DATA_OPERATOR", "ERP_CLIENT"}


@dataclass
class Principal:
    role: str
    label: str                       # human-readable actor for audit ("admin@AIC-TN-0001")
    user_id: int | None = None
    institution_id: int | None = None
    university_id: int | None = None
    person_id: int | None = None
    regulator_body: str | None = None
    api_key_id: int | None = None

    def can(self, perm: str) -> bool:
        return perm in PERMISSIONS.get(self.role, set())

    @property
    def institution_scoped(self) -> bool:
        return self.role in INSTITUTION_SCOPED


def _principal_from_user(u: User) -> Principal:
    return Principal(role=u.role, label=u.username, user_id=u.id, institution_id=u.institution_id,
                     university_id=u.university_id, person_id=u.person_id, regulator_body=u.regulator_body)


def resolve_principal(db: Session, authorization: str | None, api_key: str | None,
                      token_q: str | None = None) -> Principal | None:
    if api_key:
        k = db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(api_key),
                                            ApiKey.revoked.is_(False))).scalar_one_or_none()
        if not k:
            raise HTTPException(401, "invalid API key")
        k.last_used_at = utcnow()
        return Principal(role="ERP_CLIENT", label=f"api-key:{k.prefix}", institution_id=k.institution_id,
                         api_key_id=k.id)
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    elif token_q:
        token = token_q
    if not token:
        return None
    try:
        data = read_token(token)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")
    u = db.get(User, int(data["sub"]))
    if not u:
        raise HTTPException(401, "user no longer exists")
    return _principal_from_user(u)


def current(db: Session = Depends(get_db), authorization: str | None = Header(None),
            x_api_key: str | None = Header(None), token: str | None = Query(None, include_in_schema=False)) -> Principal:
    p = resolve_principal(db, authorization, x_api_key, token)
    if p is None:
        raise HTTPException(401, "authentication required")
    return p


def optional_principal(db: Session = Depends(get_db), authorization: str | None = Header(None),
                       x_api_key: str | None = Header(None)) -> Principal | None:
    try:
        return resolve_principal(db, authorization, x_api_key)
    except HTTPException:
        return None


def need(*perms: str):
    def dep(p: Principal = Depends(current)) -> Principal:
        if not any(p.can(x) for x in perms):
            raise HTTPException(403, f"role {p.role} lacks permission: {' or '.join(perms)}")
        return p
    return dep


def assert_inst(p: Principal, institution_id: int | None) -> None:
    """Raise 403 if an institution-scoped principal touches another institution's row."""
    if p.institution_scoped and institution_id != p.institution_id:
        raise HTTPException(403, "outside your institution's scope")


def scope_inst(p: Principal, stmt, column):
    """Add the institution filter to a query when the principal is institution-scoped."""
    if p.institution_scoped:
        return stmt.where(column == p.institution_id)
    return stmt
