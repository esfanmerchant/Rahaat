"""Train the evidence model in the background when the app starts, so the first decision does not wait.

Then score the held-out labelled cases under each department's active rule version, so the first
cost-page request (and every slider move after it) answers in tens of milliseconds.
"""

from __future__ import annotations

import threading

from app.core.logging import get_logger

log = get_logger("rahat.decision")


def _warm_scores() -> None:
    from sqlalchemy import select

    from app.core.db import system_session
    from app.db import models
    from app.modules.decision.model import get_model
    from app.modules.evals.decision_eval import cached_scores

    with system_session() as db:  # read-only: the active rule version of each department
        versions = db.scalars(
            select(models.RuleVersion).join(models.RuleSet, models.RuleSet.active_version_id == models.RuleVersion.id)
        ).all()  # fmt: skip
        rules = [dict(v.dsl or {}) for v in versions]
    model = get_model()
    for dsl in rules:
        cached_scores(dsl, model)
    log.info("labelled cases scored for %s active rule versions", len(rules))


def _warm() -> None:
    try:
        from app.modules.decision.model import get_model

        model = get_model()
        log.info("evidence model %s ready", model.version)
    except Exception:  # noqa: BLE001  (a failure here only means the first decision trains it)
        log.exception("could not train the evidence model at startup")
        return
    try:
        _warm_scores()
    except Exception:  # noqa: BLE001  (a failure here only means the first analysis scores the cases)
        log.exception("could not score the labelled cases at startup")


def startup() -> None:
    threading.Thread(target=_warm, name="evidence-model-warmup", daemon=True).start()


def shutdown() -> None:
    return None
