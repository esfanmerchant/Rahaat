"""DB-free tests of the field-level merge for offline edits."""

from __future__ import annotations

import json

from app.modules.sync.merge import fields_changed_after, plan_patch

SERVER = {
    "language": "ur",
    "household_size": {"value": 6, "confidence": 1.0, "provenance": "typed", "verified": False},
    "income_band": {"value": None, "confidence": 0.0, "provenance": "tapped", "verified": False},
    "full_name": {"value": "Zainab Bibi", "confidence": 1.0, "provenance": "qr_signed", "verified": True},
    "phone": {"value": "0999-0000201", "confidence": 1.0, "provenance": "typed", "verified": False},
}


def test_changed_fields_come_from_edits_after_the_base_version() -> None:
    rows = [
        json.dumps({"fields": ["household_size"], "version": 2}),
        json.dumps({"fields": ["income_band", "is_widow"], "version": 4}),
        {"fields": ["district"], "version": 3},
        "not json",
        json.dumps({"fields": ["gender"]}),  # no version: counted as changed, to be safe
    ]
    assert fields_changed_after(rows, 3) == {"income_band", "is_widow", "gender"}
    assert fields_changed_after(rows, 1) == {"household_size", "income_band", "is_widow", "district", "gender"}
    assert fields_changed_after([], 1) == set()


def test_untouched_fields_apply_and_real_conflicts_keep_the_server_value() -> None:
    patch = {
        "income_band": {"value": "under_15k", "provenance": "tapped"},  # nobody touched it: applies
        "household_size": {"value": 4, "provenance": "tapped"},  # someone set 6 since: conflict
        "phone": {"value": "09990000201", "provenance": "typed"},  # same number, other spelling: nothing to do
    }
    plan = plan_patch(SERVER, patch, changed={"household_size"}, locked=set(),
                      normalise=lambda n, v: v.replace("-", "") if n == "phone" and isinstance(v, str) else v)  # fmt: skip
    assert set(plan.accepted) == {"income_band"}
    assert plan.unchanged == ["phone"]
    assert [c.as_dict() for c in plan.conflicts] == [
        {"field": "household_size", "server_value": SERVER["household_size"], "your_value": 4, "reason": "changed_since_your_version"}
    ]


def test_the_same_change_twice_is_not_a_conflict() -> None:
    plan = plan_patch(SERVER, {"household_size": {"value": 6}}, changed={"household_size"}, locked=set())
    assert plan.unchanged == ["household_size"] and not plan.conflicts and not plan.accepted


def test_a_verified_field_is_never_overwritten_from_a_device() -> None:
    plan = plan_patch(SERVER, {"full_name": {"value": "Zenab Bibi", "provenance": "typed"}}, changed=set(), locked={"full_name"})
    assert not plan.accepted and plan.conflicts[0].reason == "field_locked"
    same = plan_patch(SERVER, {"full_name": {"value": "Zainab Bibi"}}, changed=set(), locked={"full_name"})
    assert same.unchanged == ["full_name"] and not same.conflicts


def test_language_merges_like_a_field() -> None:
    assert plan_patch(SERVER, {"language": "en"}, changed=set(), locked=set()).accepted == {"language": "en"}
    assert plan_patch(SERVER, {"language": "en"}, changed={"language"}, locked=set()).conflicts[0].server_value == "ur"
    assert plan_patch(SERVER, {"language": "ur"}, changed={"language"}, locked=set()).unchanged == ["language"]
