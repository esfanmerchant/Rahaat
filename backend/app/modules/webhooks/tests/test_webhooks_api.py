"""Webhooks end to end: admin API, signed delivery to the mock receiver, retries then dead, SSRF refusals, isolation."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core import webhook_signing
from app.core.crypto import decrypt_field
from app.core.db import system_session
from app.db import models
from app.modules.cases import testing as t
from app.modules.jobs.service import run_pending
from app.modules.webhooks import rules, sender

MOCK = rules.MOCK_RECEIVER_URL


def _create(client: Any, headers: dict[str, str], events: list[str] | None = None, url: str = MOCK) -> dict[str, Any]:
    response = client.post("/v1/admin/webhooks", headers=headers, json={"url": url, "events": events or ["*"]})
    assert response.status_code == 201, response.text
    return response.json()


def _deliver(tenant_id: uuid.UUID, *, now: datetime | None = None) -> int:
    return run_pending(tenant_id=tenant_id, kinds=["webhook.deliver"], now=now)


def _deliveries(client: Any, headers: dict[str, str], webhook_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/v1/admin/webhooks/{webhook_id}/deliveries", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _receiver_config(webhook_id: str, **config: Any) -> None:
    response = sender._mock_call("PUT", f"/webhooks/config/{webhook_id}", content=json.dumps(config).encode(),
                                 headers={"Content-Type": "application/json"}, params=None, timeout=5)  # fmt: skip
    assert response.status_code == 200


@pytest.fixture()
def world(client: Any, factory: Any) -> dict[str, Any]:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    return {
        "tenant": tenant, "citizen": citizen, "admin": factory.headers(client, factory.account(tenant, "admin")),
        "officer": factory.headers(client, factory.account(tenant, "officer")),
    }  # fmt: skip


def test_the_secret_is_shown_once_stored_encrypted_and_only_this_departments_admin_manages_it(client: Any, factory: Any, world: dict[str, Any]) -> None:
    created = _create(client, world["admin"], ["case.opened"])
    secret = created["secret"]
    assert secret.startswith("whsec_") and len(secret) > 30 and created["secret_hint"] == secret[-4:] and created["is_mock_receiver"]

    listed = client.get("/v1/admin/webhooks", headers=world["admin"]).json()
    assert [w["id"] for w in listed] == [created["id"]] and "secret" not in listed[0] and secret not in json.dumps(listed)
    assert "secret" not in client.get(f"/v1/admin/webhooks/{created['id']}", headers=world["admin"]).json()

    with system_session() as db:
        row = db.get(models.Webhook, uuid.UUID(created["id"]))
        assert row is not None and row.secret_enc != secret and secret not in row.secret_enc
        assert decrypt_field(db.get(models.Tenant, world["tenant"].id).wrapped_dek, row.secret_enc) == secret  # type: ignore[union-attr]

    for headers in (world["officer"], factory.headers(client, world["citizen"])):
        assert client.get("/v1/admin/webhooks", headers=headers).status_code == 403
        assert client.post("/v1/admin/webhooks", headers=headers, json={"url": MOCK, "events": ["*"]}).status_code == 403
    assert client.get("/v1/admin/webhooks").status_code == 401

    outsider = factory.headers(client, factory.account(factory.tenant(), "admin"))
    assert client.get("/v1/admin/webhooks", headers=outsider).json() == []
    for call in (lambda: client.get(f"/v1/admin/webhooks/{created['id']}", headers=outsider),
                 lambda: client.patch(f"/v1/admin/webhooks/{created['id']}", headers=outsider, json={"active": False}),
                 lambda: client.delete(f"/v1/admin/webhooks/{created['id']}", headers=outsider),
                 lambda: client.post(f"/v1/admin/webhooks/{created['id']}/test", headers=outsider),
                 lambda: client.get(f"/v1/admin/webhooks/{created['id']}/deliveries", headers=outsider)):  # fmt: skip
        assert call().status_code == 404

    again = client.post("/v1/admin/webhooks", headers=world["admin"], json={"url": MOCK, "events": ["*"]})
    assert again.status_code == 409 and again.json()["code"] == "webhook_exists"
    rotated = client.post(f"/v1/admin/webhooks/{created['id']}/rotate-secret", headers=world["admin"]).json()
    assert rotated["secret"] != secret and rotated["secret_hint"] == rotated["secret"][-4:]


def test_unknown_fields_events_and_ssrf_targets_are_refused(client: Any, world: dict[str, Any]) -> None:
    def post(body: dict[str, Any]) -> Any:
        return client.post("/v1/admin/webhooks", headers=world["admin"], json=body)

    assert post({"url": MOCK, "events": ["*"], "extra": 1}).status_code == 422
    assert post({"url": MOCK, "events": ["user.deleted"]}).status_code == 422
    assert post({"url": MOCK, "events": []}).status_code == 422
    for url in ["http://127.0.0.1:8000/v1/admin", "https://localhost/hook", "https://169.254.169.254/latest/meta-data", "https://10.0.0.5/hook",
                "https://[::1]/hook", "https://[::ffff:127.0.0.1]/hook", "ftp://example.com/x", "https://user:pw@example.com/", "file:///etc/passwd"]:
        refused = post({"url": url, "events": ["*"]})
        assert refused.status_code == 422 and refused.json()["code"] == "webhook_url_refused", url
        assert refused.json()["reason"].startswith("blocked_target"), url
    assert client.get("/v1/admin/webhooks", headers=world["admin"]).json() == []
    hook = _create(client, world["admin"])
    changed = client.patch(f"/v1/admin/webhooks/{hook['id']}", headers=world["admin"], json={"url": "https://169.254.169.254/x"})
    assert changed.status_code == 422 and changed.json()["code"] == "webhook_url_refused"


def test_a_case_opened_event_reaches_the_mock_receiver_signed_and_without_personal_data(client: Any, world: dict[str, Any]) -> None:
    tenant, citizen = world["tenant"], world["citizen"]
    hook = _create(client, world["admin"], ["case.opened"])

    ids = t.review_case(tenant.id, citizen.person_id)
    page = _deliveries(client, world["admin"], hook["id"])
    assert [d["status"] for d in page["items"]] == ["pending"] and page["items"][0]["event"] == "case.opened"
    assert _deliver(tenant.id) == 1

    delivery = _deliveries(client, world["admin"], hook["id"])["items"][0]
    assert delivery["status"] == "delivered" and delivery["response_code"] == 200 and delivery["attempts"] == 1
    assert delivery["next_attempt_at"] is None and delivery["last_error"] is None and delivery["delivered_at"]

    received = client.get("/v1/admin/webhooks/mock-receiver/received", headers=world["admin"], params={"webhook_id": hook["id"]}).json()
    assert received["reachable"] and len(received["items"]) == 1
    item = received["items"][0]
    assert item["signature_valid"] is True and item["event"] == "case.opened" and item["delivery_id"] == delivery["id"]
    body = item["body"]
    assert body["event"] == "case.opened" and body["id"] == delivery["id"]
    assert body["data"] == {"case_id": str(ids["case_id"]), "kind": "application_review", "status": "open", "application_id": str(ids["application_id"])}

    # Payloads carry ids and statuses only: no name, phone or national ID, in what was stored or in what was sent.
    with system_session() as db:
        person = db.get(models.Person, citizen.person_id)
        assert person is not None
        tenant_row = db.get(models.Tenant, tenant.id)
        assert tenant_row is not None
        national_id = decrypt_field(tenant_row.wrapped_dek, person.national_id_enc)
    everything = json.dumps([received, delivery])
    for personal in ("Test Citizen", citizen.identifier, national_id, "Karachi", "income_unverified", "household"):
        assert personal not in everything, personal
    assert set(body["data"]) <= rules.ALLOWED_KEYS


def test_a_webhook_that_does_not_subscribe_gets_nothing_and_a_disabled_one_stops(client: Any, world: dict[str, Any]) -> None:
    tenant, citizen = world["tenant"], world["citizen"]
    payments_only = _create(client, world["admin"], ["payment.sent"])
    t.review_case(tenant.id, citizen.person_id)
    assert _deliveries(client, world["admin"], payments_only["id"])["items"] == []

    patched = client.patch(f"/v1/admin/webhooks/{payments_only['id']}", headers=world["admin"], json={"events": ["case.opened"]})
    assert patched.status_code == 200 and patched.json()["events"] == ["case.opened"]
    client.patch(f"/v1/admin/webhooks/{payments_only['id']}", headers=world["admin"], json={"active": False})
    t.review_case(tenant.id, citizen.person_id)
    assert _deliveries(client, world["admin"], payments_only["id"])["items"] == [], "a disabled webhook queues nothing"


def test_failures_retry_with_backoff_then_go_dead_and_can_be_redelivered(client: Any, world: dict[str, Any]) -> None:
    tenant, citizen = world["tenant"], world["citizen"]
    hook = _create(client, world["admin"], ["case.opened"])
    _receiver_config(hook["id"], down=True)
    t.review_case(tenant.id, citizen.person_id)

    clock = datetime.now(UTC)
    seen: list[dict[str, Any]] = []
    for _ in range(rules.MAX_ATTEMPTS):
        assert _deliver(tenant.id, now=clock) == 1
        row = _deliveries(client, world["admin"], hook["id"])["items"][0]
        seen.append(row)
        if row["status"] == "dead":
            break
        assert row["status"] == "failed" and row["response_code"] == 503 and row["last_error"] == "http_503"
        wait = datetime.fromisoformat(row["next_attempt_at"]) - datetime.now(UTC)
        step = min(rules.BACKOFF_CAP_SECONDS, rules.BACKOFF_BASE_SECONDS * 2 ** (row["attempts"] - 1))
        assert timedelta(seconds=step / 2 - 5) <= wait <= timedelta(seconds=step + 5), "exponential backoff with jitter"
        assert _deliver(tenant.id) == 0, "nothing runs before the retry time"
        clock = datetime.fromisoformat(row["next_attempt_at"]) + timedelta(seconds=1)
    assert [r["attempts"] for r in seen] == list(range(1, rules.MAX_ATTEMPTS + 1))
    assert seen[-1]["status"] == "dead" and seen[-1]["next_attempt_at"] is None and seen[-1]["max_attempts"] == rules.MAX_ATTEMPTS
    assert _deliver(tenant.id, now=clock + timedelta(days=1)) == 0, "a dead delivery is not retried"
    with system_session() as db:
        dead = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "webhook.delivery_dead")).all()
        assert len(dead) == 1 and dead[0].reason == "http_503"

    _receiver_config(hook["id"], down=False)
    again = client.post(f"/v1/admin/webhooks/{hook['id']}/deliveries/{seen[-1]['id']}/redeliver", headers=world["admin"])
    assert again.status_code == 201 and again.json()["id"] != seen[-1]["id"] and again.json()["status"] == "pending"
    assert _deliver(tenant.id) == 1
    rows = _deliveries(client, world["admin"], hook["id"])["items"]
    assert [r["status"] for r in rows] == ["delivered", "dead"], "the old delivery stays in the log"
    assert [r["id"] for r in _deliveries(client, world["admin"], hook["id"], status="dead")["items"]] == [seen[-1]["id"]]


def test_the_test_button_sends_now_and_the_delivery_log_pages_with_a_cursor(client: Any, world: dict[str, Any]) -> None:
    hook = _create(client, world["admin"])
    for _ in range(3):
        sent = client.post(f"/v1/admin/webhooks/{hook['id']}/test", headers=world["admin"])
        assert sent.status_code == 201
        assert sent.json()["event"] == "webhook.test" and sent.json()["status"] == "delivered" and sent.json()["response_code"] == 200
        assert sent.json()["payload"] == {"webhook_id": hook["id"], "status": "test"}
    first = _deliveries(client, world["admin"], hook["id"], limit=2)
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = _deliveries(client, world["admin"], hook["id"], limit=2, cursor=first["next_cursor"])
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert len({d["id"] for d in first["items"] + second["items"]}) == 3
    assert client.get(f"/v1/admin/webhooks/{hook['id']}/deliveries", headers=world["admin"], params={"cursor": "garbage!"}).status_code == 422
    assert client.get(f"/v1/admin/webhooks/{hook['id']}/deliveries", headers=world["admin"], params={"limit": 101}).status_code == 422
    assert client.get("/v1/admin/webhooks", headers=world["admin"]).json()[0]["deliveries_pending"] == 0


def test_the_receiver_refuses_a_forged_or_replayed_request_and_a_changed_secret() -> None:
    hook_id = str(uuid.uuid4())
    sender.register_mock_secret(hook_id, "whsec_the_real_one")
    body = b'{"id":"d1","event":"case.opened","data":{"status":"open"}}'

    def post(secret: str, timestamp: int, payload: bytes = body) -> Any:
        headers = {"X-Rahat-Webhook": hook_id, "X-Rahat-Delivery": "d1", "X-Rahat-Event": "case.opened", "X-Rahat-Timestamp": str(timestamp),
                   "X-Rahat-Signature": webhook_signing.sign(secret, timestamp, body), "Content-Type": "application/json"}  # fmt: skip
        return sender._mock_call("POST", "/webhooks/receive", content=payload, headers=headers, params=None, timeout=5)

    now = int(time.time())
    assert post("whsec_the_real_one", now).status_code == 200
    assert post("whsec_a_guess", now).status_code == 401
    assert post("whsec_the_real_one", now, payload=body + b" ").status_code == 401
    assert post("whsec_the_real_one", now - 3600).status_code == 401
    items = sender.mock_received(hook_id, 10)["items"]
    assert [i["signature_valid"] for i in reversed(items)] == [True, False, False, False]
