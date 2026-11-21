from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.security.support import World


@pytest.fixture(scope="module")
def world(app: Any) -> Iterator[World]:
    """Two populated departments, shared by the tests of one module (building them takes a few seconds)."""
    from conftest import Factory  # the root test factory: isolated tenants and accounts

    with TestClient(app) as client:
        yield World(client, Factory())


@pytest.fixture()
def strict_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Empty buckets and small limits for one test; the suite otherwise runs with limits it never reaches."""
    from app.core import ratelimit
    from app.core.config import get_settings

    ratelimit.LIMITER.reset()

    def set_limits(*, anonymous: int | None = None, user: int | None = None, tenant: int | None = None) -> None:
        settings = get_settings()
        for name, value in (("anonymous", anonymous), ("user", user), ("tenant", tenant)):
            if value is not None:
                monkeypatch.setattr(settings, f"rate_limit_{name}_per_minute", value)

    yield set_limits
    ratelimit.LIMITER.reset()
