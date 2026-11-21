"""Rows the platform itself needs before anything else works: the platform tenant and the plans."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.audit import PLATFORM_TENANT_ID
from app.core.crypto import new_wrapped_dek
from app.core.db import system_session
from app.core.logging import get_logger
from app.db import models

log = get_logger("rahat.bootstrap")

PLANS: tuple[tuple[str, str, int, dict[str, int]], ...] = (
    ("free", "Free", 0, {"api_calls": 1_000, "ocr": 100, "sms": 200, "ai_calls": 500}),
    ("standard", "Standard", 25_000, {"api_calls": 50_000, "ocr": 5_000, "sms": 10_000, "ai_calls": 25_000}),
    ("enterprise", "Enterprise", 150_000, {"api_calls": 2_000_000, "ocr": 200_000, "sms": 500_000, "ai_calls": 1_000_000}),
)


def ensure_platform_rows() -> None:
    """Idempotent. Safe to call on every start and from several processes at once."""
    try:
        with system_session() as db:
            if db.get(models.Tenant, PLATFORM_TENANT_ID) is None:
                db.add(
                    models.Tenant(
                        id=PLATFORM_TENANT_ID, slug="platform", name="Platform", kind="platform",
                        status="system", region="PK", wrapped_dek=new_wrapped_dek(),
                    )  # fmt: skip
                )
            existing = set(db.scalars(select(models.Plan.code)).all())
            for code, name, price, limits in PLANS:
                if code not in existing:
                    db.add(models.Plan(code=code, name=name, price_pkr=price, limits=limits))
    except IntegrityError:
        log.info("platform rows were created by another process")
