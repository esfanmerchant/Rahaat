"""The local classifier: character n-gram TF-IDF and logistic regression, stacked with the signals.

Training (about a second, deterministic, from the committed corpus):
1. Train families are dealt into folds, so a fold never shares a storyline with the rest.
2. A text model per fold predicts its held-out fold. Those out-of-fold probabilities and the signal values
   train a second logistic regression (the stacker). Its weights say how far to trust each signal when the
   text model has not seen a storyline, and its log-loss fit is what calibrates the output.
3. At inference the fold text models are averaged, so the stacker sees inputs like the ones it was fitted on.

scikit-learn and numpy are imported inside the functions: importing this module costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.modules.scam.signals import EMAIL_IN_TEXT, PHONE_IN_TEXT, SIGNAL_NAMES, URL_PATTERN, analyse
from app.modules.scam.text import normalise

CLASSES: tuple[str, ...] = ("relief_scam", "phishing_link", "advance_fee", "impersonation", "legit_program_message", "unknown")
SCAM_CLASSES: tuple[str, ...] = CLASSES[:4]
LEGIT_CLASSES: tuple[str, ...] = CLASSES[4:]
ENGINE_VERSION = "1"
PARAMS: dict[str, Any] = {
    "analyzer": "char_wb", "ngram_range": [2, 5], "min_df": 2, "max_features": 50000, "sublinear_tf": True,
    "c_text": 1.0, "c_stack": 0.3, "folds": 4, "seed": 2026, "binary_balance": True, "official_sender": "RAHAT",
}  # fmt: skip
_CODE_PHRASE = re.compile(r"(?i)(?:\bcode|\bkod|(?<![؀-ۿ])کوڈ)\s*[:#.-]?\s*[A-Za-z0-9]{3}[\s-]?[A-Za-z0-9]{3}(?![A-Za-z0-9])")
_DIGIT = re.compile(r"\d")
_SPACE = re.compile(r"\s+")


def model_text(text: str) -> str:
    """What the text model reads: links, phones, emails and verify codes become placeholders, digits become 0."""
    value = normalise(text).lower()
    value = URL_PATTERN.sub(" url ", value)
    value = EMAIL_IN_TEXT.sub(" email ", value)
    value = PHONE_IN_TEXT.sub(" phone ", value)
    value = _CODE_PHRASE.sub(" ", value)
    value = _DIGIT.sub("0", value)
    return _SPACE.sub(" ", value).strip()


@dataclass
class ScamModel:
    version: str
    data_hash: str
    params: dict[str, Any]
    vectorizer: Any
    text_models: list[Any]
    stacker: Any
    trained_ms: int
    n_train: int
    n_families: int
    classes: tuple[str, ...] = CLASSES
    extras: dict[str, Any] = field(default_factory=dict)

    def text_proba(self, texts: list[str]) -> Any:
        import numpy as np

        matrix = self.vectorizer.transform(texts)
        return np.mean([_aligned(m, m.predict_proba(matrix)) for m in self.text_models], axis=0)

    def stack_input(self, text_probs: Any, signal_rows: list[list[float]]) -> Any:
        import numpy as np

        return np.hstack([np.log(np.clip(text_probs, 1e-4, 1.0)), np.asarray(signal_rows, dtype=float)])

    def predict(self, texts: list[str], signal_rows: list[list[float]]) -> tuple[Any, Any]:
        """(text-model probabilities, final calibrated probabilities), columns in CLASSES order."""
        text_probs = self.text_proba([model_text(t) for t in texts])
        final = _aligned(self.stacker, self.stacker.predict_proba(self.stack_input(text_probs, signal_rows)))
        return text_probs, final

    def pairwise(self, text_probs_row: Any, signal_row: list[float], top: int, other: int) -> tuple[float, dict[str, float]]:
        """Exact split of log(p_top / p_other): the text model's part and each signal's part."""
        import numpy as np

        coef = _aligned_coef(self.stacker)
        diff = coef[top] - coef[other]
        n_text = len(self.classes)
        text_part = float(np.dot(diff[:n_text], np.log(np.clip(text_probs_row, 1e-4, 1.0))))
        parts = {name: float(diff[n_text + i] * value) for i, (name, value) in enumerate(zip(SIGNAL_NAMES, signal_row, strict=True)) if value}
        return text_part, parts


def _aligned(model: Any, probs: Any) -> Any:
    """Columns in CLASSES order, whatever order scikit-learn chose."""
    import numpy as np

    index = {label: i for i, label in enumerate(model.classes_)}
    out = np.zeros((probs.shape[0], len(CLASSES)))
    for j, label in enumerate(CLASSES):
        if label in index:
            out[:, j] = probs[:, index[label]]
    return out


def _aligned_coef(model: Any) -> Any:
    import numpy as np

    index = {label: i for i, label in enumerate(model.classes_)}
    coef = np.zeros((len(CLASSES), model.coef_.shape[1]))
    for j, label in enumerate(CLASSES):
        if label in index:
            coef[j] = model.coef_[index[label]]
    return coef


def model_version(data_hash: str, params: dict[str, Any] = PARAMS) -> str:
    material = json.dumps({"data": data_hash, "params": params, "engine": ENGINE_VERSION}, sort_keys=True)
    return "scam-lr-" + hashlib.sha256(material.encode()).hexdigest()[:12]


def _weights(labels: list[str], balance: bool) -> list[float]:
    """Scam and legitimate messages weigh the same in total; classes share their side equally."""
    counts = Counter(labels)
    if not balance:
        return [1.0] * len(labels)
    mass = {c: 0.5 / len(SCAM_CLASSES) if c in SCAM_CLASSES else 0.5 / len(LEGIT_CLASSES) for c in CLASSES}
    n = len(labels)
    return [mass[label] * n / counts[label] for label in labels]


def _folds(records: list[dict[str, Any]], k: int, seed: int) -> list[int]:
    """Deal each class's families round-robin into k folds, after a seeded shuffle."""
    rng = random.Random(seed)
    by_label: dict[str, list[str]] = {}
    for record in records:
        names = by_label.setdefault(record["label"], [])
        if record["family"] not in names:
            names.append(record["family"])
    fold_of: dict[str, int] = {}
    offset = 0
    for label in sorted(by_label):
        names = sorted(by_label[label])
        rng.shuffle(names)
        for i, name in enumerate(names):
            fold_of[name] = (i + offset) % k
        offset += len(names)
    return [fold_of[r["family"]] for r in records]


