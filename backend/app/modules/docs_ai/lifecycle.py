"""Load the OCR model in the background when a demo or production server starts.

Loading the recogniser takes about two seconds. Without this, the first card someone uploads in the live demo
would wait for it. Tests and the dev server skip it and load the model on first use instead.
"""

from __future__ import annotations

import threading

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("rahat.docs_ai")


def _warm() -> None:
    try:
        from app.modules.docs_ai.ocr import default_engine

        engine = default_engine()
        log.info("OCR engine %s ready: %s", getattr(engine, "name", type(engine).__name__), engine.available())
    except Exception:  # noqa: BLE001  (a failure here only means the first upload loads the model)
        log.exception("could not load the OCR engine at startup")


def startup() -> None:
    if get_settings().app_env in ("demo", "prod"):
        threading.Thread(target=_warm, name="ocr-warmup", daemon=True).start()


def shutdown() -> None:
    return None
