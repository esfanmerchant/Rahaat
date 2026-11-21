"""Department API keys, for admins. A key is shown once; only its prefix and a hash are stored."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.deps import Principal, get_db
from app.core.policy import Policy, describe_routes
from app.modules.apikeys import service
from app.modules.apikeys.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyDecide, ApiKeyOut, ApiKeyRevoke, ApiKeyRotate, ScopeOut

router = APIRouter(prefix="/v1/admin/api-keys", tags=["admin: API keys"])
_manage = Policy("apikeys:manage", ["admin"], description="Create, list, rotate and revoke this department's API keys")
_approve = Policy("apikeys:approve", ["admin"], description="A second admin turns on a key that can read personal data")


@router.get("", response_model=list[ApiKeyOut], summary="This department's API keys (never the secrets)")
def list_keys(
    principal: Principal = Depends(_manage),
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False, description="Also list revoked and expired keys"),
) -> list[ApiKeyOut]:
    return service.list_keys(db, principal, include_inactive=include_inactive)


@router.post("", response_model=ApiKeyCreated, status_code=201, summary="Create a key; the response is the only time it is shown")
def create_key(body: ApiKeyCreate, request: Request, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> ApiKeyCreated:
    return service.create_key(db, principal, body, describe_routes(request.app))


@router.get("/scopes", response_model=list[ScopeOut], summary="What a key can be allowed to do, and which endpoints each scope opens")
def list_scopes(request: Request, _: Principal = Depends(_manage)) -> list[ScopeOut]:
    return service.scopes_out(describe_routes(request.app))


@router.get("/{key_id}", response_model=ApiKeyOut, summary="One API key (never the secret)")
def get_key(key_id: UUID, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> ApiKeyOut:
    return service.get_key(db, principal, key_id)


@router.post("/{key_id}/rotate", response_model=ApiKeyCreated, status_code=201,
             summary="Replace the secret; the old key stops at once or after a grace period")  # fmt: skip
def rotate_key(key_id: UUID, body: ApiKeyRotate | None = None, principal: Principal = Depends(_manage),
               db: Session = Depends(get_db)) -> ApiKeyCreated:  # fmt: skip
    return service.rotate_key(db, principal, key_id, body or ApiKeyRotate())


@router.post("/{key_id}/revoke", response_model=ApiKeyOut, summary="Stop a key; it fails on its very next request")
def revoke_key(key_id: UUID, body: ApiKeyRevoke | None = None, principal: Principal = Depends(_manage),
               db: Session = Depends(get_db)) -> ApiKeyOut:  # fmt: skip
    return service.revoke_key(db, principal, key_id, body or ApiKeyRevoke())


@router.post("/{key_id}/decide", response_model=ApiKeyOut, summary="Second admin: turn on (or refuse) a key that reads personal data")
def decide_key(key_id: UUID, body: ApiKeyDecide, principal: Principal = Depends(_approve), db: Session = Depends(get_db)) -> ApiKeyOut:
    return service.decide_key(db, principal, key_id, body)
