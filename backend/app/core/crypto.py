"""Field-level encryption and blind indexes for identifiers.

Envelope scheme: each tenant has its own random data key (DEK). The DEK is stored wrapped by the master
key from the environment, which stands in for a KMS. Encrypted fields use AES-256-GCM. Lookups use an
HMAC blind index, so the database can match an identifier without being able to read it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

_VERSION = "v1"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode())


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> str:
    nonce = os.urandom(12)
    return f"{_VERSION}:{_b64(nonce + AESGCM(key).encrypt(nonce, plaintext, aad))}"


def _open(key: bytes, token: str, aad: bytes) -> bytes:
    version, _, payload = token.partition(":")
    if version != _VERSION:
        raise ValueError("unknown ciphertext version")
    raw = _unb64(payload)
    return AESGCM(key).decrypt(raw[:12], raw[12:], aad)


def _derive(info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(get_settings().master_key_bytes())


def new_wrapped_dek() -> str:
    """Create a tenant data key and return it wrapped by the master key."""
    return _seal(get_settings().master_key_bytes(), os.urandom(32), b"dek")


def rewrap_dek(wrapped_dek: str, old_master_key: bytes) -> str:
    """Key rotation: unwrap with the old master key and wrap with the current one."""
    return _seal(get_settings().master_key_bytes(), _open(old_master_key, wrapped_dek, b"dek"), b"dek")


def encrypt_field(wrapped_dek: str, plaintext: str) -> str:
    dek = _open(get_settings().master_key_bytes(), wrapped_dek, b"dek")
    return _seal(dek, plaintext.encode(), b"field")


def decrypt_field(wrapped_dek: str, token: str) -> str:
    dek = _open(get_settings().master_key_bytes(), wrapped_dek, b"dek")
    return _open(dek, token, b"field").decode()


def encrypt_platform(plaintext: str) -> str:
    """For the few values that belong to no tenant, such as a login phone number."""
    return _seal(_derive(b"platform-field"), plaintext.encode(), b"field")


def decrypt_platform(token: str) -> str:
    return _open(_derive(b"platform-field"), token, b"field").decode()


def blind_index(value: str, *, scope: str = "global") -> str:
    """Deterministic keyed hash for equality lookups. `scope` separates tenants from each other."""
    key = _derive(b"blind-index:" + scope.encode())
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()
