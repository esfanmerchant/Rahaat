"""Opaque keyset cursors shared by the list endpoints of cases, payments, approvals, notifications and jobs."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any

from app.core.errors import Unprocessable


def encode(*values: Any) -> str:
    raw = json.dumps([v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, uuid.UUID) else v for v in values])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode(cursor: str, *, size: int) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise Unprocessable("This page link is not valid. Start from the first page.", code="bad_cursor") from exc
    if not isinstance(values, list) or len(values) != size:
        raise Unprocessable("This page link is not valid. Start from the first page.", code="bad_cursor")
    return values


def as_datetime(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise Unprocessable("This page link is not valid. Start from the first page.", code="bad_cursor") from exc


def as_uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise Unprocessable("This page link is not valid. Start from the first page.", code="bad_cursor") from exc


def iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
