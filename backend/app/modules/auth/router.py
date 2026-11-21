from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import current_client_ip
from app.core.deps import ALL_ROLES, Principal, get_db
from app.core.errors import Forbidden
from app.core.policy import Policy, Public
from app.modules.auth import service
from app.modules.auth.schemas import AuthOut, LoginIn, MeOut, SessionOut, SwitchIn

router = APIRouter(prefix="/v1/auth", tags=["auth"])

REFRESH_COOKIE = "rt"
_COOKIE_PATH = "/v1/auth"
_self = Policy("auth:self", ALL_ROLES, description="Any signed-in user, acting on their own sign-in")


def _set_refresh_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, raw, max_age=settings.refresh_ttl_seconds, path=_COOKIE_PATH,
        httponly=True, secure=settings.cookie_secure_effective, samesite="lax",
    )  # fmt: skip


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH, httponly=True, secure=settings.cookie_secure_effective, samesite="lax")


def require_app_header(request: Request) -> None:
    """Cookie-authenticated calls need a custom header. A cross-site form or image tag cannot send it."""
    if request.headers.get("x-requested-with") != "rahat":
        raise Forbidden("This request must come from the app.", code="csrf_header_missing")


@router.post("/login", response_model=AuthOut, summary="Sign in with email + password or mock phone + PIN")
def login(body: LoginIn, request: Request, response: Response,
          _: None = Depends(Public("signing in is how a caller becomes authenticated"))) -> AuthOut:  # fmt: skip
    issued = service.login(
        identifier=body.identifier, secret=body.secret, tenant_slug=body.tenant_slug,
        device_label=request.headers.get("user-agent"), ip=current_client_ip(),
    )  # fmt: skip
    _set_refresh_cookie(response, issued.refresh_token)
    return issued.out


@router.post("/refresh", response_model=AuthOut, summary="Exchange the refresh cookie for a new access token",
             dependencies=[Depends(require_app_header)])  # fmt: skip
def refresh(request: Request, response: Response,
            _: None = Depends(Public("authenticated by the httpOnly refresh cookie, which rotates on every use"))) -> AuthOut:  # fmt: skip
    issued = service.refresh(request.cookies.get(REFRESH_COOKIE))
    _set_refresh_cookie(response, issued.refresh_token)
    return issued.out


@router.post("/logout", status_code=204, summary="End this session", dependencies=[Depends(require_app_header)])
def logout(request: Request, response: Response,
           _: None = Depends(Public("authenticated by the httpOnly refresh cookie; safe to call when signed out"))) -> Response:  # fmt: skip
    service.logout(request.cookies.get(REFRESH_COOKIE))
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


@router.post("/switch", response_model=AuthOut, summary="Switch to another department you belong to")
def switch(body: SwitchIn, response: Response, principal: Principal = Depends(_self)) -> AuthOut:
    issued = service.switch(principal, tenant_id=body.tenant_id, role=body.role)
    _set_refresh_cookie(response, issued.refresh_token)
    return issued.out


@router.get("/me", response_model=MeOut, summary="Who am I, and which departments do I belong to")
def me(principal: Principal = Depends(_self), db: Session = Depends(get_db)) -> MeOut:
    return service.me(db, principal)


@router.get("/sessions", response_model=list[SessionOut], summary="My signed-in devices")
def sessions(principal: Principal = Depends(_self), db: Session = Depends(get_db)) -> list[SessionOut]:
    return service.list_sessions(db, principal)


@router.delete("/sessions/{session_id}", status_code=204, summary="Sign out one device")
def revoke_session(session_id: UUID, principal: Principal = Depends(_self), db: Session = Depends(get_db)) -> Response:
    service.revoke_session(db, principal, session_id)
    return Response(status_code=204)


@router.post("/logout-all", summary="Sign out every device")
def logout_all(response: Response, principal: Principal = Depends(_self), db: Session = Depends(get_db)) -> dict[str, int]:
    count = service.revoke_all(db, principal)
    _clear_refresh_cookie(response)
    return {"revoked": count}
