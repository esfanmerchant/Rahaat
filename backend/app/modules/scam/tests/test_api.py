"""The scam checker API, disputes, the Scam Map, warnings, tenant isolation, rate limits and the seed step."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.db import RlsContext, session_scope, system_session
from app.db import models
from app.modules.notifications.service import notify
from app.modules.scam import ratelimit, runtime
from app.modules.scam.seed_step import seed_tenant

SCAM_LABELS = {"relief_scam", "phishing_link", "advance_fee", "impersonation"}
UR = {"Accept-Language": "ur"}
EN = {"Accept-Language": "en-GB,en;q=0.9"}


def _message(tenant_id: Any, person_id: Any, template: str, lang: str, **payload: Any) -> str:
    with session_scope(RlsContext(role="worker", tenant_id=tenant_id)) as db:
        rows = notify(db, tenant_id=tenant_id, person_id=person_id, template=template, payload=payload, lang=lang, channels=("in_app",))
        return str(rows[0].body)


def _check(client: Any, headers: dict[str, str], text: str, **extra: Any) -> dict[str, Any]:
    response = client.post("/v1/scam/check", json={"text": text, **extra}, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_our_real_messages_are_confirmed_by_their_verify_code(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    headers = factory.headers(client, citizen)
    english = _message(tenant.id, citizen.person_id, "payment_sent", "en", amount_pkr=12000, rail_ref="MR-1A2B3C4D5E")
    urdu = _message(tenant.id, citizen.person_id, "application_received", "ur", tracking_code="R-10001")

    out = _check(client, headers | EN, english, sender="RAHAT")
    assert out["certainty"] == "confirmed_real" and out["label"] == "legit_program_message" and out["route"] == "auto"
    assert out["reasons"] == [{"code": "verify_code_confirmed", "text": "This code matches a message we sent."}]
    assert out["verified"]["genuine"] is True and out["verified"]["department"] == tenant.name
    assert out["detail"] is None, "citizens get no scores"

    out = _check(client, headers | UR, urdu)
    assert out["certainty"] == "confirmed_real" and out["lang"] == "ur" and out["headline"] == "یہ راحت کا اصلی پیغام ہے۔"


def test_a_tampered_or_invented_code_is_flagged(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    headers = factory.headers(client, citizen) | EN
    real = _message(tenant.id, citizen.person_id, "approved", "en", amount_pkr=12000)
    tampered = real.replace("We never ask for a fee.", "To receive it, send a Rs 500 fee to 0999-1234567.")
    out = _check(client, headers, tampered, sender="0999-1234567")
    assert out["certainty"] == "likely_scam" and out["label"] in SCAM_LABELS
    assert out["reasons"][0]["code"] == "code_real_text_changed"

    invented = "Rahat: Rs 12,000 is ready for you. Pay Rs 500 release fee to 0999-7654321 to get it today. Code Q8W4ZX"
    out = _check(client, headers, invented, sender="0999-7654321")
    assert out["certainty"] == "likely_scam" and out["reasons"][0]["code"] == "verify_code_not_found"
    assert out["verified"]["genuine"] is False


def test_a_lookalike_link_is_flagged_defanged_and_never_fetched(client: Any, factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    headers = factory.headers(client, citizen) | EN
    runtime.get_model()

    def no_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the scam checker tried to use the network")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    text = "Your Rahat relief is ready. Claim it today at https://rahat-gov.pk.claim-now.xyz/verify?cnic=1"
    out = _check(client, headers, text, sender="RAHAT-GOV")
    assert out["certainty"] in ("likely_scam", "might_be_scam")
    link = out["urls"][0]
    assert link["url"] == "hxxps://rahat-gov[.]pk[.]claim-now[.]xyz/verify?…" and link["risk"] == "high"
    assert "official_name_in_subdomain" in link["flags"] and link["flag_texts"]
    with system_session() as db:
        report = db.get(models.ScamReport, out["report_id"])
        assert report is not None and "https://" not in report.text_redacted and "claim-now[.]xyz" in report.text_redacted


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("مبارک ہو! آپ کا نام راحت پروگرام میں آ گیا ہے۔ 25,000 روپے لینے کے لیے 1,000 روپے فیس اس نمبر 0999-4445556 پر بھیجیں۔", UR),
        ("Mubarak ho! Aap ka naam Rahat program mein aa gaya hai. 25000 rupay lene ke liye 1000 rupay fee 0999-4445556 par bhejein.", EN),
    ],
)
def test_urdu_and_roman_urdu_relief_scams_are_caught(client: Any, factory: Any, text: str, lang: dict[str, str]) -> None:
    tenant = factory.tenant()
    headers = factory.headers(client, factory.account(tenant, "citizen")) | lang
    out = _check(client, headers, text, sender="0999-4445556", channel="sms_forward", district="karachi east")
    assert out["certainty"] in ("likely_scam", "might_be_scam") and out["label"] in SCAM_LABELS
    assert 1 <= len(out["reasons"]) <= 3 and out["what_to_do"]
    with system_session() as db:
        report = db.get(models.ScamReport, out["report_id"])
        assert report is not None and report.district == "Karachi East" and report.channel == "sms_forward"
        assert "0999-4445556" not in report.text_redacted and "[phone]" in report.text_redacted, "stored redacted"
        assert report.sender == "••••••••556" and len(report.text_hash) == 64 and report.tenant_id == tenant.id


def test_a_short_ambiguous_message_abstains(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    headers = factory.headers(client, factory.account(tenant, "citizen")) | EN
    out = _check(client, headers, "Call me now")
    assert out["certainty"] == "not_sure" and out["label"] is None and out["route"] == "human"
    assert out["reasons"][0]["code"] == "too_short" and out["can_dispute"] is True


def test_staff_see_the_probabilities_and_signal_weights(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    officer = factory.headers(client, factory.account(tenant, "officer")) | EN
    out = _check(client, officer, "Congratulations! Your Rahat relief of Rs 25,000 is ready. Pay Rs 500 fee to 0999-1234567 to receive it.")
    detail = out["detail"]
    assert detail is not None and abs(sum(detail["probabilities"].values()) - 1) < 1e-3
    assert detail["model_version"] == runtime.get_model().version and "asks_fee" in detail["fired"]
    assert any(s["signal"] == "asks_fee" for s in detail["signals"]) and detail["thresholds"]["auto_scam_min_p_scam"] == 0.9


def test_dispute_opens_a_case_once_and_only_for_the_reporter(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    headers = factory.headers(client, citizen) | EN
    out = _check(client, headers, "Your school fee of Rs 3,000 must be paid by Friday at the office, the principal said.")
    first = client.post(f"/v1/scam/reports/{out['report_id']}/dispute", json={"note": "This is from my son's school"}, headers=headers)
    assert first.status_code == 200, first.text
    case_id = first.json()["case_id"]
    again = client.post(f"/v1/scam/reports/{out['report_id']}/dispute", headers=headers)
    assert again.status_code == 200 and again.json()["case_id"] == case_id, "asking twice is one request"

    other = factory.headers(client, factory.account(tenant, "citizen"))
    assert client.post(f"/v1/scam/reports/{out['report_id']}/dispute", headers=other).status_code == 404
    assert client.get(f"/v1/scam/reports/{out['report_id']}", headers=other).status_code == 404

    officer = factory.headers(client, factory.account(tenant, "officer"))
    case = client.get(f"/v1/cases/{case_id}", headers=officer)
    assert case.status_code == 200, case.text
    assert case.json()["kind"] == "scam_review" and case.json()["handoff"]["evidence"]["scam_report_id"] == out["report_id"]
    mine = client.get(f"/v1/scam/reports/{out['report_id']}", headers=headers).json()
    assert mine["review"]["status"] == "waiting" and mine["review"]["case_id"] == case_id and mine["can_dispute"] is False

    labelled = client.post(f"/v1/scam/reports/{out['report_id']}/label", json={"label": "unknown", "reason": "A real school notice"}, headers=officer)
    assert labelled.status_code == 200 and labelled.json()["confirmed_label"] == "unknown"
    assert client.get(f"/v1/scam/reports/{out['report_id']}", headers=headers).json()["review"]["status"] == "done"
    assert client.post(f"/v1/scam/reports/{out['report_id']}/label", json={"label": "unknown", "reason": "nope!"}, headers=headers).status_code == 403
    listed = client.get("/v1/scam/reports/mine", headers=headers).json()["items"]
    assert [item["id"] for item in listed] == [out["report_id"]]
    with system_session() as db:
        actions = set(db.scalars(select(models.AuditLog.action).where(models.AuditLog.tenant_id == tenant.id)).all())
        assert {"scam.checked", "scam.disputed", "case.opened", "scam.label_confirmed"} <= actions


def _reports(tenant_id: Any, district: str | None, label: str, n: int, when: datetime | None = None) -> list[Any]:
    with system_session() as db:
        rows = [models.ScamReport(tenant_id=tenant_id, channel="text", text_redacted="[test]", text_hash="0" * 64, label=label, confidence=0.9,
                                  route="auto", district=district, created_at=when or datetime.now(UTC), classification={"source": "test"})
                for _ in range(n)]  # fmt: skip
        db.add_all(rows)
        db.flush()
        return [row.id for row in rows]


def test_the_map_hides_groups_under_five_and_other_tenants_see_nothing(client: Any, factory: Any) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    ids = _reports(tenant.id, "Karachi East", "relief_scam", 6)
    _reports(tenant.id, "Hyderabad", "relief_scam", 3)
    _reports(tenant.id, "Sukkur", "unknown", 7)
    officer = factory.headers(client, factory.account(tenant, "officer"))
    body = client.get("/v1/scam/map?days=7", headers=officer).json()
    assert [(c["district"], c["label"], c["count"]) for c in body["cells"]] == [("Karachi East", "relief_scam", 6)]
    assert body["hidden"]["cells"] == 1 and body["k"] == 5 and body["note"]
    assert body["district_totals"] == [{"district": "Karachi East", "count": 6}]
    everything = client.get("/v1/scam/map?days=7&kind=all", headers=officer).json()
    assert {(c["district"], c["count"]) for c in everything["district_totals"]} == {("Karachi East", 6), ("Sukkur", 7)}
    trend = client.get("/v1/scam/trends?days=3", headers=officer).json()
    relief = next(s for s in trend["series"] if s["label"] == "relief_scam")
    assert sum(p["count"] or 0 for p in relief["points"]) == 9 and len(relief["points"]) == 3

    stranger = factory.headers(client, factory.account(other, "officer"))
    assert client.get("/v1/scam/map?days=7", headers=stranger).json()["cells"] == []
    assert client.get("/v1/scam/reports", headers=stranger).json()["items"] == []
    assert client.get(f"/v1/scam/reports/{ids[0]}", headers=stranger).status_code == 404
    assert client.get("/v1/scam/map", headers=factory.headers(client, factory.account(tenant, "citizen"))).status_code == 403


def test_checks_are_rate_limited_per_user(client: Any, factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit, "PER_USER_PER_MINUTE", 2)
    tenant = factory.tenant()
    headers = factory.headers(client, factory.account(tenant, "citizen"))
    for _ in range(2):
        assert client.post("/v1/scam/check", json={"text": "Is this real?"}, headers=headers).status_code == 200
    blocked = client.post("/v1/scam/check", json={"text": "Is this real?"}, headers=headers)
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited" and int(blocked.headers["Retry-After"]) >= 1
    someone_else = factory.headers(client, factory.account(tenant, "citizen"))
    assert client.post("/v1/scam/check", json={"text": "Is this real?"}, headers=someone_else).status_code == 200


def test_the_same_idempotency_key_returns_the_same_report(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    headers = factory.headers(client, factory.account(tenant, "citizen")) | {"Idempotency-Key": "check-0001"}
    first = _check(client, headers, "Send Rs 500 fee to 0999-1234567 to receive your Rahat money")
    second = _check(client, headers, "Send Rs 500 fee to 0999-1234567 to receive your Rahat money")
    assert first["report_id"] == second["report_id"]


def test_requests_are_strict(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    headers = factory.headers(client, factory.account(tenant, "citizen"))
    assert client.post("/v1/scam/check", json={"text": "hello", "label": "unknown"}, headers=headers).status_code == 422
    assert client.post("/v1/scam/check", json={"text": ""}, headers=headers).status_code == 422
    assert client.post("/v1/scam/check", json={"text": "hello"}).status_code == 401


def test_officers_publish_warnings_and_citizens_of_that_department_read_them(client: Any, factory: Any) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    officer = factory.headers(client, factory.account(tenant, "officer"))
    citizen = factory.headers(client, factory.account(tenant, "citizen"))
    body = {"title": "Fake fee messages", "body_en": "Rahat never asks for a fee. Do not pay https://rahat-fee.xyz",
            "body_ur": "راحت کبھی فیس نہیں مانگتا۔", "district": "karachi east"}  # fmt: skip
    created = client.post("/v1/scam/warnings", json=body, headers=officer)
    assert created.status_code == 201, created.text
    warning = created.json()
    assert warning["district"] == "Karachi East" and "hxxps://rahat-fee[.]xyz" in warning["body_en"], "links in warnings are defanged"
    assert client.post("/v1/scam/warnings", json=body, headers=citizen).status_code == 403
    assert client.post("/v1/scam/warnings", json=body | {"district": "Atlantis"}, headers=officer).status_code == 422
    assert [w["id"] for w in client.get("/v1/scam/warnings", headers=citizen).json()["items"]] == [warning["id"]]
    assert client.get("/v1/scam/warnings?district=Hyderabad", headers=citizen).json()["items"] == []
    assert client.get("/v1/scam/warnings", headers=factory.headers(client, factory.account(other, "citizen"))).json()["items"] == []
    assert client.post(f"/v1/scam/warnings/{warning['id']}/withdraw", headers=officer).json()["status"] == "withdrawn"
    assert client.get("/v1/scam/warnings", headers=citizen).json()["items"] == []


def test_the_seed_step_adds_a_scam_map_once(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    now = datetime.now(UTC)
    with system_session() as db:
        row = db.get(models.Tenant, tenant.id)
        assert row is not None
        added = seed_tenant(db, row, now=now)
    with system_session() as db:
        row = db.get(models.Tenant, tenant.id)
        assert row is not None
        assert seed_tenant(db, row, now=now) == 0, "safe to run twice"
        count = db.scalar(select(func.count()).select_from(models.ScamReport).where(models.ScamReport.tenant_id == tenant.id))
        oldest = db.scalar(select(func.min(models.ScamReport.created_at)).where(models.ScamReport.tenant_id == tenant.id))
    assert count is not None and 200 <= added == count <= 400 and oldest is not None and oldest >= now - timedelta(days=14)
    officer = factory.headers(client, factory.account(tenant, "officer"))
    body = client.get("/v1/scam/map?days=14", headers=officer).json()
    assert body["cells"] and body["hidden"]["cells"] > 0
    campaigns = client.get("/v1/scam/campaigns?days=14", headers=officer).json()
    assert campaigns["items"] and all(c["size_in_window"] >= 5 for c in campaigns["items"])
    assert all("0999-" not in c["sample_text"] for c in campaigns["items"])
    assert len(client.get("/v1/scam/warnings", headers=factory.headers(client, factory.account(tenant, "citizen"))).json()["items"]) == 1
