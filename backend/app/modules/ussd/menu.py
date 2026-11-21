"""The USSD menu as a pure state machine. No database, no clock, no network: a backend object does the lookups.

    start()                      -> (state, reply)     first screen of a new session: choose a language
    step(state, text, backend)   -> (state, reply)     one key press (the last item of the aggregator's `*` history)
    timed_out(last_at, now)      -> bool               sessions end after 3 minutes without input

Menu tree (0 goes back one screen, 00 goes to the main menu):

    lang        1 English, 2 Roman Urdu
      menu      1 Check my application -> status_ask -> status_result
                2 Check a message      -> verify_ask -> verify_result
                3 Stop sharing my data -> stop_ask (PIN) -> END
                4 Talk to a person     -> callback_confirm (1 yes) -> END

A reply is `CON <text>` (the session goes on) or `END <text>` (it is over). Every screen is at most 182 characters.
Wrong codes are never explained beyond "not found": the same answer whether the code or the phone is wrong.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from app.modules.ussd import texts

SESSION_TTL_SECONDS = 180
MAX_BAD_TRIES = 3

STATES = (
    "lang", "menu", "status_ask", "status_result", "verify_ask", "verify_result", "stop_ask", "callback_confirm",
)  # fmt: skip
_PARENT = {
    "menu": "lang", "status_ask": "menu", "status_result": "status_ask", "verify_ask": "menu", "verify_result": "verify_ask",
    "stop_ask": "menu", "callback_confirm": "menu",
}  # fmt: skip

StopOutcome = Literal["done", "bad_pin", "locked"]


@dataclass(frozen=True, slots=True)
class StatusInfo:
    """What a person has proven they may see: the status and the code's pictograms. Nothing else."""

    code: str
    status: str
    symbols: tuple[str, ...]


class Backend(Protocol):
    def status(self, digits: str) -> StatusInfo | None: ...
    def verify(self, code: str) -> bool: ...
    def stop(self, pin: str) -> StopOutcome: ...
    def callback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Ussd:
    state: str = "lang"
    lang: str = "en"
    bad: int = 0
    view: str = ""  # the text of a result screen, so a repeated request can show it again

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> Ussd:
        state = str(raw.get("state") or "lang")
        return Ussd(state=state if state in STATES else "lang", lang=texts.pick_lang(str(raw.get("lang") or "en")),
                    bad=max(0, int(raw.get("bad") or 0)), view=str(raw.get("view") or "")[: texts.USSD_LIMIT])  # fmt: skip


@dataclass(frozen=True, slots=True)
class Reply:
    kind: Literal["CON", "END"]
    text: str

    @property
    def wire(self) -> str:
        return f"{self.kind} {self.text}"


def con(text: str) -> Reply:
    return Reply("CON", text)


def end(key: str, lang: str) -> Reply:
    return Reply("END", texts.screen(key, lang))


def screen_for(state: Ussd) -> str:
    """The text to show for a state."""
    if state.state in ("status_result", "verify_result"):
        return state.view
    return texts.screen(state.state, state.lang)


def start() -> tuple[Ussd, Reply]:
    state = Ussd()
    return state, con(screen_for(state))


def timed_out(last_at: float, now: float) -> bool:
    return now - last_at > SESSION_TTL_SECONDS


def timeout_reply(lang: str = "en") -> Reply:
    return end("timeout", lang)


def throttled_reply(lang: str = "en") -> Reply:
    return end("throttled", lang)


def error_reply(lang: str = "en") -> Reply:
    return end("error", lang)


_DIGITS = re.compile(r"[^0-9]")
_ALNUM = re.compile(r"[^A-Za-z0-9]")


def _to(state: Ussd, new: str, **changes: Any) -> tuple[Ussd, Reply]:
    nxt = Ussd(**{**state.to_dict(), "state": new, **changes})
    return nxt, con(screen_for(nxt))


def _retry(state: Ussd, key: str, *, count_bad: bool) -> tuple[Ussd, Reply]:
    """Stay on the same state with a short message. Three wrong tries end the session."""
    bad = state.bad + (1 if count_bad else 0)
    if bad >= MAX_BAD_TRIES:
        return Ussd(state="lang", lang=state.lang, bad=bad), end("too_many", state.lang)
    return Ussd(**{**state.to_dict(), "bad": bad}), con(texts.screen(key, state.lang))


def _invalid(state: Ussd) -> tuple[Ussd, Reply]:
    text = f"{texts.screen('wrong', state.lang)}\n{screen_for(state)}"
    return state, con(text[: texts.USSD_LIMIT])


def _status_step(state: Ussd, text: str, backend: Backend) -> tuple[Ussd, Reply]:
    digits = _DIGITS.sub("", text)
    if len(digits) != 5:
        return _retry(state, "status_format", count_bad=False)
    info = backend.status(digits)
    if info is None:
        return _retry(state, "status_none", count_bad=True)
    view = texts.screen("status_result", state.lang, code=info.code, symbols=texts.symbols_text(info.symbols, state.lang),
                        line=texts.status_line(info.status, state.lang))  # fmt: skip
    return _to(state, "status_result", bad=0, view=view)


def _verify_step(state: Ussd, text: str, backend: Backend) -> tuple[Ussd, Reply]:
    code = _ALNUM.sub("", text).upper()
    if len(code) != 6:
        return _retry(state, "verify_format", count_bad=False)
    key = "verify_genuine" if backend.verify(code) else "verify_unknown"
    return _to(state, "verify_result", view=texts.screen(key, state.lang))


def _stop_step(state: Ussd, text: str, backend: Backend) -> tuple[Ussd, Reply]:
    pin = _DIGITS.sub("", text)
    if not 4 <= len(pin) <= 6 or pin != text.strip():
        return _retry(state, "stop_format", count_bad=False)
    outcome = backend.stop(pin)
    if outcome == "done":
        return Ussd(state="lang", lang=state.lang), end("stop_done", state.lang)
    if outcome == "locked":
        return Ussd(state="lang", lang=state.lang, bad=MAX_BAD_TRIES), end("stop_locked", state.lang)
    return _retry(state, "stop_bad", count_bad=True)


def step(state: Ussd, raw: str, backend: Backend) -> tuple[Ussd, Reply]:
    """One key press. Never raises on any input; unknown input shows the same screen again."""
    text = (raw or "").strip()[:64]
    here = state.state
    if here == "lang":
        if text == "1" or text == "2":
            return _to(Ussd(lang="en" if text == "1" else "ru"), "menu")
        if text == "0":
            return Ussd(), end("bye", state.lang)
        return _invalid(state)
    if text == "00":
        return _to(state, "menu", bad=0)
    if text == "0":
        return _to(state, _PARENT[here], bad=0)
    if here == "menu":
        if text == "1":
            return _to(state, "status_ask", bad=0)
        if text == "2":
            return _to(state, "verify_ask", bad=0)
        if text == "3":
            return _to(state, "stop_ask", bad=0)
        if text == "4":
            return _to(state, "callback_confirm", bad=0)
        return _invalid(state)
    if here in ("status_ask", "status_result"):  # on a result, typing digits is "check another"
        return _status_step(state, text, backend)
    if here in ("verify_ask", "verify_result"):
        return _verify_step(state, text, backend)
    if here == "stop_ask":
        return _stop_step(state, text, backend)
    if here == "callback_confirm":
        if text == "1":
            backend.callback()
            return Ussd(state="lang", lang=state.lang), end("callback_done", state.lang)
        return _invalid(state)
    return _invalid(state)
