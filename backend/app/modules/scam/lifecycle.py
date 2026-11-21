"""Train the scam model when the app starts, so the first check does not wait. Skipped in tests."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.scam import runtime

log = get_logger("rahat.scam")


def startup() -> None:
    if not get_settings().worker_enabled_effective:
        return  # tests train on first use instead
    try:
        runtime.get_model()
    except runtime.ModelUnavailable:
        log.warning("scam checker unavailable: %s", runtime.status().get("error"))


def shutdown() -> None:
    return None
