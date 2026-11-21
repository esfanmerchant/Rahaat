"""Evaluate the scam checker on the held-out families (storylines never seen in training).

    uv run python -m app.modules.scam.evaluate             print the report, store it in eval_runs for every tenant
    uv run python -m app.modules.scam.evaluate --no-db     print only
    uv run python -m app.modules.scam.evaluate --tenant sindh-relief
    uv run python -m app.modules.scam.evaluate --json      print the summary as JSON

Two runs over the same test messages:
- `full`: as deployed. A verify code that our outbox issued is confirmed (the corpus marks which codes are
  real); every other code is checked and not found.
- `no_verify`: codes are ignored, so the model and the signals stand alone. This is the honest number for a
  message that arrives without its code.

A false alarm is a legitimate message (a Rahat message or an ordinary one) answered "scam" or "might be a
scam". A miss is a scam answered "looks real" or "confirmed real". An abstention ("not sure") is neither;
it costs an officer's look and is counted on its own. A silent guess is an `auto` answer that was wrong.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from collections import Counter, defaultdict
from typing import Any

from app.modules.scam import corpus
from app.modules.scam.engine import CodeCheck, ScamResult, decide
from app.modules.scam.model import CLASSES, SCAM_CLASSES, ScamModel
from app.modules.scam.runtime import get_model
from app.modules.scam.signals import analyse

SCAM = frozenset(SCAM_CLASSES)


def _verifier(rows: list[dict[str, Any]]) -> Any:
    issued: dict[str, str] = {}
    for row in rows:
        code = row.get("code") or {}
        if code.get("genuine"):
            family = str(row["family"])
            template = family.split(".", 1)[1] if family.startswith("program.") else ("approved" if "approved" in row["text"] else "payment_sent")
            issued[str(code["value"])] = template

    def verify(code: str) -> CodeCheck:
        template = issued.get(code)
        return CodeCheck(genuine=template is not None, template=template, channel="sms", department="Synthetic department")

    return verify


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def metrics(rows: list[dict[str, Any]], results: list[ScamResult]) -> dict[str, Any]:
    """Pure: the report for one run over labelled rows."""
    truth = [str(r["label"]) for r in rows]
    choice = [res.decision.choice for res in results]
    route = [res.decision.route for res in results]
    n = len(rows)
    per_class: dict[str, dict[str, Any]] = {}
    for label in CLASSES:
        predicted = sum(1 for c in choice if c == label)
        actual = sum(1 for t in truth if t == label)
        hit = sum(1 for t, c in zip(truth, choice, strict=True) if t == label and c == label)
        per_class[label] = {"support": actual, "predicted": predicted, "precision": _rate(hit, predicted), "recall": _rate(hit, actual)}
    legit = [i for i, t in enumerate(truth) if t not in SCAM]
    scams = [i for i, t in enumerate(truth) if t in SCAM]
    program = [i for i, t in enumerate(truth) if t == "legit_program_message"]

    def side_stats(index: list[int]) -> dict[str, Any]:
        return {
            "n": len(index),
            "abstained": _rate(sum(1 for i in index if choice[i] is None), len(index)),
            "called_scam": _rate(sum(1 for i in index if choice[i] in SCAM), len(index)),
            "called_real": _rate(sum(1 for i in index if choice[i] is not None and choice[i] not in SCAM), len(index)),
        }

    by_lang: dict[str, Any] = {}
    for lang in sorted({str(r["lang"]) for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["lang"] == lang]
        lang_legit = [i for i in idx if truth[i] not in SCAM]
        lang_scam = [i for i in idx if truth[i] in SCAM]
        by_lang[lang] = {
            "n": len(idx),
            "abstention_rate": _rate(sum(1 for i in idx if choice[i] is None), len(idx)),
            "false_alarm_rate": _rate(sum(1 for i in lang_legit if choice[i] in SCAM), len(lang_legit)),
            "miss_rate": _rate(sum(1 for i in lang_scam if choice[i] is not None and choice[i] not in SCAM), len(lang_scam)),
            "caught_rate": _rate(sum(1 for i in lang_scam if choice[i] in SCAM), len(lang_scam)),
        }
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for t, c in zip(truth, choice, strict=True):
        confusion[t][c or "abstain"] += 1
    silent = sum(1 for t, c, r in zip(truth, choice, route, strict=True) if r == "auto" and c != t)
    silent_side = sum(1 for t, c, r in zip(truth, choice, route, strict=True) if r == "auto" and (c in SCAM) != (t in SCAM))
    answered = [i for i in range(n) if choice[i] is not None]
    bins: list[dict[str, Any]] = []
    for low in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        high = {0.0: 0.5, 0.5: 0.6, 0.6: 0.7, 0.7: 0.8, 0.8: 0.9, 0.9: 0.95, 0.95: 1.01}[low]
        members = [i for i in range(n) if low <= max(results[i].decision.probabilities.values()) < high]
        if members:
            top = [max(results[i].decision.probabilities, key=lambda k: results[i].decision.probabilities[k]) for i in members]
            acc = sum(1 for i, label in zip(members, top, strict=True) if label == truth[i]) / len(members)
            conf = sum(max(results[i].decision.probabilities.values()) for i in members) / len(members)
            bins.append({"from": low, "to": min(high, 1.0), "n": len(members), "accuracy": round(acc, 4), "confidence": round(conf, 4)})
    ece = sum(b["n"] * abs(b["accuracy"] - b["confidence"]) for b in bins) / n if n else 0.0
    return {
        "messages": n,
        "abstention_rate": _rate(sum(1 for c in choice if c is None), n),
        "false_alarm_rate": _rate(sum(1 for i in legit if choice[i] in SCAM), len(legit)),
        "false_alarm_rate_auto": _rate(sum(1 for i in legit if choice[i] in SCAM and route[i] == "auto"), len(legit)),
        "false_alarms_on_rahat_messages": sum(1 for i in program if choice[i] in SCAM),
        "miss_rate": _rate(sum(1 for i in scams if choice[i] is not None and choice[i] not in SCAM), len(scams)),
        "caught_rate": _rate(sum(1 for i in scams if choice[i] in SCAM), len(scams)),
        "silent_guesses": silent,
        "silent_guesses_wrong_side": silent_side,
        "auto_answers": sum(1 for r in route if r == "auto"),
        "accuracy_when_answered": _rate(sum(1 for i in answered if choice[i] == truth[i]), len(answered)),
        "certainty": dict(sorted(Counter(res.certainty for res in results).items())),
        "legitimate": side_stats(legit),
        "scams": side_stats(scams),
        "per_class": per_class,
        "by_lang": by_lang,
        "confusion": {t: dict(sorted(c.items())) for t, c in sorted(confusion.items())},
        "calibration": {"ece": round(ece, 4), "bins": bins},
    }


def run(model: ScamModel | None = None, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows if rows is not None else corpus.load()
    model = model or get_model()
    test = [r for r in rows if r["split"] == "test"]
    verify = _verifier(rows)
    report: dict[str, Any] = {
        "kind": "scam", "model_version": model.version, "data_hash": model.data_hash, "params": model.params,
        "train_messages": model.n_train, "train_families": model.n_families, "trained_ms": model.trained_ms,
        "test_messages": len(test), "test_families": sorted({str(r["family"]) for r in test}),
        "synthetic": True,
    }  # fmt: skip
    for mode, verifier in (("full", verify), ("no_verify", None)):
        started = time.perf_counter()
        results = [decide(analyse(str(r["text"]), r.get("sender")), model, verify=verifier) for r in test]
        elapsed = (time.perf_counter() - started) * 1000
        report[mode] = metrics(test, results) | {"ms_per_message": round(elapsed / max(len(test), 1), 2)}
        if mode == "full":
            report["thresholds"] = results[0].thresholds if results else {}
            report["mistakes"] = [
                {"id": r["id"], "label": r["label"], "choice": res.decision.choice, "certainty": res.certainty, "route": res.decision.route}
                for r, res in zip(test, results, strict=True)
                if res.decision.choice is not None and (res.decision.choice in SCAM) != (r["label"] in SCAM)
            ][:40]
    return report


def summary(report: dict[str, Any]) -> dict[str, Any]:
    """The numbers the eval dashboard leads with."""
    keys = ("abstention_rate", "false_alarm_rate", "false_alarm_rate_auto", "false_alarms_on_rahat_messages", "miss_rate", "caught_rate",
            "silent_guesses", "silent_guesses_wrong_side", "auto_answers", "accuracy_when_answered", "messages")  # fmt: skip
    out: dict[str, Any] = {"model_version": report["model_version"], "synthetic": True, "test_families": len(report["test_families"])}
    for mode in ("full", "no_verify"):
        out[mode] = {k: report[mode][k] for k in keys} | {"ece": report[mode]["calibration"]["ece"]}
        out[mode]["per_class"] = {label: {"precision": v["precision"], "recall": v["recall"]} for label, v in report[mode]["per_class"].items()}
    return out


def _print(report: dict[str, Any]) -> None:
    print(f"Scam checker evaluation (SYNTHETIC data). Model {report['model_version']}, trained on {report['train_messages']} messages "
          f"from {report['train_families']} families in {report['trained_ms']} ms.")  # fmt: skip
    print(f"Test: {report['test_messages']} messages from {len(report['test_families'])} families never seen in training.\n")
    for mode in ("full", "no_verify"):
        m = report[mode]
        title = "As deployed (verify codes checked)" if mode == "full" else "Model and signals alone (codes ignored)"
        print(f"== {title}")
        print(f"  abstained (not sure)          {m['abstention_rate']}")
        print(f"  false alarms on legitimate    {m['false_alarm_rate']}  (auto: {m['false_alarm_rate_auto']}; "
              f"on Rahat messages: {m['false_alarms_on_rahat_messages']})")
        print(f"  missed scams (called real)    {m['miss_rate']}")
        print(f"  scams caught                  {m['caught_rate']}")
        print(f"  silent guesses (auto, wrong)  {m['silent_guesses']} of {m['auto_answers']} auto answers; "
              f"wrong side: {m['silent_guesses_wrong_side']}")
        print(f"  accuracy when answered        {m['accuracy_when_answered']}   ECE {m['calibration']['ece']}   {m['ms_per_message']} ms/message")
        print(f"  certainty                     {m['certainty']}")
        print("  class                   precision  recall  support")
        for label, v in m["per_class"].items():
            print(f"  {label:<24}{v['precision']!s:<11}{v['recall']!s:<8}{v['support']}")
        print("  language   n     abstain  false_alarm  miss    caught")
        for lang, v in m["by_lang"].items():
            print(f"  {lang:<10}{v['n']:<6}{v['abstention_rate']!s:<9}{v['false_alarm_rate']!s:<13}{v['miss_rate']!s:<8}{v['caught_rate']}")
        print()  # fmt: skip


def store(report: dict[str, Any], tenant_slug: str | None = None) -> int:
    """One eval_runs row (kind scam) per department (or the one named), an audit row each, and the model in the registry."""
    from sqlalchemy import select

    from app.core import audit
    from app.core.db import system_session
    from app.db import models

    stored = 0
    with system_session() as db:  # narrow: a CLI writing evaluation rows, like the seed
        query = select(models.Tenant).order_by(models.Tenant.slug)
        query = query.where(models.Tenant.slug == tenant_slug) if tenant_slug else query.where(models.Tenant.kind == "department")
        for tenant in db.scalars(query).all():
            run_id = uuid.uuid4()
            db.add(models.EvalRun(id=run_id, tenant_id=tenant.id, kind="scam", model_version=report["model_version"], status="done",
                                  metrics=summary(report), artifacts={k: report[k] for k in ("full", "no_verify", "thresholds", "test_families",
                                                                                              "params", "mistakes")}))  # fmt: skip
            registry = db.scalar(select(models.ModelRegistry).where(models.ModelRegistry.tenant_id == tenant.id, models.ModelRegistry.name == "scam",
                                                                    models.ModelRegistry.version == report["model_version"]))  # fmt: skip
            if registry is None:
                db.add(models.ModelRegistry(tenant_id=tenant.id, name="scam", version=report["model_version"], kind="classifier",
                                            data_hash=report["data_hash"], params=report["params"], metrics=summary(report), status="active",
                                            card="Character n-gram TF-IDF and logistic regression, stacked with link, sender and money signals. "
                                                 "Trained and tested on synthetic messages split by template family."))  # fmt: skip
            else:
                registry.metrics = summary(report)
            db.flush()
            audit.write(db, tenant_id=tenant.id, action="eval.recorded", actor_type="system", object_type="eval_run", object_id=run_id,
                        model_version=report["model_version"], details={"kind": "scam", "test_messages": report["test_messages"]})  # fmt: skip
            stored += 1
    return stored


def main(argv: list[str]) -> int:
    report = run()
    if "--json" in argv:
        print(json.dumps(summary(report), indent=2))
    else:
        _print(report)
    if "--no-db" not in argv:
        slug = argv[argv.index("--tenant") + 1] if "--tenant" in argv and argv.index("--tenant") + 1 < len(argv) else None
        try:
            print(f"stored in eval_runs for {store(report, slug)} tenant(s)")
        except Exception as exc:  # noqa: BLE001  (printing the numbers must not depend on a database)
            print(f"not stored: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
