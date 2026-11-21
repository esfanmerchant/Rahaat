"""DB-free tests for the pulse aggregation and shaping."""

from __future__ import annotations

from app.modules.pulse import shaping as S


def test_count_map_fills_zeros_and_folds_unknown_statuses() -> None:
    out = S.count_map([("paid", 3), ("approved", 2), ("mystery", 4)], S.APPLICATION_STATUSES)
    assert out["paid"] == 3 and out["approved"] == 2 and out["draft"] == 0 and out["other"] == 4
    assert sum(out.values()) == 9


def test_decisions_by_route_splits_hard_rule_rejection_from_auto_approval() -> None:
    out = S.decisions_by_route([("auto", "approved", 5), ("auto", "rejected", 2), ("ask_more", "needs_proof", 3), ("human", "needs_human", 7)])
    assert out == {"auto": 5, "ask_more": 3, "human": 7, "reject": 2}


def test_payments_sent_includes_settled_and_sums_amounts() -> None:
    out = S.payments_shape([("submitted", 2, 20000), ("settled", 3, 30000), ("failed", 1, 10000), ("pending_approval", 4, 40000)])
    assert out == {"sent": 5, "sent_amount_pkr": 50000, "settled": 3, "settled_amount_pkr": 30000}


def test_scam_blocked_counts_only_scam_labels() -> None:
    assert S.scam_shape([("relief_scam", 4), ("legit_program_message", 5), ("unknown", 1)]) == {"reports": 10, "blocked": 4}


def test_correct_never_counts_a_deferral_as_wrong() -> None:
    assert S.correct_of("approve", ok=False, eligible=True) is False
    assert S.correct_of("approve", ok=True, eligible=True) is True
    assert S.correct_of("reject", ok=False, eligible=False) is True
    assert S.correct_of("reject", ok=False, eligible=True) is False
    assert S.correct_of("human", ok=False, eligible=False) and S.correct_of("ask_proof", ok=True, eligible=True)


def test_replay_row_has_only_the_agreed_keys_and_rounds() -> None:
    row = S.replay_row("ask_proof", p_ok=0.123456, ok=False, eligible=True, kind="not_genuine", code="ask_proof.income_proof")
    assert set(row) == {"route", "outcome", "p_ok", "correct", "reason_code", "kind"}
    assert row["route"] == "ask_more" and row["outcome"] == "needs_proof" and row["p_ok"] == 0.1235


def test_sample_is_even_deterministic_and_capped() -> None:
    rows = list(range(5000))
    picked = S.sample(rows, 2000)
    assert len(picked) == 2000 and picked == S.sample(rows, 2000) and picked[0] == 0 and picked == sorted(set(picked))
    assert S.sample(rows[:10], 2000) == rows[:10] and S.sample(rows, 0) == []


def test_reason_code_prefers_guards() -> None:
    assert S.reason_code("human", ("fraud_signal",), None, 0.2, 0.968) == "guard.fraud_signal"
    assert S.reason_code("human", (), None, 0.5, 0.968) == "cost.approve_below_threshold"
    assert S.reason_code("approve", (), None, 0.99, 0.968) == "rules.all_hard_verified_pass"
