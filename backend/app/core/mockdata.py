"""Mock identifier formats. The API accepts only these shapes, so real data cannot be stored by accident.

Mock ID:    00000-NNNNNNN-C   reserved prefix, seven digits, one Luhn check digit
Mock phone: 0999-NNNNNNN      0999 is not a real mobile prefix
"""

from __future__ import annotations

import re

MOCK_ID_PREFIX = "00000"
MOCK_PHONE_PREFIX = "0999"

_MOCK_ID = re.compile(r"^00000-(\d{7})-(\d)$")
# Local form 0999-NNNNNNN, or the same number in Pakistan's international form: +92 999 NNNNNNN, 92999NNNNNNN,
# 0092999NNNNNNN. 999 after the country code is the reserved mock prefix; a real mobile number (+92 3xx) never matches.
_MOCK_PHONE = re.compile(r"^(?:0|\+92|0092|92)999(\d{7})$")


def luhn_check_digit(digits: str) -> int:
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return (10 - total % 10) % 10


def make_mock_id(serial: int) -> str:
    body = f"{serial % 10_000_000:07d}"
    return f"{MOCK_ID_PREFIX}-{body}-{luhn_check_digit(body)}"


def make_mock_phone(serial: int) -> str:
    return f"{MOCK_PHONE_PREFIX}-{serial % 10_000_000:07d}"


def normalise_mock_phone(value: str) -> str | None:
    """Canonical `0999-NNNNNNN`, or None when the value is not a mock phone number. Accepts the +92 form too."""
    match = _MOCK_PHONE.match(re.sub(r"[\s\-()]", "", value.strip()))
    return f"{MOCK_PHONE_PREFIX}-{match.group(1)}" if match else None


def is_mock_phone(value: str) -> bool:
    return normalise_mock_phone(value) is not None


def mock_id_shape_ok(value: str) -> bool:
    """Right shape and reserved prefix. The check digit may still be wrong (a repairable error)."""
    return _MOCK_ID.match(value.strip()) is not None


def mock_id_valid(value: str) -> bool:
    match = _MOCK_ID.match(value.strip())
    if match is None:
        return False
    return luhn_check_digit(match.group(1)) == int(match.group(2))


def mask_identifier(value: str) -> str:
    """Show only the last three characters, for screens and logs."""
    cleaned = value.strip()
    return "•" * max(len(cleaned) - 3, 0) + cleaned[-3:]


def international_mock_phone(value: str) -> str | None:
    """Pakistan's international form for display, `+92 XXXXXXXXXX` (country code, a space, ten digits): for a mock
    number that is `+92 999NNNNNNN`. None when the value is not a mock phone number."""
    canonical = normalise_mock_phone(value)
    return f"+92 999{canonical[-7:]}" if canonical else None
