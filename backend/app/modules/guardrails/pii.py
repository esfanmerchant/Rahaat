"""Personal data in free text: find it and mask it before the text is stored, logged or searched.

Masked: mock IDs and anything shaped like a national ID number, phone numbers (mock and real-looking),
emails, card and account numbers, and the digits after PIN, OTP or password. A real-looking ID or phone
number is never stored, even in the audit log. Urdu and Arabic-Indic digits are treated like 0-9.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIGITS = str.maketrans({**{chr(0x0660 + i): str(i) for i in range(10)}, **{chr(0x06F0 + i): str(i) for i in range(10)}})

# Order matters: longer and more specific shapes first. Every pattern is bounded, so matching stays linear.
_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("pii_mock_id", re.compile(r"(?<!\d)00000[-\s]?\d{7}[-\s]?\d(?!\d)"), "[mock-id]"),
    ("pii_national_id", re.compile(r"(?<!\d)\d{5}[-\s]?\d{7}[-\s]?\d(?!\d)"), "[id]"),
    ("pii_iban", re.compile(r"(?i)\bPK\d{2}[A-Z]{4}\d{16}\b"), "[account]"),
    ("pii_card_number", re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)"), "[card]"),
    ("pii_phone", re.compile(r"(?<!\d)(?:\+92[-\s]?|0092[-\s]?|0)3\d{2}[-\s]?\d{7}(?!\d)"), "[phone]"),
    ("pii_mock_phone", re.compile(r"(?<![\d+])(?:\+92[-\s]?|0092[-\s]?|92[-\s]?|0)999[-\s]?\d{7}(?!\d)"), "[mock-phone]"),
    ("pii_phone", re.compile(r"(?<!\d)0\d{2,3}[-\s]?\d{7,8}(?!\d)"), "[phone]"),
    ("pii_email", re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}\b"), "[email]"),
    (
        "pii_secret",
        re.compile(r"(?i)\b(pin|otp|password|passcode|pass\s*code|code)\b(\s*(?:is|hai|ہے|:|=|-)?\s*)(\d{4,8})(?!\d)"),
        r"\1\2[secret]",
    ),
    ("pii_secret", re.compile(r"(پن|کوڈ|پاسورڈ)(\s*(?:ہے|:)?\s*)(\d{4,8})(?!\d)"), r"\1\2[secret]"),
)


@dataclass(frozen=True, slots=True)
class Masked:
    text: str
    codes: tuple[str, ...]

    @property
    def found(self) -> bool:
        return bool(self.codes)


def mask(text: str) -> Masked:
    """Replace personal data with placeholders; report what kind was found."""
    out = text.translate(_DIGITS)
    codes: list[str] = []
    for code, pattern, replacement in _PATTERNS:
        out, count = pattern.subn(replacement, out)
        if count and code not in codes:
            codes.append(code)
    return Masked(out, tuple(codes))


def redact_for_storage(text: str, *, limit: int = 400) -> str:
    """Masked, single-line and bounded: safe to keep in the audit log."""
    masked = mask(text).text
    flat = masked.replace("\r", " ").replace("\n", " ")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
