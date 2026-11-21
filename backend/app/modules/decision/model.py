"""The calibrated evidence model: `p_eligible` and `p_genuine` from features of a `DecisionInput`.

Two logistic regressions trained on the labelled synthetic world, each calibrated with isotonic regression
on a separate calibration split, and measured on a test split that shares no family (identity) with
training. Training is deterministic and takes about a second; it happens once per process (`get_model()`).

Prediction is plain Python over the learned numbers (standardise, dot product, sigmoid, piecewise-linear
calibration map), with every learned number rounded to 6 decimals. So a decision replays to the same
probabilities, and the model version is a hash of the training data, the parameters and those numbers.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Final

from app.contracts.engine import EvidenceProbabilities
from app.core.audit import hash_payload
from app.modules.decision.facts import build_facts
from app.modules.decision.features import FEATURE_NAMES, compute_features
from app.modules.evals import metrics
from app.synth.world import GENERATOR_VERSION, SEED, SynthCase, World, build_world, family_split

MODEL_NAME: Final = "evidence-lr"
MODEL_CODE_VERSION: Final = "1"
TRAIN_PARAMS: Final[dict[str, Any]] = {
    "seed": SEED, "generator": GENERATOR_VERSION, "households": 1320, "C": 0.5, "calibration": "isotonic", "clip": [0.001, 0.999],
    "split": {"train": 60, "calibration": 20, "test": 20, "by": "family"},
}  # fmt: skip
PRECISION: Final = 4  # probabilities leave the model rounded to this many decimals


def _r6(value: float) -> float:
    return round(float(value), 6)


def _interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """np.interp in plain Python: linear between knots, flat beyond the ends."""
    if not xs:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x) - 1
    x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


@dataclass(frozen=True, slots=True)
class CalibratedLogit:
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float
    knots_x: tuple[float, ...]
    knots_y: tuple[float, ...]
    clip: tuple[float, float] = (0.001, 0.999)

    def raw(self, x: Sequence[float]) -> float:
        z = self.intercept
        for value, mu, sd, w in zip(x, self.mean, self.scale, self.coef, strict=True):
            z += w * (value - mu) / sd
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def prob(self, x: Sequence[float]) -> float:
        low, high = self.clip
        return max(low, min(high, _interp(self.raw(x), self.knots_x, self.knots_y)))

    def as_dict(self) -> dict[str, Any]:
        return {"mean": list(self.mean), "scale": list(self.scale), "coef": list(self.coef), "intercept": self.intercept,
                "knots_x": list(self.knots_x), "knots_y": list(self.knots_y), "clip": list(self.clip)}  # fmt: skip


@dataclass(frozen=True)
class EvidenceModelV1:
    """Implements `app.contracts.engine.EvidenceModel`."""

    version: str
    feature_names: tuple[str, ...]
    eligible: CalibratedLogit
    genuine: CalibratedLogit
    data_hash: str
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def predict(self, features: Mapping[str, float]) -> EvidenceProbabilities:
        x = [float(features.get(name, 0.0)) for name in self.feature_names]
        return EvidenceProbabilities(p_eligible=round(self.eligible.prob(x), PRECISION), p_genuine=round(self.genuine.prob(x), PRECISION))

    def card(self) -> str:
        test = self.metrics.get("test", {})
        return (
            f"{MODEL_NAME} {self.version}: two logistic regressions with isotonic calibration, trained on the seeded "
            f"synthetic world ({self.params.get('seed')}). Test split by family: ECE p_eligible "
            f"{test.get('p_eligible', {}).get('ece')}, p_genuine {test.get('p_genuine', {}).get('ece')}. "
            "Synthetic data only; p_ok assumes eligibility and genuineness are independent."
        )


def case_features(case: SynthCase) -> list[float]:
    params = {"income_cap": case.income_cap}
    feats = compute_features(case.inp, build_facts(case.inp, params), params)
    return [feats[name] for name in FEATURE_NAMES]


def fit_logistic(x: Any, y: Any, l2: float, *, max_iter: int = 100) -> Any:
    """L2-regularised logistic regression by Newton's method (IRLS). The intercept (column 0 of the result) is
    not penalised. Same objective as scikit-learn's `LogisticRegression(C=1/l2)`; a test checks they agree."""
    import numpy as np

    n, d = x.shape
    xb = np.hstack([np.ones((n, 1)), x])
    w = np.zeros(d + 1)
    reg = np.full(d + 1, l2)
    reg[0] = 0.0
    for _ in range(max_iter):
        p = 1.0 / (1.0 + np.exp(-np.clip(xb @ w, -30, 30)))
        grad = xb.T @ (p - y) + reg * w
        hess = xb.T @ (xb * (p * (1 - p))[:, None]) + np.diag(reg) + 1e-9 * np.eye(d + 1)
        step = np.linalg.solve(hess, grad)
        w = w - step
        if float(np.max(np.abs(step))) < 1e-10:
            break
    return w


def fit_isotonic(x: Sequence[float], y: Sequence[float]) -> tuple[list[float], list[float]]:
    """Pool-adjacent-violators. Returns knots for linear interpolation, like scikit-learn's IsotonicRegression."""
    pairs = sorted(zip(x, y, strict=True))
    blocks: list[list[float]] = []  # [sum_y, weight, x_min, x_max]
    i = 0
    while i < len(pairs):  # equal x values are pooled first, as scikit-learn does
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        blocks.append([sum(v for _, v in pairs[i:j]), float(j - i), pairs[i][0], pairs[i][0]])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] >= blocks[-1][0] / blocks[-1][1]:
            top = blocks.pop()
            blocks[-1][0] += top[0]
            blocks[-1][1] += top[1]
            blocks[-1][3] = top[3]
        i = j
    xs: list[float] = []
    ys: list[float] = []
    for total, weight, low, high in blocks:
        for point in (low, high) if high != low else (low,):
            xs.append(point)
            ys.append(total / weight)
    return xs, ys


