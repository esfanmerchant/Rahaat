from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.modules.scam import ratelimit


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> Iterator[None]:
    ratelimit.reset()
    yield
    ratelimit.reset()
