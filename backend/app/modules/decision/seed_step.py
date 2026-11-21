"""Seed: register the active evidence model (with its held-out metrics) for every department. Safe to run twice."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.modules.decision.model import get_model, registry_row

ORDER = 50


def seed(db: Session) -> None:
    model = get_model()
    row = registry_row(model)
    for tenant_id in db.scalars(select(models.Tenant.id).where(models.Tenant.kind == "department")).all():
        exists = db.scalar(select(models.ModelRegistry.id).where(models.ModelRegistry.tenant_id == tenant_id,
                                                                 models.ModelRegistry.name == row["name"],
                                                                 models.ModelRegistry.version == row["version"]))  # fmt: skip
        if exists is None:
            db.add(models.ModelRegistry(id=uuid.uuid4(), tenant_id=tenant_id, status="active", **row))
    db.flush()
