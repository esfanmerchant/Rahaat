"""The process-wide model: trained once from the committed corpus, on the training families only.

The deployed model is the one the evaluation measures (same data, same parameters, same version), so the
numbers on the eval dashboard describe what is running. Training takes a few seconds; the first caller
waits, everyone else reuses it. Without the corpus the checker reports itself unavailable and abstains.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from app.core.logging import get_logger
from app.modules.scam import corpus
from app.modules.scam.engine import DEFAULT_COSTS, ScamCosts, ScamResult, Verifier, decide
from app.modules.scam.model import PARAMS, ScamModel, model_version, train
from app.modules.scam.signals import DEFAULT_OFFICIAL_SENDER, analyse

log = get_logger("rahat.scam")
PROVIDER = "local: char n-gram TF-IDF + logistic regression, stacked with link, sender and money signals"

_lock = threading.Lock()
_model: ScamModel | None = None
_error: str | None = None


class ModelUnavailable(RuntimeError):
    pass


def training_rows() -> tuple[list[dict[str, Any]], str]:
    data = corpus.corpus_bytes()
    rows = corpus.load()
    return [r for r in rows if r["split"] == "train"], hashlib.sha256(data).hexdigest()


def get_model() -> ScamModel:
    global _model, _error
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            try:
                rows, data_hash = training_rows()
                _model = train(rows, data_hash=data_hash)
                _error = None
                log.info("scam model %s trained on %d messages in %d ms", _model.version, _model.n_train, _model.trained_ms)
            except (OSError, ValueError) as exc:
                _error = f"{type(exc).__name__}: {exc}"[:200]
                log.exception("scam model could not be trained")
                raise ModelUnavailable(_error) from exc
    return _model


def classify(text: str, sender: str | None = None, *, official_sender: str = DEFAULT_OFFICIAL_SENDER,
             official_domains: frozenset[str] = frozenset(), verify: Verifier | None = None,
             costs: ScamCosts = DEFAULT_COSTS) -> ScamResult:  # fmt: skip
    signals = analyse(text, sender, official_sender=official_sender, official_domains=official_domains)
    return decide(signals, get_model(), verify=verify, costs=costs)


def status() -> dict[str, Any]:
    """For /v1/system/health: which provider answers scam checks right now."""
    if _model is not None:
        return {"status": "ready", "provider": PROVIDER, "hosted": "none", "model_version": _model.version, "trained_ms": _model.trained_ms,
                "train_messages": _model.n_train, "train_families": _model.n_families}  # fmt: skip
    if _error:
        return {"status": "unavailable", "provider": PROVIDER, "hosted": "none", "error": _error}
    try:
        expected = model_version(hashlib.sha256(corpus.corpus_bytes()).hexdigest(), PARAMS)
    except OSError:
        return {"status": "unavailable", "provider": PROVIDER, "hosted": "none", "error": "corpus file missing"}
    return {"status": "not_loaded", "provider": PROVIDER, "hosted": "none", "model_version": expected}


def reset_for_tests() -> None:
    global _model, _error
    with _lock:
        _model, _error = None, None
