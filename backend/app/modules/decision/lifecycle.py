"""Train the evidence model in the background when the app starts, so the first decision does not wait."""

from __future__ import annotations

import threading

from app.core.logging import get_logger

log = get_logger("rahat.decision")


def _warm() -> None:
    try:
        from app.modules.decision.model import get_model

        model = get_model()
        log.info("evidence model %s ready", model.version)
    except Exception:  # noqa: BLE001  (a failure here only means the first decision trains it)
        log.exception("could not train the evidence model at startup")


def startup() -> None:
    threading.Thread(target=_warm, name="evidence-model-warmup", daemon=True).start()


def shutdown() -> None:
    return None
