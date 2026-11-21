"""The compact signed payload carried by the specimen card's QR code.

Wire format (UTF-8, one line, `|` separated, signature last):

    RC1|<key id>|<mock id>|<full name>|<dob YYYY-MM-DD>|<F|M|X>|<district>|<Ed25519 signature, base64url>

The signature covers the exact bytes before the last `|`. Everything decoded from a QR is untrusted data: it is
size-capped, parsed with fixed rules, and validated field by field before anyone reads it. Nothing in it is
ever executed, fetched or followed.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.mockdata import mock_id_valid
from app.modules.docs_ai.issuer import IssuerKey

VERSION = "RC1"
SEPARATOR = "|"
MAX_PAYLOAD_BYTES = 512
MAX_NAME_LEN = 48
MAX_DISTRICT_LEN = 40

_GENDER_CODE = {"female": "F", "male": "M", "other": "X"}
_GENDER_NAME = {code: name for name, code in _GENDER_CODE.items()}
_TEXT_FIELD = re.compile(r"^[A-Za-z][A-Za-z .'\-]*$")
_DOB = re.compile(r"^(19|20)\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_KEY_ID = re.compile(r"^[a-z0-9][a-z0-9\-]{1,31}$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9_\-]{86}$")

VerifyStatus = Literal["valid", "invalid_signature", "unknown_issuer", "malformed"]


@dataclass(frozen=True)
class CardFields:
    """What the card shows and the QR signs. Mock data only."""

    full_name: str
    national_id: str
    dob: str
    gender: str  # female | male | other
    district: str

    def as_dict(self) -> dict[str, str]:
        return {"full_name": self.full_name, "national_id": self.national_id, "dob": self.dob,
                "gender": self.gender, "district": self.district}  # fmt: skip


@dataclass(frozen=True)
class VerifyResult:
    status: VerifyStatus
    key_id: str | None = None
    fields: CardFields | None = None
    detail: str = ""

    @property
    def valid(self) -> bool:
        return self.status == "valid"


def _check_fields(fields: CardFields) -> str | None:
    """None when every field is well formed, else a short reason."""
    if not (0 < len(fields.full_name) <= MAX_NAME_LEN and _TEXT_FIELD.match(fields.full_name)):
        return "name is not plain Latin text of a sane length"
    if not mock_id_valid(fields.national_id):
        return "national id is not a valid mock id"
    if not _DOB.match(fields.dob):
        return "date of birth is not an ISO date"
    if fields.gender not in _GENDER_CODE:
        return "gender is not one of female, male, other"
    if not (0 < len(fields.district) <= MAX_DISTRICT_LEN and _TEXT_FIELD.match(fields.district)):
        return "district is not plain Latin text of a sane length"
    return None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def signed_message(key_id: str, fields: CardFields) -> str:
    return SEPARATOR.join([VERSION, key_id, fields.national_id, fields.full_name, fields.dob, _GENDER_CODE[fields.gender], fields.district])


def encode(fields: CardFields, key: IssuerKey) -> str:
    """Sign the card fields and return the QR text. Refuses fields that would not parse back."""
    problem = _check_fields(fields)
    if problem:
        raise ValueError(f"cannot issue a specimen card: {problem}")
    message = signed_message(key.key_id, fields)
    text = message + SEPARATOR + _b64url(key.sign(message.encode("utf-8")))
    if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload too long for the card QR")
    return text


def parse(text: str) -> tuple[str, CardFields, bytes, str] | None:
    """Split QR text into (key id, fields, signature, signed message). None when it is not an RC1 payload."""
    if len(text.encode("utf-8", errors="replace")) > MAX_PAYLOAD_BYTES:
        return None
    parts = text.split(SEPARATOR)
    if len(parts) != 8 or parts[0] != VERSION:
        return None
    _, key_id, national_id, name, dob, gender_code, district, signature_text = parts
    if not _KEY_ID.match(key_id) or gender_code not in _GENDER_NAME or not _SIGNATURE.match(signature_text):
        return None
    try:
        signature = base64.urlsafe_b64decode(signature_text + "==")
    except (binascii.Error, ValueError):
        return None
    fields = CardFields(full_name=name, national_id=national_id, dob=dob, gender=_GENDER_NAME[gender_code], district=district)
    if _check_fields(fields) is not None:
        return None
    return key_id, fields, signature, SEPARATOR.join(parts[:7])


def verify(text: str, trusted: dict[str, Ed25519PublicKey]) -> VerifyResult:
    """Check QR text against the trusted issuer keys. Never raises on bad input."""
    parsed = parse(text)
    if parsed is None:
        return VerifyResult("malformed", detail="QR text is not a Rahat card payload")
    key_id, fields, signature, message = parsed
    public = trusted.get(key_id)
    if public is None:
        return VerifyResult("unknown_issuer", key_id=key_id, fields=fields, detail=f"key id {key_id} is not a trusted issuer key")
    try:
        public.verify(signature, message.encode("utf-8"))
    except InvalidSignature:
        return VerifyResult("invalid_signature", key_id=key_id, fields=fields, detail=f"signature does not match key {key_id}")
    return VerifyResult("valid", key_id=key_id, fields=fields, detail=f"signed by {key_id}")
