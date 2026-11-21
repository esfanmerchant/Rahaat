"""The feature-phone channel: USSD sessions and SMS commands for people without a smartphone.

    handle_ussd(channel, session_id=..., msisdn=..., text=...)   -> menu.Reply  (CON or END)
    handle_sms(channel, msisdn=..., text=..., message_id=...)    -> SmsOutcome

A `Channel` is who carries the traffic: an API key with the `channels:ussd` or `channels:sms` scope (an aggregator), or
the demo relay (`demo_channel`, only while `DEMO_MODE` is on). The channel proves nothing about the person. The person
proves themself on the line:

* status: the tracking code together with the phone number. The lookup runs as that citizen (RLS context `citizen`
  with their person id), so another person's code is simply not found; unknown phone and wrong code answer the same.
* stop sharing: the PIN. It is checked like a sign-in (always one hash verification, the account lockout counters, a
  per-phone bucket for unknown numbers) and then the real consent service withdraws every active consent.
* callback: a `complaint` case in the officer queue with a handoff note. If the number is not registered the reply is
  the same and no case is opened ("if this number is registered, a person will call you").

Only mock numbers are accepted; a real-looking number is refused before anything is stored. Phone numbers are never
stored in clear here: sessions hold a blind index. A PIN is never logged, audited or stored. Every action writes an
audit row whose details name the channel (`ussd` or `sms`), a short reference of the phone and the outcome.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.contracts.decision import HandoffPackage
from app.core import audit, metrics, ratelimit
from app.core.config import get_settings
from app.core.crypto import blind_index
from app.core.db import RlsContext, session_scope, system_session
from app.core.deps import Principal
from app.core.logging import get_logger
from app.core.mockdata import normalise_mock_phone
from app.core.security import verify_secret
from app.db import models
from app.modules.applications.timeline import symbols_for
from app.modules.cases.service import open_case
from app.modules.consent import service as consent_service
from app.modules.notifications import service as notifications
from app.modules.people.context import PersonContext
from app.modules.ussd import menu, smscmd, texts

log = get_logger("rahat.ussd")

API_CLIENT_ROLE = "api_client"
STALE_SESSION_AFTER = timedelta(minutes=10)
REQUESTS_PER_MINUTE = 30  # key presses or texts per phone
LOOKUP_PER_MINUTE = 6  # tracking-code lookups per phone
PIN_TRIES_PER_MINUTE = 5  # PIN tries per phone, known number or not
CALLBACK_REASON = "callback_requested"
SCAM_LABELS = frozenset({"relief_scam", "phishing_link", "advance_fee", "impersonation"})


@dataclass(frozen=True, slots=True)
class Channel:
    """Who carries the traffic. `kind` is `ussd` or `sms`; `actor_id` is the API key id (None for the demo relay)."""

    tenant_id: UUID
    kind: str
    actor_id: UUID | None = None
    actor_type: str = "api_key"
    actor_role: str = API_CLIENT_ROLE
    label: str = "key"

    def rls(self) -> RlsContext:
        return RlsContext(role=API_CLIENT_ROLE, tenant_id=self.tenant_id, user_id=self.actor_id)


def demo_channel(kind: str, tenant_id: UUID) -> Channel:
    return Channel(tenant_id=tenant_id, kind=kind, actor_id=None, actor_type="system", actor_role="demo_channel", label="demo relay")


@dataclass(frozen=True, slots=True)
class Citizen:
    user_id: UUID
    person_id: UUID
    lang: str


@dataclass(frozen=True, slots=True)
class SmsOutcome:
    accepted: bool
    command: str  # status | verify | stop | help | unknown | bad_argument | duplicate | rejected | throttled
    reply_key: str | None = None
    reply_sent: bool = False


# --- who is on the line ---------------------------------------------------------------------------------------


def canonical_msisdn(raw: str) -> str | None:
    """`0999-NNNNNNN` for a mock number in any common spelling, else None. A real number is never accepted."""
    return normalise_mock_phone(raw or "")


def phone_key(tenant_id: UUID, phone: str) -> str:
    return blind_index(phone, scope=str(tenant_id))


def _ref(tenant_id: UUID, phone: str) -> str:
    return phone_key(tenant_id, phone)[:12]


def _allow(tenant_id: UUID, key: str, per_minute: int, *, label: str) -> bool:
    """Take one token from a per-phone bucket. True when allowed. Honours the global rate-limit switch."""
    if not get_settings().rate_limits().enabled:
        return True
    charge = ratelimit.Charge("user", f"{label}:{tenant_id}:{key}", per_minute, tenant_id, label=f"{label}:{key[:8]}")
    refusal = ratelimit.LIMITER.take([charge])
    if refusal is not None:
        metrics.RATE_LIMITED.labels("user").inc()
        return False
    return True


def find_citizen(tenant_id: UUID, phone: str) -> Citizen | None:
    """The citizen who signed up with this number in this department. A narrow pre-authentication lookup, like sign-in."""
    with system_session() as db:
        row = db.execute(
            select(models.User.id, models.User.lang, models.Membership.person_id)
            .join(models.Membership, models.Membership.user_id == models.User.id)
            .where(
                models.User.phone_hash == blind_index(phone),
                models.User.status == "active",
                models.Membership.tenant_id == tenant_id,
                models.Membership.role == "citizen",
                models.Membership.status == "active",
                models.Membership.person_id.is_not(None),
            )
            .limit(1)
        ).first()
    if row is None or row.person_id is None:
        return None
    return Citizen(user_id=row.id, person_id=row.person_id, lang=row.lang)


def citizen_rls(tenant_id: UUID, citizen: Citizen) -> RlsContext:
    return RlsContext(role="citizen", tenant_id=tenant_id, user_id=citizen.user_id, person_id=citizen.person_id)


def _audit(db: Session, channel: Channel, action: str, *, person_id: UUID | None = None, result: str = "ok", reason: str | None = None,
           object_type: str | None = None, object_id: UUID | str | None = None, details: dict[str, Any] | None = None) -> None:  # fmt: skip
    audit.write(db, tenant_id=channel.tenant_id, action=action, actor_type=channel.actor_type, actor_id=channel.actor_id,
                actor_role=channel.actor_role, acting_for_person_id=person_id, object_type=object_type, object_id=object_id,
                result=result, reason=reason, details={"channel": channel.kind, **(details or {})})  # fmt: skip


def _audit_alone(channel: Channel, action: str, **fields: Any) -> None:
    with session_scope(channel.rls()) as db:
        _audit(db, channel, action, **fields)


# --- what the person may do -----------------------------------------------------------------------------------


class Actions:
    """The effects behind the menu. One instance serves one request for one phone number (the `menu.Backend`)."""

    def __init__(self, channel: Channel, phone: str, citizen: Citizen | None) -> None:
        self.channel, self.phone, self.citizen = channel, phone, citizen
        self.tenant_id = channel.tenant_id
        self.ref = _ref(channel.tenant_id, phone)

    # status: tracking code and phone must match
    def status(self, digits: str) -> menu.StatusInfo | None:
        code = f"R-{digits}"
        found = None
        person_id = self.citizen.person_id if self.citizen else uuid.UUID(int=0)  # same query for an unknown phone
        ctx = citizen_rls(self.tenant_id, self.citizen) if self.citizen else self.channel.rls()
        if not _allow(self.tenant_id, self.ref, LOOKUP_PER_MINUTE, label="ussd-lookup"):
            return None  # too many lookups from one phone: the same "not found" as a wrong code
        with session_scope(ctx) as db:
            application = db.scalar(select(models.Application).where(
                models.Application.tenant_id == self.tenant_id, models.Application.person_id == person_id,
                models.Application.tracking_code == code).limit(1))  # fmt: skip
            if application is not None:
                found = menu.StatusInfo(code=code, status=application.status, symbols=tuple(symbols_for(code)))
            _audit(db, self.channel, "channel.status_checked", person_id=self.citizen.person_id if self.citizen else None,
                   object_type="application", object_id=application.id if application else None,
                   details={"found": found is not None, "phone_ref": self.ref})  # fmt: skip
        return found

    # message check: is this a code we really sent
    def verify(self, code: str) -> bool:
        genuine = notifications.lookup_verify_code(code).genuine
        _audit_alone(self.channel, "channel.message_checked", details={"genuine": genuine, "phone_ref": self.ref})
        return genuine

    # stop sharing: PIN, then the real consent withdrawal
    def stop(self, pin: str) -> menu.StopOutcome:
        if not _allow(self.tenant_id, self.ref, PIN_TRIES_PER_MINUTE, label="ussd-pin"):
            _audit_alone(self.channel, "channel.consent_stop_refused", result="denied", reason="pin_tries_exceeded", details={"phone_ref": self.ref})
            return "locked"
        verdict = _check_pin(self.citizen.user_id if self.citizen else None, pin)
        if verdict != "ok" or self.citizen is None:
            reason = "locked" if verdict == "locked" else "pin_not_accepted"
            _audit_alone(self.channel, "channel.consent_stop_refused", result="denied", reason=reason,
                         person_id=self.citizen.person_id if self.citizen else None, details={"phone_ref": self.ref})  # fmt: skip
            return "locked" if verdict == "locked" else "bad_pin"
        self._withdraw_all(self.citizen)
        return "done"

    def _withdraw_all(self, citizen: Citizen) -> int:
        """Withdraw every active consent the department holds for this person, through the real consent service."""
        principal = Principal(user_id=citizen.user_id, tenant_id=self.tenant_id, role="citizen", person_id=citizen.person_id)
        ctx = PersonContext(principal=principal, person_id=citizen.person_id, via_helper=False, scope="track")
        with session_scope(citizen_rls(self.tenant_id, citizen)) as db:
            ids = list(db.scalars(select(models.Consent.id).where(
                models.Consent.tenant_id == self.tenant_id, models.Consent.person_id == citizen.person_id,
                models.Consent.grantee_type == "tenant", models.Consent.status == "active").order_by(models.Consent.created_at)).all())  # fmt: skip
            for consent_id in ids:
                consent_service.withdraw(db, ctx, consent_id)  # commits; audits `consent.withdrawn`; holds applications
            _audit(db, self.channel, "channel.consent_withdrawn", person_id=citizen.person_id, object_type="person", object_id=citizen.person_id,
                   details={"consents_withdrawn": len(ids), "phone_ref": self.ref})  # fmt: skip
        return len(ids)

    # talk to a person: a callback case, one at a time per person
    def callback(self) -> None:
        if self.citizen is None:
            _audit_alone(self.channel, "channel.callback_requested", details={"registered": False, "phone_ref": self.ref})
            return
        with session_scope(citizen_rls(self.tenant_id, self.citizen)) as db:
            existing = db.scalar(select(models.Case.id).where(
                models.Case.tenant_id == self.tenant_id, models.Case.subject_person_id == self.citizen.person_id,
                models.Case.kind == "complaint", models.Case.opened_reason == CALLBACK_REASON,
                models.Case.status.in_(("open", "assigned", "in_review", "escalated"))).limit(1))  # fmt: skip
            case_id = existing
            if existing is None:
                package = HandoffPackage(
                    question="This person asked for a call back from a feature phone.",
                    understanding=f"Asked on the {self.channel.kind.upper()} channel. No application detail was shared on the line.",
                    suggested_question="Call the phone number on file and ask how we can help.",
                    guards=[f"channel:{self.channel.kind}", "callback"],
                )
                case = open_case(db, tenant_id=self.tenant_id, kind="complaint", opened_reason=CALLBACK_REASON,
                                 person_id=self.citizen.person_id, handoff=package, priority=40)  # fmt: skip
                case_id = case.id
            _audit(db, self.channel, "channel.callback_requested", person_id=self.citizen.person_id, object_type="case", object_id=case_id,
                   details={"registered": True, "new_case": existing is None, "phone_ref": self.ref})  # fmt: skip


def _check_pin(user_id: UUID | None, pin: str) -> str:
    """`ok`, `bad` or `locked`, like a sign-in: one hash verification whether or not the account exists, and the same
    failure counters, so a wrong PIN on the phone counts toward the account lockout."""
    settings = get_settings()
    now = datetime.now(UTC)
    with system_session() as db:
        user = db.scalar(select(models.User).where(models.User.id == user_id).with_for_update()) if user_id else None
        pin_ok = verify_secret(user.password_hash if user else None, pin)
        if user is not None and user.locked_until and user.locked_until > now:
            return "locked"
        if user is None or not pin_ok:
            if user is not None:
                user.failed_logins += 1
                if user.failed_logins >= settings.login_max_failures:
                    user.failed_logins = 0
                    user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                    details = {"minutes": settings.login_lock_minutes, "via": "feature_phone"}
                    db.add(models.SecurityEvent(tenant_id=audit.PLATFORM_TENANT_ID, kind="lockout", severity="medium",
                                                actor_user_id=user.id, details=details))  # fmt: skip
                    return "locked"
            return "bad"
        user.failed_logins = 0
        return "ok"


# --- USSD -----------------------------------------------------------------------------------------------------


def _session_key(session_id: str) -> str:
    return blind_index(session_id, scope="ussd-session")


def _purge_stale(db: Session, tenant_id: UUID) -> None:
    db.execute(delete(models.UssdSession).where(models.UssdSession.tenant_id == tenant_id,
                                                models.UssdSession.updated_at < datetime.now(UTC) - STALE_SESSION_AFTER))  # fmt: skip


def handle_ussd(channel: Channel, *, session_id: str, msisdn: str, text: str, now: float | None = None) -> menu.Reply:
    """One request from the aggregator. `text` is the `*`-joined history; only its last item is this key press."""
    phone = canonical_msisdn(msisdn)
    if phone is None:
        _audit_alone(channel, "channel.refused", result="denied", reason="not_a_mock_number")
        return menu.Reply("END", "This prototype accepts only mock numbers.")
    key = phone_key(channel.tenant_id, phone)
    if not _allow(channel.tenant_id, key, REQUESTS_PER_MINUTE, label="ussd-requests"):
        return menu.throttled_reply()
    clock = now if now is not None else time.time()
    segments = [s for s in (text or "").split("*")] if text else []
    steps = len(segments)
    skey = _session_key(session_id)
    try:
        with session_scope(channel.rls()) as db:
            row = db.scalar(select(models.UssdSession).where(models.UssdSession.tenant_id == channel.tenant_id,
                                                            models.UssdSession.session_key == skey)
                            .order_by(models.UssdSession.created_at.desc()).limit(1).with_for_update())  # fmt: skip
            if row is None:
                _purge_stale(db, channel.tenant_id)
                state, reply = menu.start()
                row = models.UssdSession(tenant_id=channel.tenant_id, session_key=skey, msisdn_hash=key, state=state.state,
                                         data={}, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))  # fmt: skip
                db.add(row)
                _remember(row, state, reply, clock, steps, text)
                return reply
            data = dict(row.data or {})
            state = menu.Ussd.from_dict({**data, "state": row.state})
            if row.state == "ended":
                db.delete(row)  # the dial after an END starts over
                state, reply = menu.start()
                row = models.UssdSession(tenant_id=channel.tenant_id, session_key=skey, msisdn_hash=key, state=state.state,
                                         data={}, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))  # fmt: skip
                db.add(row)
                _remember(row, state, reply, clock, steps, text)
                return reply
            if row.msisdn_hash != key:  # a session id belongs to one phone
                _audit(db, channel, "channel.refused", result="denied", reason="session_phone_mismatch")
                return menu.error_reply(state.lang)
            if data.get("n") == steps and data.get("text") == (text or "") and data.get("reply"):
                return _stored_reply(data)  # the aggregator sent the same request again
            if menu.timed_out(float(data.get("at") or 0), clock):
                reply = menu.timeout_reply(state.lang)
                row.state, row.data, row.updated_at = (
                    "ended",
                    {"at": clock, "n": steps, "text": text or "", "reply": reply.wire, "lang": state.lang},
                    datetime.now(UTC),
                )
                return reply
            citizen = find_citizen(channel.tenant_id, phone)
            actions = Actions(channel, phone, citizen)
            state, reply = menu.step(state, segments[-1] if segments else "", actions)
            _remember(row, state, reply, clock, steps, text)
            return reply
    except Exception:  # noqa: BLE001  (an aggregator needs a plain answer, never a stack trace)
        log.exception("ussd request failed")
        return menu.error_reply()


def _stored_reply(data: dict[str, Any]) -> menu.Reply:
    wire = str(data.get("reply") or "")
    return menu.Reply("END" if wire.startswith("END") else "CON", wire[4:])


def _remember(row: models.UssdSession, state: menu.Ussd, reply: menu.Reply, clock: float, steps: int, text: str | None) -> None:
    ended = reply.kind == "END"
    row.state = "ended" if ended else state.state
    row.data = {**state.to_dict(), "view": "", "at": clock, "n": steps, "text": text or "", "reply": reply.wire}
    row.updated_at = datetime.now(UTC)


# --- SMS ------------------------------------------------------------------------------------------------------


def _reply_text(command: smscmd.Command, actions: Actions) -> tuple[str, str]:
    """(template key, text) for one parsed command; the effects run here."""
    lang = command.lang
    if command.kind == "status":
        info = actions.status(command.arg)
        if info is None:
            return "status_none", texts.sms("status_none", lang)
        return "status_ok", texts.sms("status_ok", lang, code=info.code, symbols=texts.symbols_text(info.symbols, lang),
                                      line=texts.status_line(info.status, lang))  # fmt: skip
    if command.kind == "verify":
        key = "verify_genuine" if actions.verify(command.arg) else "verify_unknown"
        return key, texts.sms(key, lang)
    if command.kind == "stop":
        outcome = actions.stop(command.arg)
        key = {"done": "stop_done", "locked": "stop_locked"}.get(outcome, "stop_bad")
        return key, texts.sms(key, lang)
    return "help", texts.sms("help", lang)


def _unrecognised(actions: Actions, text: str) -> tuple[str, str]:
    """Free text that is not a command: say if it looks like a scam (the same classifier as the scam checker), else help."""
    from app.modules.scam.service import classify_message

    verdict = classify_message(text, None)
    scam = verdict.choice in SCAM_LABELS and not verdict.abstained
    _audit_alone(actions.channel, "channel.message_unrecognised", details={"phone_ref": actions.ref, "scam_label": verdict.choice if scam else None})
    key = "scam_warning" if scam else "help"
    return key, texts.sms(key, "en")


def handle_sms(channel: Channel, *, msisdn: str, text: str, message_id: str | None = None) -> SmsOutcome:
    phone = canonical_msisdn(msisdn)
    if phone is None:
        _audit_alone(channel, "channel.refused", result="denied", reason="not_a_mock_number")
        return SmsOutcome(False, "rejected")
    key = phone_key(channel.tenant_id, phone)
    if not _allow(channel.tenant_id, key, REQUESTS_PER_MINUTE, label="ussd-requests"):
        return SmsOutcome(False, "throttled")  # no reply: a reply to a flood is a flood
    if message_id:
        dedupe = _session_key(f"sms:{message_id}")
        with session_scope(channel.rls()) as db:
            if (
                db.scalar(
                    select(models.UssdSession.id)
                    .where(models.UssdSession.tenant_id == channel.tenant_id, models.UssdSession.session_key == dedupe)
                    .limit(1)
                )
                is not None
            ):
                return SmsOutcome(True, "duplicate")
            _purge_stale(db, channel.tenant_id)
            db.add(models.UssdSession(tenant_id=channel.tenant_id, session_key=dedupe, msisdn_hash=key, state="sms", data={},
                                      created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))  # fmt: skip
    citizen = find_citizen(channel.tenant_id, phone)
    actions = Actions(channel, phone, citizen)
    command = smscmd.parse(text)
    try:
        if command.kind == "unknown":
            template, body = _unrecognised(actions, text)
            lang = "en"
        else:
            template, body = _reply_text(command, actions)
            lang = command.lang
    except Exception:  # noqa: BLE001
        log.exception("sms command failed")
        return SmsOutcome(True, command.kind, None, False)
    with session_scope(channel.rls()) as db:
        row = notifications.send_reply(db, tenant_id=channel.tenant_id, person_id=citizen.person_id if citizen else None, phone=phone,
                                       template=f"channel_{template}", lang=lang, text=body, channel_label=channel.kind)  # fmt: skip
        sent = row.status == "sent"
    return SmsOutcome(True, command.kind, template, sent)