def fit_platt(raw: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """Platt scaling on the log-odds of the raw score: p = sigmoid(a * logit(raw) + b)."""
    import numpy as np

    logit = np.asarray([math.log(max(r, 1e-9) / max(1 - r, 1e-9)) for r in raw])[:, None]
    w = fit_logistic(logit, np.asarray(y, dtype=float), 1e-6)
    return float(w[1]), float(w[0])


def _fit_one(x_train: list[list[float]], y_train: list[int], x_cal: list[list[float]], y_cal: list[int],
             c: float, clip: tuple[float, float], calibration: str) -> CalibratedLogit:  # fmt: skip
    import numpy as np

    xt = np.asarray(x_train, dtype=float)
    mean = xt.mean(axis=0)
    scale = xt.std(axis=0)
    scale[scale == 0] = 1.0
    w = fit_logistic((xt - mean) / scale, np.asarray(y_train, dtype=float), 1.0 / c)
    partial = CalibratedLogit(
        mean=tuple(_r6(v) for v in mean), scale=tuple(_r6(v) for v in scale), coef=tuple(_r6(v) for v in w[1:]),
        intercept=_r6(w[0]), knots_x=(), knots_y=(), clip=clip,
    )  # fmt: skip
    raw_cal = [partial.raw(row) for row in x_cal]
    if calibration == "isotonic":
        knots_x, knots_y = fit_isotonic(raw_cal, [float(v) for v in y_cal])
    else:  # Platt, written as a dense piecewise-linear map so prediction stays one code path
        a, b = fit_platt(raw_cal, y_cal)
        knots_x = [i / 200 for i in range(201)]
        knots_y = [1.0 / (1.0 + math.exp(-(a * math.log(max(r, 1e-9) / max(1 - r, 1e-9)) + b))) for r in knots_x]
    return CalibratedLogit(
        mean=partial.mean, scale=partial.scale, coef=partial.coef, intercept=partial.intercept,
        knots_x=tuple(_r6(v) for v in knots_x), knots_y=tuple(_r6(v) for v in knots_y), clip=clip,
    )  # fmt: skip


def split_cases(world: World) -> dict[str, list[SynthCase]]:
    out: dict[str, list[SynthCase]] = {"train": [], "calibration": [], "test": []}
    for case in world.cases:
        out[family_split(case.family_id, world.seed)].append(case)
    return out


def train(world: World | None = None, params: Mapping[str, Any] = TRAIN_PARAMS) -> EvidenceModelV1:
    world = world or build_world(int(params["seed"]), households=int(params["households"]))
    parts = split_cases(world)
    rows = {name: [case_features(case) for case in cases] for name, cases in parts.items()}
    labels = {
        name: {"eligible": [int(c.truth.eligible) for c in cases], "genuine": [int(c.truth.genuine) for c in cases]} for name, cases in parts.items()
    }
    clip = (float(params["clip"][0]), float(params["clip"][1]))
    models = {
        target: _fit_one(
            rows["train"],
            labels["train"][target],
            rows["calibration"],
            labels["calibration"][target],
            float(params["C"]),
            clip,
            str(params["calibration"]),
        )
        for target in ("eligible", "genuine")
    }
    data_hash = hash_payload({name: {"x": rows[name], "y": labels[name], "ids": [c.case_id for c in parts[name]]} for name in parts})
    learned = {target: m.as_dict() for target, m in models.items()}
    version = f"{MODEL_NAME}-" + hash_payload({"data": data_hash, "params": dict(params), "features": FEATURE_NAMES,
                                               "learned": learned, "code": MODEL_CODE_VERSION})[:12]  # fmt: skip
    model = EvidenceModelV1(version=version, feature_names=FEATURE_NAMES, eligible=models["eligible"], genuine=models["genuine"],
                            data_hash=data_hash, params=dict(params))  # fmt: skip
    report: dict[str, Any] = {"sizes": {name: len(cases) for name, cases in parts.items()}}
    for name in ("calibration", "test"):
        preds = [model.predict(dict(zip(FEATURE_NAMES, row, strict=True))) for row in rows[name]]
        p_e = [p.p_eligible for p in preds]
        p_g = [p.p_genuine for p in preds]
        p_ok = [round(a * b, PRECISION) for a, b in zip(p_e, p_g, strict=True)]
        ok = [int(c.truth.ok) for c in parts[name]]
        report[name] = {
            "p_eligible": metrics.summary(p_e, labels[name]["eligible"]),
            "p_genuine": metrics.summary(p_g, labels[name]["genuine"]),
            "p_ok": metrics.summary(p_ok, ok),
        }
    return EvidenceModelV1(version=model.version, feature_names=model.feature_names, eligible=model.eligible, genuine=model.genuine,
                           data_hash=data_hash, params=dict(params), metrics=report)  # fmt: skip


@lru_cache(maxsize=1)
def get_model() -> EvidenceModelV1:
    """The active evidence model for this process, trained on first use."""
    return train()


def registry_row(model: EvidenceModelV1) -> dict[str, Any]:
    """The `model_registry` fields for this model (the caller adds tenant_id)."""
    test = model.metrics.get("test", {})
    compact = {target: {k: v for k, v in test.get(target, {}).items() if k != "reliability"} for target in ("p_eligible", "p_genuine", "p_ok")}
    return {"name": MODEL_NAME, "version": model.version, "kind": "calibrated_logistic_regression", "data_hash": model.data_hash,
            "params": model.params, "metrics": {"test": compact, "sizes": model.metrics.get("sizes")}, "card": model.card()}  # fmt: skip
