"""The mock ID issuer's Ed25519 keys.

In dev and test the key is derived deterministically from a built-in seed, so generated specimen cards keep
verifying across machines and runs. Set `MOCK_ISSUER_SEED` to use a different key (the key id changes with it).
Only the public half ever leaves this module: `public_keys()` / `public_jwks()` are what another service (the
mock identity service) publishes. No real issuer exists; this key signs nothing but specimen cards.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DEFAULT_SEED = "rahat-dev-mock-issuer-seed-2026-not-a-secret"
SEED_ENV = "MOCK_ISSUER_SEED"
_HKDF_SALT = b"rahat-mock-issuer-v1"


@dataclass(frozen=True)
class IssuerKey:
    key_id: str
    private_key: Ed25519PrivateKey

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self.private_key.public_key()

    def public_bytes(self) -> bytes:
        return self.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message)


def key_from_seed(seed: str, *, prefix: str = "mi") -> IssuerKey:
    """Derive an Ed25519 key from a seed string with HKDF-SHA256. The key id is a fingerprint of the public key."""
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=b"ed25519-signing-key").derive(seed.encode("utf-8"))
    private = Ed25519PrivateKey.from_private_bytes(raw)
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return IssuerKey(key_id=f"{prefix}-{hashlib.sha256(public).hexdigest()[:8]}", private_key=private)


def is_default_seed() -> bool:
    return not os.environ.get(SEED_ENV)


@lru_cache(maxsize=4)
def _issuer_for(seed: str) -> IssuerKey:
    return key_from_seed(seed)


def issuer_key() -> IssuerKey:
    """The active mock issuer key (signing side). Used only by the specimen generator."""
    return _issuer_for(os.environ.get(SEED_ENV) or DEFAULT_SEED)


def trusted_public_keys() -> dict[str, Ed25519PublicKey]:
    """Key id to public key, for verifying QR signatures. Today that is the one active issuer key."""
    key = issuer_key()
    return {key.key_id: key.public_key}


def public_keys() -> dict[str, bytes]:
    """Key id to raw 32-byte public key."""
    key = issuer_key()
    return {key.key_id: key.public_bytes()}


def public_jwks() -> dict[str, list[dict[str, str]]]:
    """The public keys as a JWK set (RFC 8037 OKP), ready for a service to publish."""
    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "alg": "EdDSA",
                "use": "sig",
                "kid": kid,
                "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
            }  # fmt: skip
            for kid, raw in public_keys().items()
        ]
    }
