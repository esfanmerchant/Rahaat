"""A simulated customer server that receives Rahat webhooks, so they can be demoed with no outside network.

    PUT    /webhooks/config/{webhook_id}   the secret the "customer" holds (and, for demos, failure injection)
    POST   /webhooks/receive               verifies X-Rahat-Signature and keeps what it got
    GET    /webhooks/received              what arrived, newest first, with whether each signature was valid
    DELETE /webhooks/received              forget it

State is in this process's memory, like the rest of the mock services. Every call carries the webhook key
(`X-Mock-Key`). The receiver answers 401 to a bad or missing signature and an unknown webhook, 503 while it is told to fail.
"""

from __future__ import annotations

import hmac
import json
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core import webhook_signing
from app.mocks.config import get_mock_service_settings

router = APIRouter(prefix="/webhooks", tags=["mock webhook receiver"])


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str | None = Field(default=None, min_length=8, max_length=200)
    fail_next: int | None = Field(default=None, ge=0, le=100, description="Answer the next N deliveries with 503")
    down: bool | None = Field(default=None, description="Answer every delivery with 503 until set to false")


class Receiver:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.secrets: dict[str, str] = {}
        self.fail_next: dict[str, int] = {}
        self.down: set[str] = set()
        self.items: deque[dict[str, Any]] = deque(maxlen=300)
        self.seen: set[tuple[str, str]] = set()


RECEIVER = Receiver()


def _key_ok(presented: str | None) -> bool:
    expected = get_mock_service_settings().webhook_key
    return bool(presented) and hmac.compare_digest((presented or "").encode(), expected.encode())


def _refuse() -> JSONResponse:
    return JSONResponse({"code": "bad_key", "detail": "missing or wrong API key for the webhook receiver"}, status_code=401)


@router.put("/config/{webhook_id}")
def configure(webhook_id: str, body: _Config, x_mock_key: str | None = Header(default=None)) -> Any:
    if not _key_ok(x_mock_key):
        return _refuse()
    with RECEIVER.lock:
        if body.secret is not None:
            RECEIVER.secrets[webhook_id] = body.secret
        if body.fail_next is not None:
            RECEIVER.fail_next[webhook_id] = body.fail_next
        if body.down is not None:
            (RECEIVER.down.add if body.down else RECEIVER.down.discard)(webhook_id)
        return {"webhook_id": webhook_id, "has_secret": webhook_id in RECEIVER.secrets, "fail_next": RECEIVER.fail_next.get(webhook_id, 0),
                "down": webhook_id in RECEIVER.down}  # fmt: skip


@router.post("/receive")
async def receive(request: Request, x_mock_key: str | None = Header(default=None)) -> Any:
    if not _key_ok(x_mock_key):
        return _refuse()
    body = await request.body()
    h = request.headers
    webhook_id = h.get("x-rahat-webhook", "")
    delivery_id = h.get("x-rahat-delivery", "")
    item: dict[str, Any] = {
        "received_at": datetime.now(UTC).isoformat(timespec="seconds"), "webhook_id": webhook_id, "delivery_id": delivery_id,
        "event": h.get("x-rahat-event", ""), "timestamp": h.get("x-rahat-timestamp", ""), "signature": h.get("x-rahat-signature", ""),
        "signature_valid": False, "duplicate": False, "answered": 200, "body": None,
    }  # fmt: skip
    with RECEIVER.lock:
        secret = RECEIVER.secrets.get(webhook_id)
        if webhook_id in RECEIVER.down:
            item["answered"] = 503
        elif RECEIVER.fail_next.get(webhook_id, 0) > 0:
            RECEIVER.fail_next[webhook_id] -= 1
            item["answered"] = 503
        elif secret is None:
            item["answered"] = 401
        elif not webhook_signing.verify(secret, item["timestamp"], body, item["signature"], now=time.time()):
            item["answered"] = 401
        else:
            item["signature_valid"] = True
            key = (webhook_id, delivery_id)
            item["duplicate"] = key in RECEIVER.seen
            RECEIVER.seen.add(key)
            try:
                item["body"] = json.loads(body)
            except ValueError:
                item["body"] = None
        RECEIVER.items.appendleft(item)
    if item["answered"] == 200:
        return {"received": True, "duplicate": item["duplicate"]}
    code = {503: "service_unavailable", 401: "bad_signature"}[item["answered"]]
    return JSONResponse({"code": code}, status_code=item["answered"])


@router.get("/received")
def received(x_mock_key: str | None = Header(default=None), webhook_id: str | None = Query(default=None, max_length=64),
             limit: int = Query(default=50, ge=1, le=300)) -> Any:  # fmt: skip
    if not _key_ok(x_mock_key):
        return _refuse()
    with RECEIVER.lock:
        items = [i for i in RECEIVER.items if webhook_id is None or i["webhook_id"] == webhook_id]
    return {"items": items[:limit], "reachable": True}


@router.delete("/received")
def clear(x_mock_key: str | None = Header(default=None)) -> Any:
    if not _key_ok(x_mock_key):
        return _refuse()
    with RECEIVER.lock:
        RECEIVER.items.clear()
        RECEIVER.seen.clear()
    return {"ok": True}
