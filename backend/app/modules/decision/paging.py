"""Keyset cursors for Track B's lists: URL-safe, exact to the microsecond, and refused when malformed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import Unprocessable

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICRO = timedelta(microseconds=1)


def encode(created_at: datetime, row_id: uuid.UUID) -> str:
    stamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    return f"{(stamp - _EPOCH) // _MICRO}_{row_id.hex}"


def decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        micros, _, hex_id = cursor.partition("_")
        return _EPOCH + timedelta(microseconds=int(micros)), uuid.UUID(hex=hex_id)
    except (ValueError, OverflowError):
        raise Unprocessable("This page cursor is not valid. Start again from the first page.", code="bad_cursor") from None


def before(columns: tuple[Any, Any], cursor: str | None) -> Any | None:
    """A WHERE clause for rows strictly after the cursor in (created_at desc, id desc) order, or None."""
    if not cursor:
        return None
    stamp, row_id = decode(cursor)
    created, ident = columns
    return (created < stamp) | ((created == stamp) & (ident < row_id))
