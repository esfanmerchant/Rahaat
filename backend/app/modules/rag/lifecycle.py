"""Bring the policy corpus into the database when the app starts, so an existing deployment gets new versions.

The container only seeds an empty database (`seed --if-empty`), so without this hook a running demo would
never see the corpus. It is idempotent: unchanged documents are skipped and nothing is ever edited in place.
Skipped in tests, which ingest for their own tenants.
"""

from __future__ import annotations

import threading

from app.core.config import get_settings
from app.core.db import system_session
from app.core.logging import get_logger

log = get_logger("rahat.rag")


def _ingest_all() -> None:
    try:
        from app.modules.rag.ingest import department_ids, ingest

        with system_session() as db:  # narrow: inserts approved policy text for each department, nothing else
            for tenant_id in department_ids(db):
                report = ingest(db, tenant_id)
                if report.added or report.refused:
                    log.info("policy corpus for %s: added %s, refused %s", tenant_id, report.added, report.refused)
    except Exception:  # noqa: BLE001  (the assistant then refuses until the corpus is ingested)
        log.exception("could not ingest the policy corpus at startup")
    try:
        from app.modules.rag import calibration

        calibration.probability(0.5)  # fit once now, so the first question does not wait for it
    except Exception:  # noqa: BLE001
        log.exception("could not prepare the answer calibration")


def startup() -> None:
    if get_settings().app_env == "test":
        return
    threading.Thread(target=_ingest_all, name="policy-corpus-ingest", daemon=True).start()


def shutdown() -> None:
    return None
