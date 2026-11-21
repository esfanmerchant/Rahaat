"""RFC 7807 problem responses. Clients get a stable code and a request id, never a stack trace."""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import current_request_id
from app.core.logging import get_logger

log = get_logger("rahat.errors")
PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        self.extra = extra or {}
        self.headers = headers or {}


class Unauthorized(AppError):
    status, code, title = 401, "not_authenticated", "Not authenticated"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "You do not have permission to do this"


class NotFound(AppError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "Conflict"


class Unprocessable(AppError):
    status, code, title = 422, "invalid_input", "Some of the information needs fixing"


class PaymentRequired(AppError):
    status, code, title = 402, "plan_limit_reached", "Plan limit reached"


class TooManyRequests(AppError):
    status, code, title = 429, "too_many_requests", "Too many requests. Please try again later."


class ServiceUnavailable(AppError):
    status, code, title = 503, "service_unavailable", "A service we depend on is not responding. Try again soon."


def problem(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    *,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://rahat.example/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail or title,
        "code": code,
        "request_id": current_request_id(),
    }
    if extra:
        # Extra fields never replace the standard ones (type, title, status, detail, code, request_id).
        body.update({k: v for k, v in extra.items() if k not in body})
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


_LOGGED_FLAG = "_rahat_logged"


def mark_logged(exc: BaseException) -> None:
    """The request middleware already logged this error (with its request id) and answered the client."""
    with contextlib.suppress(AttributeError):  # a type that refuses new attributes is then logged twice, which is harmless
        setattr(exc, _LOGGED_FLAG, True)


def _field_path(loc: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in loc)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.title, exc.detail, extra=exc.extra, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Repairable: say which field and why, without echoing the submitted value back.
        errors = [
            {"field": _field_path(tuple(e.get("loc", ()))), "message": e.get("msg", "invalid"), "code": e.get("type", "invalid")}
            for e in exc.errors()
        ]
        return problem(422, "invalid_input", Unprocessable.title, "Check the fields listed in 'errors'.", extra={"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code in (404, 405):
            # No route matched, so no policy charged the caller: probing for endpoints counts against the network.
            from app.core import ratelimit  # imported here because ratelimit imports this module

            try:
                ratelimit.charge_anonymous(request.url.path)
            except TooManyRequests as limited:
                return problem(limited.status, limited.code, limited.title, limited.detail, extra=limited.extra, headers=limited.headers)
        code = {401: "not_authenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        title = str(exc.detail) if isinstance(exc.detail, str) else "Request failed"
        return problem(exc.status_code, code, title, headers=dict(exc.headers or {}))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Normally the request middleware has already answered (with headers and the request id); this is the
        # fallback for an error raised outside it.
        if not getattr(exc, _LOGGED_FLAG, False):
            log.exception("unhandled error: %s", type(exc).__name__)
        return problem(500, "internal_error", "Something went wrong on our side", "Quote the request id if you report this.")