def signal_rows(records: list[dict[str, Any]], official_sender: str) -> list[list[float]]:
    return [analyse(r["text"], r.get("sender"), official_sender=official_sender).vector() for r in records]


def train(records: list[dict[str, Any]], *, data_hash: str, params: dict[str, Any] = PARAMS) -> ScamModel:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    started = time.perf_counter()
    texts = [model_text(r["text"]) for r in records]
    labels = [r["label"] for r in records]
    weights = np.asarray(_weights(labels, params["binary_balance"]))
    signals = signal_rows(records, params["official_sender"])
    vectorizer = TfidfVectorizer(analyzer=params["analyzer"], ngram_range=tuple(params["ngram_range"]), min_df=params["min_df"],
                                 max_features=params["max_features"], sublinear_tf=params["sublinear_tf"], dtype=np.float32)  # fmt: skip
    matrix = vectorizer.fit_transform(texts)
    folds = np.asarray(_folds(records, params["folds"], params["seed"]))
    y = np.asarray(labels)
    oof = np.zeros((len(records), len(CLASSES)))
    text_models = []
    for fold in range(params["folds"]):
        fit_rows, held = folds != fold, folds == fold
        model = LogisticRegression(C=params["c_text"], max_iter=3000)
        model.fit(matrix[fit_rows], y[fit_rows], sample_weight=weights[fit_rows])
        oof[held] = _aligned(model, model.predict_proba(matrix[held]))
        text_models.append(model)
    stacker = LogisticRegression(C=params["c_stack"], max_iter=5000)
    stack_x = np.hstack([np.log(np.clip(oof, 1e-4, 1.0)), np.asarray(signals, dtype=float)])
    stacker.fit(stack_x, y, sample_weight=weights)
    elapsed = int((time.perf_counter() - started) * 1000)
    return ScamModel(version=model_version(data_hash, params), data_hash=data_hash, params=dict(params), vectorizer=vectorizer,
                     text_models=text_models, stacker=stacker, trained_ms=elapsed, n_train=len(records),
                     n_families=len({r["family"] for r in records}))  # fmt: skip
