"""Signatures, backoff, payload hygiene and the SSRF guard. No database, no network."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.core import webhook_signing
from app.modules.webhooks import rules, sender

# --- signature ----------------------------------------------------------------------------------------------


def test_signature_matches_the_documented_formula() -> None:
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(b"whsec_x", b"1700000000.{\"a\":1}", hashlib.sha256).hexdigest()
    assert webhook_signing.sign("whsec_x", 1700000000, b'{"a":1}') == expected


def test_verify_accepts_only_the_exact_body_secret_and_a_fresh_timestamp() -> None:
    body = b'{"event":"case.opened"}'
    signature = webhook_signing.sign("secret-1234", 1000, body)
    assert webhook_signing.verify("secret-1234", "1000", body, signature, now=1100)
    assert not webhook_signing.verify("secret-1234", "1000", body + b" ", signature, now=1100)  # body changed
    assert not webhook_signing.verify("other-secret", "1000", body, signature, now=1100)
    assert not webhook_signing.verify("secret-1234", "1001", body, signature, now=1100)  # timestamp is part of what is signed
    assert not webhook_signing.verify("secret-1234", "1000", body, signature, now=1000 + 301)  # replayed too late
    assert not webhook_signing.verify("secret-1234", "soon", body, signature, now=1000)
    assert not webhook_signing.verify("secret-1234", None, body, signature, now=1000)
    assert not webhook_signing.verify("secret-1234", "1000", body, None, now=1000)


# --- backoff ------------------------------------------------------------------------------------------------


def test_backoff_doubles_with_jitter_inside_the_step_and_is_capped() -> None:
    for attempts, step in [(1, 30), (2, 60), (3, 120), (4, 240)]:
        assert rules.backoff_seconds(attempts, 0.0) == step / 2
        assert rules.backoff_seconds(attempts, 0.999999) == pytest.approx(step, rel=1e-3)
    assert rules.backoff_seconds(20, 1.0) == rules.BACKOFF_CAP_SECONDS
    assert rules.backoff_seconds(3, -5) == rules.backoff_seconds(3, 0) and rules.backoff_seconds(3, 5) == rules.backoff_seconds(3, 1)


def test_a_blocked_target_is_never_retried_but_everything_else_is() -> None:
    assert not rules.retryable("blocked_target:private_address")
    assert all(rules.retryable(e) for e in ("timeout", "http_503", "connect_error:ConnectError", None, "redirect_not_followed"))


# --- payload hygiene ----------------------------------------------------------------------------------------


def test_payloads_keep_ids_and_statuses_and_drop_everything_else() -> None:
    case_id = uuid.uuid4()
    clean = rules.clean_payload({
        "case_id": case_id, "status": "open", "application_id": None, "full_name": "Rubina Bibi", "phone": "0999-1234567",
        "national_id": "00000-1234567-1", "resolution": "Ali Khan", "outcome": "rejected", "route": "human; drop table", "nested": {"a": 1},
    })  # fmt: skip
    assert clean == {"case_id": str(case_id), "status": "open", "outcome": "rejected"}


def test_every_allowed_key_is_an_id_or_a_status_word() -> None:
    assert all(k.endswith("_id") or k in {"status", "outcome", "route", "kind", "resolution", "reason_code"} for k in rules.ALLOWED_KEYS)


def test_subscription_matching_and_event_names() -> None:
    assert rules.subscribed(["case.opened"], "case.opened") and not rules.subscribed(["case.opened"], "case.resolved")
    assert rules.subscribed(["*"], "payment.sent") and not rules.subscribed([], "payment.sent") and not rules.subscribed(None, "x")
    assert rules.valid_event("*") and rules.valid_event("appeal.opened") and not rules.valid_event("user.deleted")


# --- SSRF guard ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.1.2.3", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "224.0.0.1",
    "::1", "::", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::1", "not-an-ip",
])  # fmt: skip
def test_non_public_addresses_are_refused(address: str) -> None:
    assert not rules.address_is_public(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert rules.address_is_public(address)


def test_one_private_answer_blocks_the_whole_host() -> None:
    with pytest.raises(rules.BlockedTarget) as blocked:
        rules.check_addresses("evil.example", ["93.184.216.34", "10.0.0.1"])
    assert blocked.value.reason == "blocked_target:private_address"
    with pytest.raises(rules.BlockedTarget):
        rules.check_addresses("nowhere.example", [])
    assert rules.check_addresses("ok.example", ["93.184.216.34", "93.184.216.34"]) == ["93.184.216.34"]


@pytest.mark.parametrize("url", [
    "http://example.com/hook", "ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "https://user:pw@example.com/",
    "https://example.com/hook#frag", "https:///nohost", "https://exa mple.com/", "", "https://example.com:99999/", "gopher://example.com",
])  # fmt: skip
def test_malformed_or_unsafe_urls_are_refused_before_any_lookup(url: str) -> None:
    with pytest.raises(rules.BlockedTarget):
        rules.parse_target(url)


def test_http_is_allowed_only_when_the_caller_says_dev_does() -> None:
    assert rules.parse_target("http://example.com/hook", allow_http=True).scheme == "http"
    target = rules.parse_target("https://Example.com:8443/a/b?x=1")
    assert (target.host, target.port, target.path, target.host_header) == ("example.com", 8443, "/a/b?x=1", "example.com:8443")


def _resolver(*addresses: str):  # noqa: ANN202
    return lambda host, port: list(addresses)


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/hook", "https://[::1]/hook", "https://169.254.169.254/latest/meta-data", "https://localhost/hook",
    "https://10.1.2.3:8443/hook", "https://[::ffff:127.0.0.1]/hook",
])  # fmt: skip
def test_literal_private_hosts_are_blocked_even_if_the_resolver_lies(url: str) -> None:
    result = sender.send_signed(url, b"{}", {}, resolver=sender.system_resolver)
    assert not result.ok and result.error is not None and result.error.startswith("blocked_target")


def test_a_public_name_that_resolves_private_is_blocked_at_send_time() -> None:
    """DNS rebinding: the name looked fine when it was saved and resolves to the metadata address now."""
    result = sender.send_signed("https://hooks.example.com/x", b"{}", {}, resolver=_resolver("169.254.169.254"))
    assert (result.ok, result.error) == (False, "blocked_target:private_address")


def test_the_request_goes_to_the_checked_address_with_the_host_name_kept_and_redirects_are_not_followed() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest"})

    result = sender.send_signed(
        "https://hooks.example.com/x?y=1", b'{"a":1}', {"X-Rahat-Event": "case.opened"}, resolver=_resolver("93.184.216.34"),
        transport=httpx.MockTransport(handler),
    )  # fmt: skip
    assert (result.ok, result.status_code, result.error) == (False, 302, "redirect_not_followed")
    assert len(seen) == 1, "the redirect target was not requested"
    request = seen[0]
    assert request.url.host == "93.184.216.34" and request.url.path == "/x" and request.headers["host"] == "hooks.example.com"
    assert request.headers["x-rahat-event"] == "case.opened" and request.content == b'{"a":1}'
    assert request.extensions.get("sni_hostname") == "hooks.example.com"


def test_success_failure_and_timeout_are_reported_without_raising() -> None:
    def respond(code: int):  # noqa: ANN202
        return httpx.MockTransport(lambda request: httpx.Response(code))

    ok = sender.send_signed("https://h.example.com/", b"{}", {}, resolver=_resolver("93.184.216.34"), transport=respond(204))
    bad = sender.send_signed("https://h.example.com/", b"{}", {}, resolver=_resolver("93.184.216.34"), transport=respond(503))
    assert (ok.ok, ok.status_code) == (True, 204) and (bad.ok, bad.status_code, bad.error) == (False, 503, "http_503")

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    timed_out = sender.send_signed("https://h.example.com/", b"{}", {}, resolver=_resolver("93.184.216.34"), transport=httpx.MockTransport(slow))
    assert (timed_out.ok, timed_out.error) == (False, "timeout")
