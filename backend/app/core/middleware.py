"""One ASGI middleware for request ids, body limits, security headers, access logs and metrics."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics
from app.core.config import get_settings
from app.core.context import client_ip_var, jobs_holder_var, request_id_var
from app.core.errors import mark_logged, problem
from app.core.logging import get_logger

log = get_logger("rahat.access")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_CSP_APP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
# Swagger UI loads its bundle from a CDN and uses an inline bootstrap script. Only the docs pages get this.
_CSP_DOCS = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)
_DOCS_PATHS = ("/docs", "/redoc")
_NO_CACHE_FILES = ("/", "/index.html", "/sw.js", "/registerSW.js", "/manifest.webmanifest")


class _BodyTooLarge(Exception):
    pass


def _client_ip(headers: dict[str, str], client: Any, header_name: str | None) -> str:
    """The ASGI peer address, unless CLIENT_IP_HEADER names a header the hosting platform sets itself.

    Only set it where the platform overwrites that header on every request (Vercel does for x-vercel-forwarded-for,
    x-real-ip and x-forwarded-for). Anywhere else a client could send its own value and dodge the per-address limits.
    """
    if header_name:
        value = headers.get(header_name.strip().lower(), "").split(",")[0].strip()
        if value and len(value) <= 64:
            return value
    return str(client[0]) if client else ""


def _cache_control(path: str) -> str | None:
    if path.startswith("/v1/") or path in ("/healthz", "/readyz", "/metrics", "/openapi.json"):
        return "no-store"
    if path.startswith("/assets/"):
        return "public, max-age=31536000, immutable"
    if path in _NO_CACHE_FILES or path.startswith("/workbox-"):
        return "no-cache"
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        inbound = headers.get("x-request-id", "")
        request_id = inbound if _SAFE_REQUEST_ID.match(inbound) else uuid.uuid4().hex[:20]
        client = scope.get("client")
        settings = get_settings()
        rid_token = request_id_var.set(request_id)
        ip_token = client_ip_var.set(_client_ip(headers, client, settings.client_ip_header))
        # Inline jobs: a sync endpoint cannot set a context variable for us, so it marks this shared holder instead.
        holder: dict[str, bool] | None = {"enqueued": False} if settings.jobs_inline else None
        holder_token = jobs_holder_var.set(holder)

        path: str = scope["path"]
        method: str = scope["method"]
        https = scope.get("scheme") == "https" or headers.get("x-forwarded-proto") == "https"
        state: dict[str, Any] = {"status": 500, "started": False}
        started_at = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["started"] = True
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = request_id
                out["X-Content-Type-Options"] = "nosniff"
                out["Referrer-Policy"] = "no-referrer"
                out["X-Frame-Options"] = "DENY"
                out["Cross-Origin-Opener-Policy"] = "same-origin"
                out["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
                out["Content-Security-Policy"] = _CSP_DOCS if path.startswith(_DOCS_PATHS) else _CSP_APP
                if https:
                    out["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                cache = _cache_control(path)
                if cache and "cache-control" not in out:
                    out["Cache-Control"] = cache
            elif holder is not None and holder["enqueued"] and message["type"] == "http.response.body" and not message.get("more_body"):
                # Serverless: the endpoint has committed, so run what it queued before the last byte leaves. A function
                # may be frozen once the response is complete, and the platform documents no way to run work after it.
                holder["enqueued"] = False
                from app.modules.jobs.inline import drain

                await run_in_threadpool(drain)
            await send(message)

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _BodyTooLarge
            return message

        try:
            declared = headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_body_bytes:
                raise _BodyTooLarge
            await self.app(scope, limited_receive, send_wrapper)
        except _BodyTooLarge:
            if not state["started"]:
                response = problem(413, "payload_too_large", "That upload is too large", "Send a smaller file.")
                await response(scope, receive, send_wrapper)
        except Exception as exc:
            # Starlette renders unexpected errors outside every middleware: without the security headers, and after
            # the request id is gone. Answer here instead, then let the error continue so the server and tests see it.
            if not state["started"]:
                log.exception("unhandled error: %s", type(exc).__name__)
                mark_logged(exc)
                response = problem(500, "internal_error", "Something went wrong on our side", "Quote the request id if you report this.")
                await response(scope, receive, send_wrapper)
            raise
        finally:
            elapsed = time.perf_counter() - started_at
            route = getattr(scope.get("route"), "path", "unmatched")
            metrics.observe_request(method, route, int(state["status"]), elapsed)
            log.info(
                "request",
                extra={"fields": {"method": method, "route": route, "status": state["status"], "ms": round(elapsed * 1000, 1)}},
            )
            request_id_var.reset(rid_token)
            client_ip_var.reset(ip_token)
            jobs_holder_var.reset(holder_token)
