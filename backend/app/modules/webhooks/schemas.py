from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.contracts.common import Strict
from app.modules.webhooks import rules


def _events(values: list[str]) -> list[str]:
    bad = [v for v in values if not rules.valid_event(v)]
    if bad:
        raise ValueError(f"unknown events: {', '.join(bad[:3])}")
    return list(dict.fromkeys(values))


class WebhookCreate(Strict):
    url: str = Field(min_length=8, max_length=2000, description="https address of your server, or `mock://receiver` for the built-in demo receiver")
    events: list[str] = Field(min_length=1, max_length=10, description="Event names (GET /v1/admin/webhooks/events) or `*`")

    @field_validator("events")
    @classmethod
    def _check_events(cls, value: list[str]) -> list[str]:
        return _events(value)


class WebhookUpdate(Strict):
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    events: list[str] | None = Field(default=None, min_length=1, max_length=10)
    active: bool | None = Field(default=None, description="false disables the webhook: nothing new is queued for it")

    @field_validator("events")
    @classmethod
    def _check_events(cls, value: list[str] | None) -> list[str] | None:
        return _events(value) if value is not None else None


class WebhookOut(BaseModel):
    id: UUID
    url: str
    events: list[str]
    active: bool
    secret_hint: str = Field(description="The last 4 characters of the signing secret, to tell secrets apart")
    created_at: str
    created_by: UUID | None = None
    is_mock_receiver: bool = False
    deliveries_pending: int = 0
    deliveries_dead: int = 0


class WebhookCreated(WebhookOut):
    secret: str = Field(description="The signing secret. Shown once: only an encrypted copy is kept. Rotate it to get a new one.")


class DeliveryOut(BaseModel):
    id: UUID
    webhook_id: UUID
    event: str
    status: Literal["pending", "delivered", "failed", "dead"]
    attempts: int
    max_attempts: int
    response_code: int | None = None
    last_error: str | None = None
    next_attempt_at: str | None = None
    delivered_at: str | None = None
    created_at: str
    payload: dict[str, Any]


class DeliveryList(BaseModel):
    items: list[DeliveryOut]
    next_cursor: str | None = None


class EventOut(BaseModel):
    name: str
    description: str


class MockReceived(BaseModel):
    reachable: bool = True
    items: list[dict[str, Any]]
