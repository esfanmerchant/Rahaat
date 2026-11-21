"""Measure the anomaly detectors on a synthetic month with injected anomalies.

    cd backend && uv run python -m app.modules.anomaly.evaluate            # seeds 20261201 .. 20261205, prints JSON
    cd backend && uv run python -m app.modules.anomaly.evaluate --seeds 1  # one seed (the first)

DB-free and deterministic. A finding is a true positive when it covers at least half of an injected
pattern's applications and at least 30% of the finding is that pattern (a spike finding also holds the
district's normal traffic that day). A spike that an injected ring or helper burst caused counts as a correct spike flag.
Every injected pattern a finding covers counts as found; a pattern no
finding covers is missed; a finding that covers no injected pattern is a false alarm.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import timedelta
from typing import Any

from app.modules.anomaly import detectors as D
from app.synth.anomaly_world import DAYS, SEED, AnomalyWorld, Truth, build_anomaly_world

TRUTH_COVERAGE = 0.5
FINDING_PURITY = 0.3
GENERATOR_SEEDS = tuple(SEED + i for i in range(5))


def _overlaps(finding: D.Finding, truth: Truth) -> bool:
    ids = set(finding.evidence_ids)
    common = len(ids & truth.app_ids)
    return common / len(truth.app_ids) >= TRUTH_COVERAGE and common / max(len(ids), 1) >= FINDING_PURITY


def score_detector(result: D.DetectorResult, world: AnomalyWorld) -> dict[str, Any]:
    truths = [t for t in world.truth if t.detector == result.detector]
    negatives = [t for t in world.hard_negatives if t.detector == result.detector]
    found = [t for t in truths if any(_overlaps(f, t) for f in result.findings)]
    # A district spike made by an injected ring or helper burst is a real spike: it is not a false alarm for the spike detector.
    explainers = world.truth if result.detector == "application_spike" else truths
    true_findings = [f for f in result.findings if any(_overlaps(f, t) for t in explainers)]
    false_findings = [f for f in result.findings if f not in true_findings]
    hard_negative_hits = [
        t for t in negatives if any(len(set(f.evidence_ids) & t.app_ids) / len(t.app_ids) >= TRUTH_COVERAGE for f in false_findings)
    ]
    flagged = len(result.findings)
    return {
        "detector": result.detector,
        "status": result.status,
        "injected": len(truths),
        "found": len(found),
        "missed": len(truths) - len(found),
        "flags": flagged,
        "false_alarms": len(false_findings),
        "precision": round(len(true_findings) / flagged, 3) if flagged else None,
        "recall": round(len(found) / len(truths), 3) if truths else None,
        "false_alarms_per_1000_applications": round(1000 * len(false_findings) / len(world.records), 2),
        "benign_lookalikes": len(negatives),
        "benign_lookalikes_wrongly_flagged": len(hard_negative_hits),
        "abstained_reason": result.abstention.reasons[0] if result.abstention else None,
    }


def run_world(seed: int) -> dict[str, Any]:
    world = build_anomaly_world(seed)
    today = (world.today).date()
    results = [
        D.detect_shared_payout(world.records),
        D.detect_application_spike(world.records, today=today, eval_days=DAYS - 8),
        D.detect_helper_burst(world.records),
        D.detect_repeated_identity(world.records),
    ]  # fmt: skip
    spike = results[1]
    per_detector = [score_detector(r, world) for r in results]
    for row in per_detector:
        if row["detector"] == "application_spike":
            tested = spike.data_points.get("district_days_tested") or 1
            row["false_alarms_per_100_district_days"] = round(100 * row["false_alarms"] / tested, 2)
    first_day = world.records[0].day
    thin = D.detect_application_spike([r for r in world.records if (r.day - first_day).days < 5], today=first_day + timedelta(days=4))
    return {
        "seed": seed, "applications": len(world.records), "injected": len(world.truth), "benign_lookalikes": len(world.hard_negatives),
        "detectors": per_detector, "thin_data_check": {"status": thin.status, "reason": thin.abstention.reasons[0] if thin.abstention else None},
    }  # fmt: skip


def summarise(runs: list[dict[str, Any]]) -> dict[str, Any]:
    pooled: dict[str, dict[str, Any]] = defaultdict(lambda: {"injected": 0, "found": 0, "flags": 0, "false_alarms": 0, "apps": 0})
    for run in runs:
        for row in run["detectors"]:
            p = pooled[row["detector"]]
            p["injected"] += row["injected"]
            p["found"] += row["found"]
            p["flags"] += row["flags"]
            p["false_alarms"] += row["false_alarms"]
            p["apps"] += run["applications"]
    out = {}
    for name, p in pooled.items():
        true_flags = p["flags"] - p["false_alarms"]
        out[name] = {
            "injected": p["injected"], "found": p["found"], "flags": p["flags"], "false_alarms": p["false_alarms"],
            "precision": round(true_flags / p["flags"], 3) if p["flags"] else None, "recall": round(p["found"] / p["injected"], 3),
            "false_alarms_per_1000_applications": round(1000 * p["false_alarms"] / p["apps"], 2),
        }  # fmt: skip
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seeds", type=int, default=len(GENERATOR_SEEDS), help="how many seeds to run, starting at the first")
    args = parser.parse_args()
    runs = [run_world(seed) for seed in GENERATOR_SEEDS[: max(1, args.seeds)]]
    print(
        json.dumps(
            {"generator": "anomaly-world-1", "first_seed": runs[0], "pooled_over_seeds": summarise(runs), "seeds": [r["seed"] for r in runs]},
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
