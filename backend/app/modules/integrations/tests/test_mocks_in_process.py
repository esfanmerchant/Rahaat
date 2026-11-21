"""MOCKS_IN_PROCESS: the adapters reach the mock services without a network. No database."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from app.core.config import reset_settings_cache
from app.demo_accounts import demo_citizens
from app.mocks.state import STATE
from app.modules.integrations import service
from app.modules.integrations.settings import get_integration_settings


@pytest.fixture()
def deployed() -> Iterator[None]:
    """Behave like a deployed instance (APP_ENV=demo) with nothing listening on the mock address."""
    keys = ["APP_ENV", "SECRET_KEY", "MASTER_KEY", "MOCK_BASE_URL", "MOCK_TRANSPORT", "MOCKS_IN_PROCESS", "MOCK_RETRIES", "MOCK_BACKOFF_BASE_SECONDS"]
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(
        APP_ENV="demo", MOCK_BASE_URL="http://127.0.0.1:1", MOCK_RETRIES="0", MOCK_BACKOFF_BASE_SECONDS="0",
        SECRET_KEY="x" * 40, MASTER_KEY="a" * 8 + "A" * 35 + "=",
    )  # fmt: skip
    os.environ.pop("MOCK_TRANSPORT", None)
    os.environ.pop("MOCKS_IN_PROCESS", None)
    reset_settings_cache()
    STATE.reset_all()
    service.reset()
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        reset_settings_cache()
        STATE.reset_all()
        service.reset()


def test_deployed_default_is_http(deployed: None) -> None:
    assert get_integration_settings().transport_effective() == "http"


def test_the_setting_switches_to_in_process_and_an_explicit_transport_still_wins(deployed: None) -> None:
    os.environ["MOCKS_IN_PROCESS"] = "true"
    reset_settings_cache()
    service.reset()
    assert get_integration_settings().transport_effective() == "inprocess"
    os.environ["MOCK_TRANSPORT"] = "http"
    service.reset()
    assert get_integration_settings().transport_effective() == "http"


def test_adapters_and_controls_work_in_process_with_nothing_listening(deployed: None) -> None:
    os.environ["MOCKS_IN_PROCESS"] = "true"
    reset_settings_cache()
    service.reset()
    citizen = next(c for c in demo_citizens() if c["name"] == "Zainab Bibi")
    check = service.verify_identity(citizen["national_id"], citizen["name"], citizen["dob"])
    assert check.status == "match", "the identity mock answered without a network"
    controls = service.mock_controls()
    assert set(controls["services"]) == {"identity", "registry", "payment", "sms"}
    # failure injection is per process: it takes effect for the very next adapter call
    service.set_mock_control("identity", latency_ms=None, failure_rate=None, down=True)
    assert service.verify_identity(citizen["national_id"], citizen["name"], citizen["dob"]).status == "unavailable"
    service.reset_mock_controls()
