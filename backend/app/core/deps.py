"""Request dependencies: who is calling, and a database session scoped to them by Row Level Security."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import RlsContext, open_session
from app.core.errors import Unauthorized
from app.core.security import AccessClaims, decode_access_token
from app.db import models

STAFF_ROLES = ("officer", "admin", "auditor")
ALL_ROLES = ("citizen", "helper", "officer", "admin", "auditor")

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /v1/auth/login")


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. Everything here comes from the verified token and the session row."""

    user_id: UUID
    tenant_id: UUID
    role: str
    session_id: UUID | None = None
    person_id: UUID | None = None
    auth_kind: str = "user"  # user | api_key
    acting_for_person_id: UUID | None = None  # set when a helper acts for a person (verified server-side)

    def rls(self) -> RlsContext:
        return RlsContext(role=self.role, tenant_id=self.tenant_id, user_id=self.user_id, person_id=self.person_id)


def get_claims(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> AccessClaims:
    if credentials is None or not credentials.credentials:
        raise Unauthorized("Sign in to continue.", code="not_authenticated", headers={"WWW-Authenticate": "Bearer"})
    return decode_access_token(credentials.credentials)


def get_db(claims: AccessClaims = Depends(get_claims)) -> Iterator[Session]:
    """One session per request, carrying the caller's RLS context.

    Endpoints commit explicitly once their work is complete. Anything left uncommitted is rolled back
    here, so a failed request never leaves a partial write.
    """
    session = open_session(
        RlsContext(role=claims.role, tenant_id=claims.tenant_id, user_id=claims.user_id, person_id=claims.person_id)
    )
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def get_principal(
    request: Request, claims: AccessClaims = Depends(get_claims), db: Session = Depends(get_db)
) -> Principal:
    """A valid token is not enough: its session must still exist, be unrevoked, and match the token.

    This is what makes sign-out, revoke-all and tenant switching take effect on the very next request.
    """
    session_row = db.get(models.AuthSession, claims.session_id)
    now = datetime.now(UTC)
    if (
        session_row is None
        or session_row.revoked_at is not None
        or session_row.expires_at <= now
        or session_row.user_id != claims.user_id
        or session_row.tenant_id != claims.tenant_id
        or session_row.role != claims.role
    ):
        raise Unauthorized("Your sign-in has ended. Please sign in again.", code="session_ended")
    principal = Principal(
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        role=claims.role,
        session_id=claims.session_id,
        person_id=claims.person_id,
    )
    request.state.principal = principal
    return principal
