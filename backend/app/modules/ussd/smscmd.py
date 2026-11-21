"""SMS commands, parsed without a database: STATUS, VERIFY, STOP and HELP in English and Roman Urdu.

    parse("status R-48213")   -> Command("status", "48213", "en")
    parse("halat 48213")      -> Command("status", "48213", "ru")
    parse("STOP 4826")        -> Command("stop", "4826", "en")
    parse("hello")            -> Command("unknown", "", "en")

The keyword decides the reply language (Roman Urdu keyword, Roman Urdu reply). A command with a missing or
malformed argument is `bad_argument`, so the reply can say what to send instead. The PIN of a STOP command is only
ever held in memory for the length of the request: it is not logged, not audited and not stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

Kind = Literal["status", "verify", "stop", "help", "unknown", "bad_argument"]

KEYWORDS: Final[dict[str, tuple[Kind, str]]] = {
    "STATUS": ("status", "en"), "HALAT": ("status", "ru"), "HAAL": ("status", "ru"),
    "VERIFY": ("verify", "en"), "CHECK": ("verify", "en"), "TASDEEQ": ("verify", "ru"), "JANCH": ("verify", "ru"),
    "STOP": ("stop", "en"), "ROKEIN": ("stop", "ru"), "ROKO": ("stop", "ru"), "BAND": ("stop", "ru"),
    "HELP": ("help", "en"), "MADAD": ("help", "ru"),
}  # fmt: skip

MAX_SMS_CHARS = 320
_SPLIT = re.compile(r"[\s,:;]+")
_DIGITS = re.compile(r"[^0-9]")
_ALNUM = re.compile(r"[^A-Za-z0-9]")


@dataclass(frozen=True, slots=True)
class Command:
    kind: Kind
    arg: str = ""
    lang: str = "en"


def parse(text: str) -> Command:
    """The command in an inbound message. Never raises."""
    words = [w for w in _SPLIT.split((text or "")[:MAX_SMS_CHARS].strip()) if w]
    if not words:
        return Command("unknown")
    keyword = KEYWORDS.get(_ALNUM.sub("", words[0]).upper())
    if keyword is None:
        return Command("unknown")
    kind, lang = keyword
    rest = "".join(words[1:])
    if kind == "help":
        return Command("help", "", lang)
    if kind == "status":
        digits = _DIGITS.sub("", rest)
        # `R-48213`, `R48213` and `48213` are all the same code.
        return (
            Command("status", digits, lang)
            if len(digits) == 5 and re.fullmatch(r"(?i)r?-?[0-9]{5}", rest)
            else Command("bad_argument", "status", lang)
        )
    if kind == "verify":
        code = _ALNUM.sub("", rest).upper()
        return Command("verify", code, lang) if len(code) == 6 else Command("bad_argument", "verify", lang)
    pin = rest
    return Command("stop", pin, lang) if re.fullmatch(r"[0-9]{4,6}", pin) else Command("bad_argument", "stop", lang)
