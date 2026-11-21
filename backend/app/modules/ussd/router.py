"""The feature-phone channel over HTTP.

    POST /v1/channels/ussd          an aggregator's USSD request; answers `CON ...` or `END ...` as plain text
    POST /v1/channels/sms/inbound   an aggregator's inbound SMS; the reply goes out through the mock SMS gateway

Both admit API keys only (`channels:ussd`, `channels:sms`); no signed-in user can call them. A key can carry the line
but proves nothing about the person: the person proves themself with a tracking code or PIN (see `service`).

The demo simulator (`/ussd` in the web app) never holds a key. It calls the demo relay below, which runs the same
service code with a server-side demo channel, in the demo department, for mock numbers only. The relay answers 404
unless `DEMO_MODE` is on, like `/v1/demo/accounts`.

    POST /v1/demo/ussd              one key press of the simulator (JSON in, JSON out)
    POST /v1/demo/sms               one text from the simulator
    GET  /v1/demo/sms               the messages the system sent to a mock number
    GET  /v1/demo/ussd/personas     the demo numbers, with the tracking code each can try
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import Field
from sqlalchemy import select

from app.contracts.common import Strict
from app.core.config import get_settings
from app.core.crypto import blind_index
from app.core.db import RlsContext, session_scope, system_session
from app.core.deps import Principal
from app.core.errors import NotFound, Unprocessable
from app.core.mockdata import international_mock_phone
from app.core.policy import Policy, Public
from app.db import models
from app.demo_accounts import DEMO_ACCOUNTS, DEMO_PIN, DEMO_TENANTS
from app.modules.applications.timeline import symbols_for
from app.modules.ussd import service
from app.modules.ussd.service import Channel
from app.modules.ussd.texts import SMS_LIMIT

router = APIRouter(tags=["channels (feature phone)"])

SESSION_ID = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$", description="The aggregator's session id")
MSISDN = Field(min_length=8, max_length=20, description="The caller's number. Only mock numbers (0999-NNNNNNN or +92 999NNNNNNN) are accepted")


class UssdIn(Strict):
    session_id: str = SESSION_ID
    msisdn: str = MSISDN
    text: str = Field(default="", max_length=200, description="The `*`-joined input history; empty on the first dial")
    service_code: str = Field(default="*786#", max_length=20, pattern=r"^\*[0-9*]{1,18}#$")


class SmsIn(Strict):
    msisdn: str = MSISDN
    text: str = Field(min_length=1, max_length=320)
    message_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$",
                                   description="The aggregator's message id; a repeat of the same id is answered once")  # fmt: skip


class SmsAccepted(Strict):
    accepted: bool
    command: str = Field(description="status, verify, stop, help, unknown, bad_argument, duplicate, rejected or throttled")
    reply_sent: bool


def _channel(principal: Principal, kind: str) -> Channel:
    assert principal.api_key is not None  # the policy admits keys only
    return Channel(tenant_id=principal.tenant_id, kind=kind, actor_id=principal.api_key.id, label=principal.api_key.prefix)


@router.post(
    "/v1/channels/ussd",
    response_class=PlainTextResponse,
    summary="USSD gateway: one request in an aggregator's shape. Answers plain text starting with CON or END",
    responses={200: {"content": {"text/plain": {"example": "CON Rahat (prototype)\n1 English\n2 Roman Urdu"}}}},
)
async def ussd(body: UssdIn, principal: Principal = Depends(Policy("channels:ussd", [], api_scopes=["channels:ussd"], cost=1))) -> PlainTextResponse:
    reply = await run_in_threadpool(service.handle_ussd, _channel(principal, "ussd"), session_id=body.session_id, msisdn=body.msisdn, text=body.text)
    return PlainTextResponse(reply.wire, headers={"Cache-Control": "no-store"})


@router.post(
    "/v1/channels/sms/inbound",
    response_model=SmsAccepted,
    summary="Inbound SMS: STATUS, VERIFY, STOP and HELP (English and Roman Urdu). The reply is sent as an SMS",
)
async def sms_inbound(body: SmsIn, principal: Principal = Depends(Policy("channels:sms", [], api_scopes=["channels:sms"], cost=1))) -> SmsAccepted:
    out = await run_in_threadpool(service.handle_sms, _channel(principal, "sms"), msisdn=body.msisdn, text=body.text, message_id=body.message_id)
    return SmsAccepted(accepted=out.accepted, command=out.command, reply_sent=out.reply_sent)


# --- the demo relay: no key in the browser ------------------------------------------------------------------


def _demo_tenant_id() -> UUID:
    if not get_settings().demo_mode:
        raise NotFound()
    slug = DEMO_TENANTS[0]["slug"]
    with system_session() as db:
        tenant_id = db.scalar(select(models.Tenant.id).where(models.Tenant.slug == slug, models.Tenant.status == "active"))
    if tenant_id is None:
        raise NotFound()
    return tenant_id


class DemoUssdOut(Strict):
    kind: str = Field(description="CON (the session goes on) or END")
    text: str


class DemoSmsMessage(Strict):
    id: str
    at: str
    body: str
    template: str


class DemoSmsOut(Strict):
    accepted: bool
    command: str
    reply_sent: bool
    messages: list[DemoSmsMessage]


class DemoPersona(Strict):
    name: str
    msisdn: str = Field(description="Mock number, 0999-NNNNNNN")
    display: str = Field(description="+92 999NNNNNNN")
    tracking_code: str | None = Field(description="The tracking code of the latest application, when there is one (demo only)")
    symbols: list[str]


class DemoPersonasOut(Strict):
    personas: list[DemoPersona]
    demo_pin: str
    service_code: str


@router.post(
    "/v1/demo/ussd",
    response_model=DemoUssdOut,
    summary="Simulator relay for one USSD key press (demo only)",
)
async def demo_ussd(
    body: UssdIn, _: None = Depends(Public("demo simulator relay: mock numbers only, no key in the browser; 404 outside demo mode", cost=2))
) -> DemoUssdOut:
    channel = service.demo_channel("ussd", _demo_tenant_id())
    reply = await run_in_threadpool(service.handle_ussd, channel, session_id=body.session_id, msisdn=body.msisdn, text=body.text)
    return DemoUssdOut(kind=reply.kind, text=reply.text)


def _thread(tenant_id: Any, phone: str, limit: int = 30) -> list[DemoSmsMessage]:
    with session_scope(RlsContext(role=service.API_CLIENT_ROLE, tenant_id=tenant_id)) as db:
        rows = db.scalars(
            select(models.Notification)
            .where(models.Notification.tenant_id == tenant_id, models.Notification.channel == "sms",
                   models.Notification.destination_hash == blind_index(phone, scope=str(tenant_id)),
                   models.Notification.template.like("channel_%"))
            .order_by(models.Notification.created_at.desc(), models.Notification.id).limit(limit)
        ).all()  # fmt: skip
        return [DemoSmsMessage(id=str(r.id), at=r.created_at.isoformat(timespec="seconds"), body=r.body[:SMS_LIMIT * 2], template=r.template)
                for r in reversed(rows)]  # fmt: skip


@router.post("/v1/demo/sms", response_model=DemoSmsOut, summary="Simulator relay for one inbound text (demo only)")
async def demo_sms(
    body: SmsIn, _: None = Depends(Public("demo simulator relay: mock numbers only, no key in the browser; 404 outside demo mode", cost=2))
) -> DemoSmsOut:
    tenant_id = _demo_tenant_id()
    channel = service.demo_channel("sms", tenant_id)
    out = await run_in_threadpool(service.handle_sms, channel, msisdn=body.msisdn, text=body.text, message_id=body.message_id)
    phone = service.canonical_msisdn(body.msisdn)
    messages = await run_in_threadpool(_thread, tenant_id, phone) if phone else []
    return DemoSmsOut(accepted=out.accepted, command=out.command, reply_sent=out.reply_sent, messages=messages)


@router.get("/v1/demo/sms", response_model=list[DemoSmsMessage], summary="Messages sent to a mock number by the channel (demo only)")
def demo_sms_thread(
    msisdn: str = Query(min_length=8, max_length=20),
    _: None = Depends(Public("demo simulator: the SMS thread of a mock number; 404 outside demo mode")),
) -> list[DemoSmsMessage]:
    tenant_id = _demo_tenant_id()
    phone = service.canonical_msisdn(msisdn)
    if phone is None:
        raise Unprocessable("Use a mock number: 0999-NNNNNNN.", code="mock_phone_format")
    return _thread(tenant_id, phone)


@router.get("/v1/demo/ussd/personas", response_model=DemoPersonasOut, summary="Demo numbers for the simulator (demo only)")
def demo_personas(
    _: None = Depends(Public("demo simulator: the demo numbers and their latest tracking code; 404 outside demo mode")),
) -> DemoPersonasOut:
    tenant_id = _demo_tenant_id()
    people: list[DemoPersona] = []
    for account in DEMO_ACCOUNTS:
        if account["kind"] != "citizen" or account["role"] != "citizen" or account["tenants"][0] != DEMO_TENANTS[0]["slug"]:
            continue
        phone = account["identifier"]
        citizen = service.find_citizen(tenant_id, phone)
        code = None
        if citizen is not None:
            with session_scope(service.citizen_rls(tenant_id, citizen)) as db:
                code = db.scalar(select(models.Application.tracking_code).where(
                    models.Application.tenant_id == tenant_id, models.Application.person_id == citizen.person_id,
                    models.Application.tracking_code.is_not(None)).order_by(models.Application.created_at.desc()).limit(1))  # fmt: skip
        people.append(DemoPersona(name=account["name"], msisdn=phone, display=international_mock_phone(phone) or phone, tracking_code=code,
                                  symbols=symbols_for(code)))  # fmt: skip
    return DemoPersonasOut(personas=people, demo_pin=DEMO_PIN, service_code="*786#")
