"""Public pulse for the /live page.

GET /v1/public/pulse     counts and sums over the demo departments plus a replay of synthetic labelled cases (cached about 15 s)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.policy import Public
from app.modules.pulse import service
from app.modules.pulse.schemas import PulseOut

router = APIRouter(tags=["public"])
_open = Public("aggregate counts and a synthetic replay for the public /live page; no personal data; rate limited per network", cost=2)


@router.get("/v1/public/pulse", response_model=PulseOut, summary="Live counts and a synthetic replay for the /live page")
def get_pulse(_: None = Depends(_open)) -> PulseOut:
    return PulseOut.model_validate(service.pulse())
