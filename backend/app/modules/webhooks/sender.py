"""Sending one signed webhook request. Never raises: the outcome is a `SendResult`.

For a real target the host is resolved here, every address is checked (rules.check_addresses), and the request
goes to one of those addresses directly (the host name is kept for the `Host` header and for TLS name checking),
so a second lookup cannot return a different answer. Redirects are never followed, proxy variables are ignored,
the timeout is short, and only the status code of the answer is kept.

The mock receiver (`mock://receiver`) is the one allowed target that is not public: it is the in-repo mock
service, reached in process or at `MOCK_BASE_URL`, the same way the other mock services are.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.mocks.config import KEY_HEADER, get_mock_service_settings
from app.modules.integrations.settings import get_integration_settings
from app.modules.webhooks import rules

log = get_logger("rahat.webhooks")

Resolver = Callable[[str, int], list[str]]


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status_code: int | None = None
    error: str | None = None


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return []
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def allow_http() -> bool:
    return get_settings().defaults_allowed  # plain http only in dev and test


def validate_url(url: str, *, resolver: Resolver | None = None) -> tuple[rules.Target, list[str]]:
    """Raises BlockedTarget. Returns the target and the checked addresses (empty for the mock receiver)."""
    if url == rules.MOCK_RECEIVER_URL:
        return rules.Target(scheme="mock", host="receiver", port=0, path="/"), []
    target = rules.parse_target(url, allow_http=allow_http())
    addresses = rules.check_addresses(target.host, (resolver or system_resolver)(target.host, target.port))
    return target, addresses


def _outcome(response: httpx.Response) -> SendResult:
    code = response.status_code
    if 200 <= code < 300:
        return SendResult(True, code)
    if 300 <= code < 400:
        return SendResult(False, code, "redirect_not_followed")
    return SendResult(False, code, f"http_{code}")


def send_signed(
    url: str, body: bytes, headers: dict[str, str], *, resolver: Resolver | None = None,
    transport: httpx.BaseTransport | None = None, timeout: float = rules.TIMEOUT_SECONDS,
) -> SendResult:  # fmt: skip
    """POST `body` to `url`. `transport` replaces the network (tests)."""
    try:
        target, addresses = validate_url(url, resolver=resolver)
    except rules.BlockedTarget as exc:
        return SendResult(False, None, exc.reason)
    if target.scheme == "mock":
        return _send_to_mock_receiver(body, headers, timeout=timeout)
    last = SendResult(False, None, "connect_error")
    for address in addresses[:3]:
        host = f"[{address}]" if ":" in address else address
        try:
            with httpx.Client(transport=transport, follow_redirects=False, trust_env=False, timeout=timeout) as client:
                response = client.post(
                    f"{target.scheme}://{host}:{target.port}{target.path}", content=body,
                    headers={**headers, "Host": target.host_header, "Content-Type": "application/json"},
                    extensions={"sni_hostname": target.host},
                )
            return _outcome(response)
        except httpx.TimeoutException:
            last = SendResult(False, None, "timeout")
        except httpx.HTTPError as exc:
            last = SendResult(False, None, f"connect_error:{type(exc).__name__}")
    return last


# --- the mock receiver ----------------------------------------------------------------------------------

_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook-mock")


def _mock_call(method: str, path: str, *, content: bytes | None, headers: dict[str, str], params: dict[str, Any] | None,
               timeout: float) -> httpx.Response:  # fmt: skip
    all_headers = {**headers, KEY_HEADER: get_mock_service_settings().webhook_key}
    if get_integration_settings().transport_effective() == "inprocess":
        from app.mocks.main import app as mock_app

        async def send() -> httpx.Response:
            asgi = httpx.ASGITransport(app=mock_app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=asgi, base_url="http://mock.internal") as client:
                return await client.request(method, path, content=content, headers=all_headers, params=params)

        return _POOL.submit(lambda: asyncio.run(send())).result(timeout=timeout)
    with httpx.Client(base_url=get_settings().mock_base_url.rstrip("/"), follow_redirects=False, trust_env=False, timeout=timeout) as client:
        return client.request(method, path, content=content, headers=all_headers, params=params)


def _send_to_mock_receiver(body: bytes, headers: dict[str, str], *, timeout: float) -> SendResult:
    try:
        return _outcome(_mock_call("POST", "/webhooks/receive", content=body, headers={**headers, "Content-Type": "application/json"},
                                   params=None, timeout=timeout))  # fmt: skip
    except (httpx.HTTPError, concurrent.futures.TimeoutError):
        return SendResult(False, None, "timeout")


def register_mock_secret(webhook_id: str, secret: str) -> None:
    """Tell the mock receiver the secret, as an admin would paste it into their own server. Best effort."""
    import json

    try:
        _mock_call("PUT", f"/webhooks/config/{webhook_id}", content=json.dumps({"secret": secret}).encode(),
                   headers={"Content-Type": "application/json"}, params=None, timeout=3.0)  # fmt: skip
    except Exception:  # noqa: BLE001
        log.warning("could not reach the mock webhook receiver to register a secret")


def mock_received(webhook_id: str | None, limit: int) -> dict[str, Any]:
    try:
        response = _mock_call("GET", "/webhooks/received", content=None, headers={}, params={"webhook_id": webhook_id, "limit": limit}
                              if webhook_id else {"limit": limit}, timeout=3.0)  # fmt: skip
        body = response.json()
        return body if response.status_code == 200 and isinstance(body, dict) else {"items": [], "reachable": False}
    except Exception:  # noqa: BLE001
        return {"items": [], "reachable": False}
