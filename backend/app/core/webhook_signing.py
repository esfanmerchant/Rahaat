"""The webhook signature, shared by the sender and the mock receiver. Pure functions, no I/O.

    X-Rahat-Signature: sha256=HMAC_SHA256(secret, timestamp + "." + body)

The timestamp is sent in `X-Rahat-Timestamp` (unix seconds). A receiver recomputes the HMAC over the exact
bytes it got, compares in constant time and refuses a timestamp that is too old, so a captured request
cannot be replayed later. HMAC-SHA256 comes from the standard library; there is no custom crypto here.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="
DEFAULT_TOLERANCE_SECONDS = 300


def sign(secret: str, timestamp: int | str, body: bytes) -> str:
    message = str(timestamp).encode() + b"." + body
    return SIGNATURE_PREFIX + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(
    secret: str, timestamp: str | None, body: bytes, signature: str | None, *, now: float,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
) -> bool:  # fmt: skip
    """True only when the signature matches and the timestamp is within the tolerance of `now`."""
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    if abs(now - sent_at) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body).encode(), signature.strip().encode())
