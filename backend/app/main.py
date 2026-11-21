"""Application factory: middleware, error handling, auto-discovered routers and the static frontend."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import FileResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

import app.modules as modules_pkg
from app.core.config import PROTOTYPE_LABEL, get_settings
from app.core.errors import NotFound, install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.policy import Public

log = get_logger("rahat.main")
BACKEND_DIR = Path(__file__).resolve().parents[1]

_DESCRIPTION = f"""**{PROTOTYPE_LABEL}**

Rahat is a multi-tenant, AI-assisted public-service platform built for the Coder's Cup '26 hackathon.
Every person, case, message and document is synthetic.

* Sign in with `POST /v1/auth/login`, then press **Authorize** and paste the access token.
* Errors are RFC 7807 problem documents with a `code` and a `request_id`.
* Every endpoint declares who may call it; `GET /v1/system/policies` lists the whole registry.
"""

# Paths the single-page app must never answer for.
_RESERVED_PREFIXES = ("v1/", "docs", "redoc", "openapi.json", "healthz", "readyz", "metrics", "mock/")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        from app.bootstrap import ensure_platform_rows

        ensure_platform_rows()
    except Exception:  # noqa: BLE001
        # Stay up so /healthz answers and /readyz can report the real problem.
        log.exception("startup bootstrap failed; is the database migrated and reachable?")
    hooks = _lifecycle_modules()
    if not get_settings().startup_warmup:
        # Serverless cold start: models, OCR and the corpus load on first use instead of delaying the first request.
        hooks = [(name, module) for name, module in hooks if name == "jobs"]
    for name, module in hooks:
        try:
            getattr(module, "startup", lambda: None)()
        except Exception:  # noqa: BLE001
            log.exception("startup hook of %s failed", name)
    yield
    for name, module in reversed(hooks):
        try:
            getattr(module, "shutdown", lambda: None)()
        except Exception:  # noqa: BLE001
            log.exception("shutdown hook of %s failed", name)


def _lifecycle_modules() -> list[tuple[str, Any]]:
    """`app/modules/<name>/lifecycle.py` may define `startup()` and `shutdown()` (for example the job worker).

    Hooks decide for themselves whether to do anything: check `get_settings().worker_enabled_effective`
    before starting a background loop, so tests stay quiet.
    """
    found: list[tuple[str, Any]] = []
    for module in sorted(pkgutil.iter_modules(modules_pkg.__path__), key=lambda m: m.name):
        name = f"app.modules.{module.name}.lifecycle"
        try:
            found.append((module.name, importlib.import_module(name)))
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return found


def _include_module_routers(app: FastAPI) -> None:
    """Every `app/modules/<name>/router.py` that defines `router` is included, in name order.

    No track edits this file to add an endpoint. `zz_stubs` sorts last, so a real route always wins over
    the contract stub with the same method and path.
    """
    settings = get_settings()
    for module in sorted(pkgutil.iter_modules(modules_pkg.__path__), key=lambda m: m.name):
        if not module.ispkg:
            continue
        if module.name == "zz_stubs" and not settings.stubs_effective:
            continue
        try:
            router_module = importlib.import_module(f"app.modules.{module.name}.router")
        except ModuleNotFoundError as exc:
            if exc.name == f"app.modules.{module.name}.router":
                continue  # a module without HTTP endpoints
            raise
        router = getattr(router_module, "router", None)
        if isinstance(router, APIRouter):
            app.include_router(router)


def _mount_frontend(app: FastAPI) -> None:
    settings = get_settings()
    dist = Path(settings.frontend_dist)
    if not dist.is_absolute():
        dist = (BACKEND_DIR / dist).resolve()
    index = dist / "index.html"
    if not index.is_file():
        log.info("frontend build not found at %s; serving the API only", dist)
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, _: None = Depends(Public("static frontend files and the single-page app shell"))) -> FileResponse:
        if full_path.startswith(_RESERVED_PREFIXES):
            raise NotFound()
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.check_secrets()
    configure_logging()

    app = FastAPI(
        title="Rahat API (Prototype)",
        version=settings.app_version,
        description=_DESCRIPTION,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=_lifespan,
    )
    install_error_handlers(app)
    app.add_middleware(GZipMiddleware, minimum_size=600)
    # Added last so it is outermost: request ids, limits and security headers cover every response.
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_body_bytes)
    _include_module_routers(app)
    _mount_frontend(app)
    return app


app = create_app()
