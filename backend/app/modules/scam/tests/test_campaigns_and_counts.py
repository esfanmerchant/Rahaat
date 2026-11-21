"""Campaign signatures, k-anonymity, districts, the rate limiter and the evaluation arithmetic. DB-free."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from app.modules.scam import aggregates, clustering, ratelimit
from app.modules.scam.districts import normalise_district
from app.modules.scam.evaluate import metrics

A = "Mubarak ho! Aap ka naam Rahat program mein aa gaya hai. 25000 rupay hasil karne ke liye 500 rupay fee is number 0999-1234567 par bhejein."
B = "mubarak ho! ap ka nam Rahat Relief main aa gaya hai. 12,000 rupees hasil karne k liye 1500 rupay fee is number 0999 7654321 pe bhejen"
C = "Your parcel could not be delivered due to an incomplete address. Pay Rs 200 redelivery fee at bit.ly/abc123"


def test_variants_of_one_template_join_one_campaign_and_others_do_not() -> None:
    a, b, c = clustering.minhash(A), clustering.minhash(B), clustering.minhash(C)
    assert clustering.similarity(a, b) >= clustering.JOIN_AT
    assert clustering.similarity(a, c) < 0.2
    assert clustering.best_match(b, [("parcel", c), ("relief", a)]) == ("relief", clustering.similarity(a, b))


def test_signatures_are_stable() -> None:
    assert clustering.minhash(A) == clustering.minhash(A)
    assert clustering.signature(clustering.minhash(A)) == clustering.signature(clustering.minhash(A))
    assert clustering.signature(clustering.minhash(A)).startswith("mh1:") and len(clustering.signature(clustering.minhash(A))) <= 128
    assert clustering.template_hash("Send Rs 500 to 0999-1112223") == clustering.template_hash("send rs 900 to 0999-4445556")


def test_groups_under_k_are_hidden_and_zero_is_shown_as_zero() -> None:
    shown, hidden = aggregates.suppress([(("Karachi East", "relief_scam", "2026-11-20"), 6), (("Hyderabad", "relief_scam", "2026-11-20"), 3),
                                         (("Sukkur", "phishing_link", "2026-11-19"), 5), (("Larkana", "advance_fee", "2026-11-19"), 0)])  # fmt: skip
    assert [key[0] for key, _ in shown] == ["Karachi East", "Sukkur"] and hidden == 1
    series = aggregates.day_series({"2026-11-19": 7, "2026-11-20": 2}, date(2026, 11, 18), date(2026, 11, 20))
    assert series == [("2026-11-18", 0), ("2026-11-19", 7), ("2026-11-20", None)]
    assert aggregates.rollup([(("A", "x", "d1"), 3), (("A", "y", "d1"), 4), (("B", "x", "d2"), 1)], (0,)) == {("A",): 7, ("B",): 1}


def test_the_window_is_calendar_days_in_pakistan_time() -> None:
    first, last, since = aggregates.window(14, now=datetime(2026, 11, 21, 20, 0, tzinfo=UTC))  # 01:00 on the 22nd in Karachi
    assert (first, last) == (date(2026, 11, 9), date(2026, 11, 22))
    assert since == datetime(2026, 11, 8, 19, 0, tzinfo=UTC)


def test_only_known_districts_are_kept() -> None:
    assert normalise_district("karachi  east") == "Karachi East"
    assert normalise_district("House 12, Street 4, Gulshan") is None, "an address is never stored"
    assert normalise_district(None) is None


def test_rate_limiter_window() -> None:
    window = ratelimit.SlidingWindow()
    assert window.hit("u", 2, now=0.0) is None and window.hit("u", 2, now=1.0) is None
    wait = window.hit("u", 2, now=2.0)
    assert wait is not None and 57.0 <= wait <= 58.0
    assert window.hit("u", 2, now=61.0) is None, "the oldest hit has left the window"


def _result(choice: str | None, route: str, top: float = 0.9) -> Any:
    probs = {label: (1 - top) / 5 for label in ("relief_scam", "phishing_link", "advance_fee", "impersonation", "legit_program_message", "unknown")}
    probs[choice or "unknown"] = top
    certainty = "not_sure" if choice is None else "likely_scam" if choice in ("relief_scam", "advance_fee") else "looks_real"
    return SimpleNamespace(decision=SimpleNamespace(choice=choice, route=route, probabilities=probs), certainty=certainty)


def test_evaluation_counts_false_alarms_misses_abstentions_and_silent_guesses() -> None:
    rows = [{"label": "relief_scam", "lang": "en"}, {"label": "relief_scam", "lang": "ur"}, {"label": "unknown", "lang": "roman"},
            {"label": "legit_program_message", "lang": "en"}, {"label": "advance_fee", "lang": "en"}]  # fmt: skip
    results = [_result("relief_scam", "auto"), _result(None, "human"), _result("relief_scam", "human"), _result("legit_program_message", "auto"),
               _result("relief_scam", "auto")]  # fmt: skip
    report = metrics(rows, results)
    assert report["abstention_rate"] == 0.2
    assert report["false_alarm_rate"] == 0.5 and report["false_alarm_rate_auto"] == 0.0
    assert report["miss_rate"] == 0.0 and report["caught_rate"] == round(2 / 3, 4)
    assert report["silent_guesses"] == 1 and report["silent_guesses_wrong_side"] == 0, "advance fee called relief scam: right side, wrong kind"
    assert report["per_class"]["relief_scam"]["precision"] == round(1 / 3, 4)
