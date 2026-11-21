"""Seed: give every person a blocking key for dedupe. Runs after the other modules' people are seeded. Idempotent."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.modules.matching.service import backfill_name_keys

ORDER = 900  # after every step that adds people

log = get_logger("rahat.matching")


def seed(db: Session) -> None:
    count = backfill_name_keys(db)
    if count:
        log.info("dedupe blocking keys set for %s people", count)
