"""Adapter settings: how to reach the mock services, their keys, timeouts, retries and breaker limits.

`MOCK_BASE_URL` stays in the core settings. Everything else reads `MOCK_*` variables here.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import get_settings
from app.mocks.config import DEV_KEYS


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOCK_", env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    # auto: in process in dev and test (no second process needed), over HTTP at MOCK_BASE_URL otherwise.
    transport: Literal["auto", "inprocess", "http"] = "auto"
    identity_key: str = DEV_KEYS["identity"]
    registry_key: str = DEV_KEYS["registry"]
    payment_key: str = DEV_KEYS["payment"]
    sms_key: str = DEV_KEYS["sms"]
    control_key: str = DEV_KEYS["control"]

    timeout_seconds: float = 2.0  # identity, registry, SMS: the citizen is waiting
    payment_timeout_seconds: float = 5.0
    retries: int = 2  # extra attempts after the first, for timeouts and 5xx only
    backoff_base_seconds: float = 0.15
    backoff_max_seconds: float = 1.0
    breaker_threshold: int = 3  # consecutive failed calls before the breaker opens
    breaker_reset_seconds: float = 15.0  # how long it stays open before one trial call

    def key_for(self, service: str) -> str:
        return {
            "identity": self.identity_key,
            "registry": self.registry_key,
            "payment": self.payment_key,
            "sms": self.sms_key,
            "control": self.control_key,
        }[service]

    def transport_effective(self) -> Literal["inprocess", "http"]:
        if self.transport != "auto":
            return self.transport
        if get_settings().mocks_in_process:
            return "inprocess"
        return "inprocess" if get_settings().defaults_allowed else "http"

    def timeout_for(self, service: str) -> float:
        return self.payment_timeout_seconds if service == "payment" else self.timeout_seconds


@lru_cache
def get_integration_settings() -> IntegrationSettings:
    return IntegrationSettings()
