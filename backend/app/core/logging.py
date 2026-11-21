"""Structured JSON logs with request ids and central redaction of personal data."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import current_request_id

# Patterns are bounded and anchored on digits so they stay linear-time on hostile input.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b\d{5}-\d{7}-\d\b"), "[id]"),
    (re.compile(r"\b0\d{3}-?\d{7}\b"), "[phone]"),
    (re.compile(r"\+92[ -]?\d{3}[ -]?\d{7}"), "[phone]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}\b"), "[email]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [token]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[token]"),
    # API keys keep their public prefix (useful when reading logs) and lose the secret.
    (re.compile(r"\brk_([a-f0-9]{6,16})_[A-Za-z0-9_-]{8,}"), r"rk_\1_[key]"),
)


def redact(text: str) -> str:
    """Mask identifiers, phone numbers, emails and tokens. Use before logging or sending text out."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    # Newlines and control characters would let a caller forge log lines.
    return text.replace("\r", "\\r").replace("\n", "\\n")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "request_id": current_request_id(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Access logs are written by our middleware, with the route template instead of the raw path.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
