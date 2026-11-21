"""Request dependencies: who is calling, and a database session scoped to them by Row Level Security.

A caller presents one credential:

* an access token from sign-in (`Authorization: Bearer eyJ...`), checked against its session row on every
  request, or
* an API key (`Authorization: Bearer rk_...` or `X-API-Key: rk_...`), looked up on every request.

Both become a `Principal` whose tenant and role come from the verified credential, never from the request.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import apikeys, ratelimit
from app.core.apikeys import API_CLIENT_ROLE, ApiKeyIdentity
from app.core.db import RlsContext, open_session
from app.core.errors import Unauthorized
from app.core.security import AccessClaims, decode_access_token
from app.db import models

STAFF_ROLES = ("officer", "admin", "auditor")
ALL_ROLES = ("citizen", "helper", "officer", "admin", "auditor")  # user roles; API keys are admitted by scope only

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /v1/auth/login, or an API key (rk_...)")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="An API key (rk_...) made by a department admin")


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. Everything here comes from the verified token and the session row."""

    user_id: UUID  # for an API key: the key's id
    tenant_id: UUID
    role: str
    session_id: UUID | None = None
    person_id: UUID | None = None
    auth_kind: str = "user"  # user | api_key
    acting_for_person_id: UUID | None = None  # set when a helper acts for a person (verified server-side)
    api_key: ApiKeyIdentity | None = None  # set when auth_kind is "api_key"

    @property
    def scopes(self) -> tuple[str, ...]:
        return self.api_key.scopes if self.api_key else ()

    def rls(self) -> RlsContext:
        return RlsContext(role=self.role, tenant_id=self.tenant_id, user_id=self.user_id, person_id=self.person_id)


@dataclass(frozen=True, slots=True)
class Credential:
    """A verified credential, before the per-request session check. Exactly one of the two is set."""

    claims: AccessClaims | None = None
    api_key: ApiKeyIdentity | None = None

    def rls(self) -> RlsContext:
        if self.api_key is not None:
            return RlsContext(role=API_CLIENT_ROLE, tenant_id=self.api_key.tenant_id, user_id=self.api_key.id)
        assert self.claims is not None
        claims = self.claims
        return RlsContext(role=claims.role, tenant_id=claims.tenant_id, user_id=claims.user_id, person_id=claims.person_id)


def _verify(bearer: HTTPAuthorizationCredentials | None, header_key: str | None) -> Credential:
    token = bearer.credentials.strip() if bearer and bearer.credentials else ""
    key = (header_key or "").strip()
    if token and key:
        raise Unauthorized("Send one credential: an access token or an API key, not both.", code="ambiguous_credentials")
    if key or apikeys.looks_like_api_key(token):
        return Credential(api_key=apikeys.authenticate(key or token))
    if not token:
        raise Unauthorized("Sign in to continue.", code="not_authenticated", headers={"WWW-Authenticate": "Bearer"})
    return Credential(claims=decode_access_token(token))


def get_credential(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    header_key: str | None = Depends(_api_key_header),
) -> Credential:
    """Verify whatever the caller presented. A failure counts against the caller's network rate limit.

    The limit is charged before a refused key is recorded, so a caller over its limit gets 429 and writes nothing.
    """
    try:
        return _verify(bearer, header_key)
    except Unauthorized as exc:
        ratelimit.charge_anonymous(request.url.path)  # after too many failures the answer becomes 429
        if isinstance(exc, apikeys.KeyRefused):
            apikeys.record_refusal(exc)
        raise


def get_claims(credential: Credential = Depends(get_credential)) -> AccessClaims:
    """The access token of a signed-in user. API keys are refused here."""
    if credential.claims is None:
        raise Unauthorized("This needs a signed-in user, not an API key.", code="user_token_required")
    return credential.claims


def get_db(credential: Credential = Depends(get_credential)) -> Iterator[Session]:
    """One session per request, carrying the caller's RLS context.

    Endpoints commit explicitly once their work is complete. Anything left uncommitted is rolled back
    here, so a failed request never leaves a partial write.
    """
    session = open_session(credential.rls())
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def get_principal(
    request: Request, credential: Credential = Depends(get_credential), db: Session = Depends(get_db)
) -> Principal:
    """A valid token is not enough: its session must still exist, be unrevoked, and match the token.

    This is what makes sign-out, revoke-all and tenant switching take effect on the very next request.
    An API key was looked up again for this request in `get_credential`, so revoking it works the same way.
    """
    if credential.api_key is not None:
        key = credential.api_key
        principal = Principal(user_id=key.id, tenant_id=key.tenant_id, role=API_CLIENT_ROLE, auth_kind="api_key", api_key=key)
        request.state.principal = principal
        return principal

    claims = credential.claims
    assert claims is not None
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
        ratelimit.charge_anonymous(request.url.path)
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
