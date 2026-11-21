"""Webhook rules: events, payload hygiene, retry backoff and the SSRF guard. Pure functions, DB-free tests.

The SSRF guard has three parts, because a URL that looked fine when it was saved can resolve elsewhere later
(DNS rebinding):

1. `parse_target` takes only a well-formed https URL (http only where dev allows it) with no user name and no fragment.
2. `check_addresses` refuses the whole host when any address it resolves to is not a public one: private,
   loopback, link-local (this covers the cloud metadata address 169.254.169.254), multicast, reserved, unspecified,
   carrier-grade NAT, and IPv4 addresses hidden inside IPv6 forms.
3. The sender connects to one of the checked addresses itself, so no second lookup can return a different answer.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

MOCK_RECEIVER_URL: Final = "mock://receiver"  # the in-repo receiver (app.mocks): the only target allowed to be private

EVENTS: Final[dict[str, str]] = {
    "decision.made": "An application was decided (by the engine, an officer or an appeal)",
    "case.opened": "A case was opened for a person to review",
    "case.resolved": "A case was resolved",
    "payment.sent": "A payment was handed to the payment rail",
    "payment.settled": "The payment rail confirmed a payment",
    "appeal.opened": "A citizen appealed a decision",
    "appeal.resolved": "An appeal was decided",
}
TEST_EVENT: Final = "webhook.test"
WILDCARD: Final = "*"

# Payloads carry ids and statuses only. Everything not listed here is dropped, and a value that is not a plain
# token (letters, digits and . _ : -) is dropped too, so a name, a phone number or a sentence cannot get in.
ALLOWED_KEYS: Final = frozenset({
    "application_id", "decision_id", "case_id", "payment_id", "appeal_id", "webhook_id",
    "status", "outcome", "route", "kind", "resolution", "reason_code",
})  # fmt: skip
_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

MAX_ATTEMPTS: Final = 6
BACKOFF_BASE_SECONDS: Final = 30.0
BACKOFF_CAP_SECONDS: Final = 3600.0
TIMEOUT_SECONDS: Final = 5.0


def valid_event(name: str) -> bool:
    return name == WILDCARD or name in EVENTS


def subscribed(events: list[Any] | None, event: str) -> bool:
    return bool(events) and (WILDCARD in events or event in events)


def clean_payload(data: dict[str, Any]) -> dict[str, str]:
    """Keep only allowed keys whose values are plain tokens (ids, status words)."""
    clean: dict[str, str] = {}
    for key, value in data.items():
        if key not in ALLOWED_KEYS or value is None:
            continue
        text = str(value) if isinstance(value, uuid.UUID | str | int) and not isinstance(value, bool) else None
        if text is not None and _TOKEN.match(text):
            clean[key] = text
    return clean


def backoff_seconds(attempts_made: int, rand: float) -> float:
    """Exponential backoff with equal jitter: half of the step is fixed, half is random (`rand` is in [0, 1))."""
    step = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempts_made - 1)))
    return step / 2 + (step / 2) * min(max(rand, 0.0), 1.0)


def retryable(error: str | None) -> bool:
    """A refused target never becomes allowed by waiting; every other failure is worth another try."""
    return not (error or "").startswith("blocked_target")


# --- the SSRF guard ---------------------------------------------------------------------------------------


class BlockedTarget(ValueError):
    """The URL may not be called. The message is safe to show to an admin."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int
    path: str  # path and query, as sent

    @property
    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        return self.host if self.port == default else f"{self.host}:{self.port}"


def parse_target(url: str, *, allow_http: bool = False) -> Target:
    if not url or len(url) > 2000 or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise BlockedTarget("blocked_target:bad_url", "That is not a valid web address.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise BlockedTarget("blocked_target:bad_url", "That is not a valid web address.") from exc
    scheme = parts.scheme.lower()
    if scheme != "https" and not (allow_http and scheme == "http"):
        raise BlockedTarget("blocked_target:scheme", "Only https addresses are allowed.")
    if parts.username is not None or parts.password is not None:
        raise BlockedTarget("blocked_target:userinfo", "The address must not contain a user name or password.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedTarget("blocked_target:bad_url", "The address has no host name.")
    if parts.fragment:
        raise BlockedTarget("blocked_target:bad_url", "The address must not contain a #fragment.")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return Target(scheme=scheme, host=host, port=port or (443 if scheme == "https" else 80), path=path)


def address_is_public(raw: str) -> bool:
    """True only for an address that routes on the public internet."""
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is not None:
            return address_is_public(str(embedded))
        if ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64 hides an IPv4 address in the last 32 bits
            return address_is_public(str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)))
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_private)


def check_addresses(host: str, addresses: list[str]) -> list[str]:
    """The addresses to connect to. Refuses the host when it resolves to nothing, or to anything that is not public."""
    if not addresses:
        raise BlockedTarget("blocked_target:unresolved", "That host name does not resolve.")
    bad = [a for a in addresses if not address_is_public(a)]
    if bad:
        raise BlockedTarget("blocked_target:private_address", "That host points to a private, local or reserved address.")
    return list(dict.fromkeys(addresses))
