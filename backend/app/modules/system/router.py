"""Health, metrics, platform info, the endpoint-to-role registry and the demo accounts list."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.core import metrics
from app.core.config import PROTOTYPE_LABEL, PROTOTYPE_LABEL_UR, get_settings
from app.core.db import system_session
from app.core.deps import STAFF_ROLES, Principal
from app.core.errors import NotFound, ServiceUnavailable
from app.core.logging import get_logger
from app.core.policy import Policy, Public, describe_routes
from app.demo_accounts import DEMO_ACCOUNTS, DEMO_TENANTS, secret_for

router = APIRouter(tags=["system"])
log = get_logger("rahat.system")


class InfoOut(BaseModel):
    app: str = "rahat"
    env: str
    version: str
    prototype_label: str = PROTOTYPE_LABEL
    prototype_label_ur: str = PROTOTYPE_LABEL_UR
    languages: list[str] = ["ur", "en"]
    features: dict[str, bool]
    demo_mode: bool
    ai_profile: str


class DemoAccountOut(BaseModel):
    label: str
    kind: str
    role: str
    tenant_slug: str
    tenant_name: str
    identifier: str
    secret: str


class DemoAccountsOut(BaseModel):
    notice: str = "Demo accounts with invented people. " + PROTOTYPE_LABEL
    accounts: list[DemoAccountOut]


def _database_ok() -> bool:
    try:
        with system_session() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        log.exception("database check failed")
        return False


@router.get("/healthz", summary="Liveness: the process is up (does not touch the database)")
def healthz(_: None = Depends(Public("liveness probe"))) -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: the database answers")
def readyz(_: None = Depends(Public("readiness probe"))) -> dict[str, str]:
    if not _database_ok():
        raise ServiceUnavailable("The database is not answering.")
    return {"status": "ready"}


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
def prometheus(_: None = Depends(Public("aggregate counters only; labels never carry identifiers"))) -> Response:
    return Response(metrics.render(), media_type=metrics.METRICS_CONTENT_TYPE)


@router.get("/v1/system/info", response_model=InfoOut, summary="What this deployment is")
def info(_: None = Depends(Public("needed before sign-in: prototype label, languages, feature flags"))) -> InfoOut:
    settings = get_settings()
    return InfoOut(
        env=settings.app_env, version=settings.app_version, features=settings.features(),
        demo_mode=settings.demo_mode, ai_profile=settings.ai_profile,
    )  # fmt: skip


@router.get("/v1/system/health", summary="Which parts are running right now")
def health(_: Principal = Depends(Policy("system:health", STAFF_ROLES))) -> dict[str, Any]:
    settings = get_settings()
    return {
        "database": "ok" if _database_ok() else "down",
        "env": settings.app_env,
        "ai_profile": settings.ai_profile,
        "providers": {
            "ocr_tesseract": "available" if shutil.which("tesseract") else "missing",
        },
        "contract_stubs": settings.stubs_effective,
    }


@router.get("/v1/system/policies", summary="Endpoint-to-role registry (every route and who may call it)")
def policies(request: Request, _: Principal = Depends(Policy("system:policies", ["admin", "auditor"]))) -> list[dict[str, Any]]:
    return describe_routes(request.app)


@router.get("/v1/demo/accounts", response_model=DemoAccountsOut, summary="Demo sign-ins (not available in prod)")
def demo_accounts(_: None = Depends(Public("demo credentials for invented accounts; disabled in prod"))) -> DemoAccountsOut:
    if not get_settings().demo_mode:
        raise NotFound()
    names = {t["slug"]: t["name"] for t in DEMO_TENANTS}
    return DemoAccountsOut(
        accounts=[
            DemoAccountOut(
                label=a["label"], kind=a["kind"], role=a["role"], tenant_slug=a["tenants"][0],
                tenant_name=names[a["tenants"][0]], identifier=a["identifier"], secret=secret_for(a),
            )  # fmt: skip
            for a in DEMO_ACCOUNTS
        ]
    )
