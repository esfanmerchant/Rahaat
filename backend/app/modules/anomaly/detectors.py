"""Anomaly detectors: pure functions over plain records. No database, no clock, no random source.

    result = detect_shared_payout(records)                      # one wallet, three or more households
    result = detect_application_spike(records, today=date(...)) # a district's daily count against its own robust baseline
    result = detect_helper_burst(records)                       # one helper submitting for many families in a short window
    result = detect_repeated_identity(records)                  # one mock national ID on several people, or tried many times

Each detector returns a `DetectorResult`. Every finding carries a `TypedDecision` that is always routed to a
person ("human"): an anomaly is a guard that sends a case to review, never a reason to reject anyone. A
detector that does not have enough data abstains and says why, instead of reporting "all clear".

Confidences here are documented heuristic scores (they grow with the size of the pattern), not calibrated
probabilities. How often each detector is right is measured on a labelled synthetic dataset
(`python -m app.modules.anomaly.evaluate`) and reported in docs/EVAL_REPORT.md.

Identifiers arrive already fingerprinted by the service (a keyed hash), so an evidence chip never shows a
raw national ID, phone number or account.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from app.contracts.decision import TypedDecision

MODEL_VERSION: Final = "anomaly-1"
DETECTORS: Final = ("shared_payout", "application_spike", "helper_burst", "repeated_identity")
DetectorName = Literal["shared_payout", "application_spike", "helper_burst", "repeated_identity"]
Status = Literal["flagged", "clear", "abstained"]

TITLES: Final[dict[str, str]] = {
    "shared_payout": "One payout account for several households",
    "application_spike": "Applications from one district jumped",
    "helper_burst": "One helper submitted for many families in a short time",
    "repeated_identity": "One ID number used again and again",
}
# What a person can do to settle each pattern with one check (staff view only).
CHEAPEST_CHECK: Final[dict[str, str]] = {
    "shared_payout": "Ask the payout provider for the account holder's name and compare it with the applicants. "
    "Related people sharing one wallet is fine.",
    "application_spike": "Look at where the applications came from (channel and helper). "
    "A real announcement or a camp in that district explains a jump.",
    "helper_burst": "Phone the helper and spot-check three of these families to confirm each one asked for help.",
    "repeated_identity": "Compare the applicants' names and dates of birth against the registry. "
    "One person re-trying is different from two people using one ID.",
}


@dataclass(frozen=True, slots=True)
class AppRecord:
    """The few facts a detector needs about one application. `payout` and `national_id` are fingerprints, never raw values."""

    app_id: str
    person_id: str
    at: datetime
    district: str | None = None
    payout: str | None = None
    national_id: str | None = None
    helper_id: str | None = None  # the signed-in helper when the application was submitted through Helper Mode
    household: str | None = None
    status: str = "submitted"

    @property
    def day(self) -> date:
        return self.at.date()

    @property
    def unit(self) -> str:
        """The household, or the person when no household is known: two members of one household are one unit."""
        return self.household or self.person_id


class Finding(BaseModel):
    detector: DetectorName
    pattern_key: str = Field(description="Stable key of the pattern: the same pattern always has the same key, so one pattern opens one case")
    decision: TypedDecision[str]
    title: str
    summary_code: str
    evidence: dict[str, Any] = Field(default_factory=dict, description="Numbers and short labels shown as chips; never raw identifiers")
    evidence_ids: list[str] = Field(default_factory=list, description="Application ids behind the pattern")
    cheapest_check: str
    priority: int = Field(description="Case priority, 0 is most urgent")

    @property
    def confidence(self) -> float:
        return self.decision.confidence


class DetectorResult(BaseModel):
    detector: DetectorName
    status: Status
    findings: list[Finding] = Field(default_factory=list)
    abstention: TypedDecision[str] | None = Field(default=None, description="Set when the detector did not have enough data")
    data_points: dict[str, Any] = Field(default_factory=dict, description="What the detector looked at, so an empty result can be read")
    params: dict[str, Any] = Field(default_factory=dict)


def _flag(
    detector: DetectorName, key: str, confidence: float, reasons: list[str], *, evidence: dict[str, Any], ids: Iterable[str], priority: int
) -> Finding:
    confidence = round(max(0.0, min(0.99, confidence)), 3)
    decision = TypedDecision[str](
        choice="anomaly",
        probabilities={"anomaly": confidence, "normal": round(1 - confidence, 3)},
        confidence=confidence,
        route="human",
        reasons=reasons,
        model_version=MODEL_VERSION,
    )
    return Finding(
        detector=detector,
        pattern_key=key,
        decision=decision,
        title=TITLES[detector],
        summary_code=reasons[0],
        evidence=evidence,
        evidence_ids=sorted(set(ids)),
        cheapest_check=CHEAPEST_CHECK[detector],
        priority=priority,
    )


def _abstain(detector: DetectorName, reason: str, data: dict[str, Any], params: dict[str, Any]) -> DetectorResult:
    decision = TypedDecision[str](choice=None, confidence=0.0, route="ask_more", reasons=[reason], model_version=MODEL_VERSION, abstained=True)
    return DetectorResult(detector=detector, status="abstained", abstention=decision, data_points=data, params=params)


def _result(detector: DetectorName, findings: list[Finding], data: dict[str, Any], params: dict[str, Any]) -> DetectorResult:
    findings = sorted(findings, key=lambda f: (f.priority, -f.confidence, f.pattern_key))
    return DetectorResult(detector=detector, status="flagged" if findings else "clear", findings=findings, data_points=data, params=params)


def short(fingerprint: str) -> str:
    """The label an officer sees for a fingerprinted identifier: enough to tell two apart, not enough to look anything up."""
    return f"fp-{fingerprint[:8]}"


# --- (a) shared payout -----------------------------------------------------------------------------------


def detect_shared_payout(records: Sequence[AppRecord], *, min_people: int = 3, min_units: int = 2) -> DetectorResult:
    """One payout account used by `min_people` or more different people who do not all live in one household.

    Relatives often share one wallet, so people from a single household are not flagged. A ring is the
    same account behind several unrelated households.
    """
    params = {"min_people": min_people, "min_units": min_units}
    with_payout = [r for r in records if r.payout]
    if not with_payout:
        return _abstain("shared_payout", "no_payout_data", {"applications": len(records), "with_payout_account": 0}, params)
    groups: dict[str, list[AppRecord]] = defaultdict(list)
    for r in with_payout:
        groups[r.payout or ""].append(r)
    findings: list[Finding] = []
    for account, rows in groups.items():
        people = {r.person_id for r in rows}
        units = {r.unit for r in rows}
        if len(people) < min_people or len(units) < min_units:
            continue
        districts = sorted({r.district for r in rows if r.district})
        confidence = 0.55 + 0.1 * (len(units) - min_units) + 0.03 * (len(people) - min_people)
        findings.append(
            _flag(
                "shared_payout",
                f"shared_payout:{account}",
                confidence,
                ["payout_account_shared"],
                evidence={"account": short(account), "people": len(people), "households": len(units), "districts": ", ".join(districts)},
                ids=(r.app_id for r in rows),
                priority=15 if len(units) >= 6 else 30,
            )
        )
    return _result(
        "shared_payout", findings, {"applications": len(records), "with_payout_account": len(with_payout), "accounts": len(groups)}, params
    )


# --- (b) application spike --------------------------------------------------------------------------------


def _robust_baseline(counts: Sequence[int]) -> tuple[float, float]:
    """Median and a robust scale: 1.4826 x MAD, never below the Poisson spread sqrt(median) (a quiet district has MAD 0)."""
    median = float(statistics.median(counts))
    mad = float(statistics.median(abs(c - median) for c in counts))
    return median, max(1.4826 * mad, max(median, 1.0) ** 0.5)


def detect_application_spike(
    records: Sequence[AppRecord],
    *,
    today: date,
    baseline_days: int = 14,
    min_baseline_days: int = 7,
    z_threshold: float = 3.5,
    min_count: int = 8,
    eval_days: int = 1,
) -> DetectorResult:
    """A district's applications on a day, against its own previous `baseline_days` (a robust z-score).

    Abstains when the data set covers fewer than `min_baseline_days` days before the day tested: a spike
    cannot be told from a quiet start without a baseline. `today` is passed in; the function reads no clock.
    """
    params = {
        "baseline_days": baseline_days,
        "min_baseline_days": min_baseline_days,
        "z_threshold": z_threshold,
        "min_count": min_count,
        "eval_days": eval_days,
    }
    dated = [r for r in records if r.district]
    if not dated:
        return _abstain("application_spike", "no_district_data", {"applications": len(records)}, params)
    first = min(r.day for r in dated)
    history = (today - first).days
    if history < min_baseline_days:
        return _abstain(
            "application_spike",
            "thin_baseline",
            {"history_days": max(history, 0), "needed_days": min_baseline_days, "applications": len(dated)},
            params,
        )
    per_district: dict[str, dict[date, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in dated:
        per_district[r.district or ""][r.day].append(r.app_id)
    findings: list[Finding] = []
    tested = 0
    for district, by_day in sorted(per_district.items()):
        for offset in range(eval_days):
            day = today - timedelta(days=offset)
            start = max(first, day - timedelta(days=baseline_days))
            window = [(start + timedelta(days=i)) for i in range((day - start).days)]
            if len(window) < min_baseline_days:
                continue
            tested += 1
            baseline = [len(by_day.get(d, [])) for d in window]
            median, scale = _robust_baseline(baseline)
            count = len(by_day.get(day, []))
            z = (count - median) / scale
            if count >= min_count and z >= z_threshold:
                findings.append(
                    _flag(
                        "application_spike",
                        f"application_spike:{district}:{day.isoformat()}",
                        0.5 + 0.05 * (z - z_threshold),
                        ["application_spike"],
                        evidence={
                            "district": district,
                            "day": day.isoformat(),
                            "applications": count,
                            "usual_per_day": round(median, 1),
                            "robust_z": round(z, 1),
                            "baseline_days": len(window),
                        },
                        ids=by_day.get(day, []),
                        priority=30,
                    )
                )
    return _result("application_spike", findings, {"history_days": history, "districts": len(per_district), "district_days_tested": tested}, params)


# --- (c) helper burst ------------------------------------------------------------------------------------


def detect_helper_burst(records: Sequence[AppRecord], *, window_minutes: int = 60, min_families: int = 10) -> DetectorResult:
    """One helper submitting for `min_families` or more different people inside `window_minutes`.

    A community helper may serve forty families over weeks, so only the rate is unusual. Abstains when the
    whole data set has fewer helper submissions than the threshold (there is nothing to compare).
    """
    params = {"window_minutes": window_minutes, "min_families": min_families}
    helped = [r for r in records if r.helper_id]
    if len(helped) < min_families:
        return _abstain("helper_burst", "thin_helper_data", {"helper_submissions": len(helped), "needed": min_families}, params)
    by_helper: dict[str, list[AppRecord]] = defaultdict(list)
    for r in helped:
        by_helper[r.helper_id or ""].append(r)
    window = timedelta(minutes=window_minutes)
    merged: dict[str, dict[str, Any]] = {}
    for helper, rows in by_helper.items():
        rows.sort(key=lambda r: (r.at, r.app_id))
        i = 0
        while i < len(rows):
            j = i
            while j + 1 < len(rows) and rows[j + 1].at - rows[i].at <= window:
                j += 1
            if len({r.person_id for r in rows[i : j + 1]}) >= min_families:
                while j + 1 < len(rows) and rows[j + 1].at - rows[j].at <= window / 4:  # the same burst going on, not a new one
                    j += 1
                chunk = rows[i : j + 1]
                key = f"helper_burst:{helper}:{chunk[0].day.isoformat()}"
                entry = merged.setdefault(key, {"ids": set(), "people": set(), "first": chunk[0].at, "last": chunk[-1].at, "helper": helper})
                entry["ids"].update(r.app_id for r in chunk)
                entry["people"].update(r.person_id for r in chunk)
                entry["first"], entry["last"] = min(entry["first"], chunk[0].at), max(entry["last"], chunk[-1].at)
                i = j + 1
            else:
                i += 1
    findings = []
    for key, entry in merged.items():
        families = len(entry["people"])
        minutes = max(1, round((entry["last"] - entry["first"]).total_seconds() / 60))
        findings.append(
            _flag(
                "helper_burst",
                key,
                0.5 + 0.04 * (families - min_families),
                ["helper_burst"],
                evidence={
                    "helper": short(entry["helper"].replace("-", "")),
                    "families": families,
                    "minutes": minutes,
                    "from": entry["first"].isoformat(timespec="minutes"),
                },
                ids=entry["ids"],
                priority=25,
            )
        )
    return _result("helper_burst", findings, {"helper_submissions": len(helped), "helpers": len(by_helper)}, params)


# --- (d) repeated identity --------------------------------------------------------------------------------


def detect_repeated_identity(records: Sequence[AppRecord], *, min_attempts: int = 3) -> DetectorResult:
    """The same mock national ID on applications of two or more different people, or tried `min_attempts` times or more."""
    params = {"min_attempts": min_attempts}
    with_id = [r for r in records if r.national_id]
    if not with_id:
        return _abstain("repeated_identity", "no_identity_data", {"applications": len(records), "with_national_id": 0}, params)
    groups: dict[str, list[AppRecord]] = defaultdict(list)
    for r in with_id:
        groups[r.national_id or ""].append(r)
    findings = []
    for identity, rows in groups.items():
        people = {r.person_id for r in rows}
        refused = sum(1 for r in rows if r.status in ("rejected", "withdrawn"))
        if len(people) >= 2:
            code, confidence = "identity_on_several_people", 0.75 + 0.05 * (len(people) - 2)
        elif len(rows) >= min_attempts:
            code, confidence = "identity_many_attempts", 0.55 + 0.05 * (len(rows) - min_attempts)
        else:
            continue
        findings.append(
            _flag(
                "repeated_identity",
                f"repeated_identity:{identity}",
                confidence,
                [code],
                evidence={"id": short(identity), "people": len(people), "attempts": len(rows), "refused": refused},
                ids=(r.app_id for r in rows),
                priority=20 if len(people) >= 2 else 35,
            )
        )
    return _result("repeated_identity", findings, {"applications": len(records), "with_national_id": len(with_id), "ids": len(groups)}, params)


def run_all(records: Sequence[AppRecord], *, today: date) -> list[DetectorResult]:
    """All four detectors over the same records, in a fixed order."""
    return [
        detect_shared_payout(records),
        detect_application_spike(records, today=today),
        detect_helper_burst(records),
        detect_repeated_identity(records),
    ]
