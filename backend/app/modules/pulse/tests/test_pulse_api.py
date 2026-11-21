"""The public pulse API: open, aggregate only, cached. Uses Postgres."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.modules.decision.tests.dbsetup import make_program
from app.modules.pulse import service

TOP_KEYS = {"generated_at", "cache_seconds", "notice", "live", "replay", "elapsed_ms"}
LIVE_KEYS = {"applications_by_status", "decisions_by_route", "payments", "scam", "audit_chain_length", "departments"}
REPLAY_KEYS = {"available", "replay_source", "rule_version_no", "model_version", "cases_scored", "cases", "headline"}
CASE_KEYS = {"route", "outcome", "p_ok", "correct", "reason_code", "kind"}
FORBIDDEN = ("name", "phone", "national", "tracking", "email", "person_id", "application_id", "user_id", "cnic")


@pytest.fixture()
def demo_tenant(factory: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    tenant = factory.tenant()
    make_program(tenant.id)
    monkeypatch.setattr(service, "demo_slugs", lambda: [tenant.slug])
    service.reset_cache()
    yield tenant
    service.reset_cache()


def test_pulse_is_public_aggregate_only_and_scored_by_the_live_engine(client: TestClient, demo_tenant: Any) -> None:
    response = client.get("/v1/public/pulse")  # no credentials
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == TOP_KEYS and set(body["live"]) == LIVE_KEYS and set(body["replay"]) == REPLAY_KEYS
    replay = body["replay"]
    assert replay["available"] and replay["replay_source"] == "synthetic labelled eval set"
    assert 1 <= len(replay["cases"]) <= 2000 and all(set(c) == CASE_KEYS for c in replay["cases"])
    head = replay["headline"]
    assert head["silent_guesses"] == 0 and head["cases"] == replay["cases_scored"] >= 1000
    assert (
        head["wrong_approvals"] == sum(1 for c in replay["cases"] if c["outcome"] == "approved" and not c["correct"]) or replay["cases_scored"] > 2000
    )
    assert 0 < head["thresholds"]["reject"] < head["thresholds"]["approve"] <= 1
    keys = {k.lower() for k in _all_keys(body)}
    assert not [k for k in keys if any(bad in k for bad in FORBIDDEN)], keys
    assert body["live"]["departments"] == 1 and set(body["live"]["decisions_by_route"]) >= {"auto", "ask_more", "human", "reject"}


def test_pulse_is_cached_about_fifteen_seconds(client: TestClient, demo_tenant: Any) -> None:
    first = client.get("/v1/public/pulse").json()
    second = client.get("/v1/public/pulse").json()
    assert first["generated_at"] == second["generated_at"], "the second call must come from the cache"
    service.reset_cache()
    assert client.get("/v1/public/pulse").json()["generated_at"] != first["generated_at"]


def test_pulse_survives_a_department_without_rules(client: TestClient, factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = factory.tenant()
    monkeypatch.setattr(service, "demo_slugs", lambda: [tenant.slug])
    service.reset_cache()
    body = client.get("/v1/public/pulse").json()
    assert body["replay"]["available"] is False and body["replay"]["cases"] == [] and body["replay"]["headline"] is None
    service.reset_cache()


def _all_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value, *[k for v in value.values() for k in _all_keys(v)]]
    if isinstance(value, list):
        return [k for v in value[:50] for k in _all_keys(v)]
    return []


def test_the_body_is_json_serialisable_text_only() -> None:
    json.dumps(service.compute())
