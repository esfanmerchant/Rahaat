"""Settings of the mock services. The platform's adapters read the same `MOCK_*_KEY` variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICES: tuple[str, ...] = ("identity", "registry", "payment", "sms")

# Development keys. They protect simulated services only; set real values with MOCK_*_KEY when deployed.
DEV_KEYS: dict[str, str] = {
    "identity": "mock-identity-dev-key-0001",
    "registry": "mock-registry-dev-key-0001",
    "payment": "mock-payment-dev-key-0001",
    "sms": "mock-sms-dev-key-0001",
    "control": "mock-control-dev-key-0001",
    "webhook": "mock-webhook-dev-key-0001",
}

KEY_HEADER = "X-Mock-Key"


class MockServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOCK_", env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    identity_key: str = DEV_KEYS["identity"]
    registry_key: str = DEV_KEYS["registry"]
    payment_key: str = DEV_KEYS["payment"]
    sms_key: str = DEV_KEYS["sms"]
    control_key: str = DEV_KEYS["control"]
    webhook_key: str = DEV_KEYS["webhook"]  # the demo webhook receiver (not one of the failure-injected SERVICES)
    max_latency_ms: int = 15_000
    seed: int = 20261121  # failure injection draws from a seeded generator, so a run can be repeated

    def key_for(self, service: str) -> str:
        return {
            "identity": self.identity_key,
            "registry": self.registry_key,
            "payment": self.payment_key,
            "sms": self.sms_key,
            "control": self.control_key,
            "webhook": self.webhook_key,
        }[service]


@lru_cache
def get_mock_service_settings() -> MockServiceSettings:
    return MockServiceSettings()
