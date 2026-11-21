"""Signals that are not the model: links, the sender, money asks and verify codes. Pure functions.

Nothing here fetches a URL, resolves a host name or contacts a sender. A link is analysed as a string and
shown back defanged (`hxxps://example[.]com`). Patterns are bounded so they stay linear on hostile input.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlsplit

from rapidfuzz import fuzz

from app.core.logging import redact
from app.modules.notifications import templates
from app.modules.scam.text import meaningful_words, normalise, script_of

DEFAULT_OFFICIAL_SENDER = "RAHAT"
MAX_TEXT_CHARS = 2000
MAX_URLS = 5

# --- links ----------------------------------------------------------------------------------------------

SHORTENERS = frozenset(
    "bit.ly bitly.com tinyurl.com t.co goo.gl is.gd cutt.ly rb.gy ow.ly tiny.cc s.id v.gd rebrand.ly buff.ly t.ly "
    "shorturl.at short.io bl.ink lnkd.in tr.im u.to clck.ru qr.ae adf.ly shorte.st bit.do x.co soo.gd t2m.io".split()
)
MESSAGING_HOSTS = frozenset("wa.me chat.whatsapp.com api.whatsapp.com t.me telegram.me".split())
HIGH_RISK_TLDS = frozenset(
    "xyz top icu buzz click link rest cam cyou sbs tk ml ga cf gq monster loan win bid kim men party review stream trade "
    "date racing download accountant science cricket faith pw su zip mov country gdn work".split()
)
KNOWN_TLDS = frozenset(
    "com net org pk info biz co io me app online site live store shop club vip cc ws us uk in ae sa xyz top icu buzz click "
    "link rest cam cyou sbs tk ml ga cf gq monster loan win bid kim men party review stream trade date racing download "
    "accountant science cricket faith pw su ly gl gd to fun space website tech gov edu ru work".split()
)
MULTI_SUFFIXES = frozenset("gov.pk com.pk org.pk net.pk edu.pk web.pk biz.pk fam.pk gok.pk gop.pk co.uk org.uk com.au co.in".split())
# Words that make a host look official. Strong ones count inside a longer word (rahat2026, govpk).
STRONG_OFFICIAL = ("rahat", "relief", "gov", "govt", "sarkar", "sarkari", "hukumat", "imdad", "imdadi", "official")
WEAK_OFFICIAL = frozenset({"government", "program", "programme", "fund", "portal", "benefit", "grant", "subsidy", "madad"})
PHISHY_WORDS = re.compile(r"(?i)(?:verify|verif|kyc|secure|login|signin|update|claim|bonus|prize|reward|gift|free|wallet|unlock|confirm)")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

_REFANG = (
    (re.compile(r"(?i)\bhxxp(s?)"), r"http\1"),
    (re.compile(r"\[\.\]|\(\.\)|\{\.\}|\[dot\]|\(dot\)"), "."),
    (re.compile(r"\[:\]"), ":"),
)
_TLD_ALT = "|".join(sorted(KNOWN_TLDS, key=len, reverse=True))
URL_PATTERN = re.compile(
    r"(?i)(?<![\w@./-])("
    r"https?://[^\s<>\"'`]{1,400}"
    r"|www\d{0,3}\.[^\s<>\"'`]{1,400}"
    r"|(?:[\w](?:[\w-]{0,62})\.){1,6}(?:" + _TLD_ALT + r")(?![\w-])(?:[/?#][^\s<>\"'`]{0,400})?"
    r"|(?:\d{1,3}\.){3}\d{1,3}(?::\d{2,5})?(?:/[^\s<>\"'`]{0,400})?"
    r")"
)
_TRAILING = ".,;:!?)]}'\"۔،"
_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")

URL_HIGH_RISK = frozenset({"official_name_in_subdomain", "lookalike_official", "ip_host", "punycode", "apk_download", "at_sign"})
URL_MEDIUM_RISK = frozenset({"shortener", "odd_tld", "http", "messaging_link", "phishy_words", "many_hyphens"})


@dataclass(frozen=True)
class UrlFinding:
    defanged: str
    host: str  # defanged
    flags: tuple[str, ...]
    risk: str  # high | medium | low


def refang(text: str) -> str:
    for pattern, replacement in _REFANG:
        text = pattern.sub(replacement, text)
    return text


def defang(url: str) -> str:
    """`https://a.b/c` -> `hxxps://a[.]b/c`. Query strings are cut: they often carry someone's details."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        scheme, rest = "", url
    host, slash, path = rest.partition("/")
    path, _, query = path.partition("?")
    shown = host.replace(".", "[.]") + (slash + path[:80] if slash else "") + ("?…" if query else "")
    if scheme:
        shown = re.sub(r"(?i)^http", "hxxp", scheme) + "://" + shown
    return redact(shown)


def _registrable(host: str) -> tuple[str, list[str]]:
    labels = [label for label in host.split(".") if label]
    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_SUFFIXES:
        return ".".join(labels[-3:]), labels[:-3]
    return ".".join(labels[-2:]), labels[:-2]


def _official_looking(label: str, official_names: tuple[str, ...]) -> bool:
    for token in re.split(r"[^a-z]+", label.lower().translate(_LEET)):
        if len(token) < 3:
            continue
        if token in WEAK_OFFICIAL or token in official_names:
            return True
        for term in (*STRONG_OFFICIAL, *official_names):
            if (token.startswith(term) or token.endswith(term)) and len(token) <= len(term) + 6:
                return True
        if len(token) >= 4 and any(fuzz.ratio(token, name) >= 80 for name in ("rahat", *official_names)):
            return True
    return False


def analyse_url(raw: str, *, official_domains: frozenset[str] = frozenset(), official_names: tuple[str, ...] = ()) -> UrlFinding | None:
    had_scheme = re.match(r"(?i)https?://", raw) is not None
    try:
        parts = urlsplit(raw if had_scheme else "http://" + raw)
        host = (parts.hostname or "").rstrip(".")
    except ValueError:
        return None
    if not host:
        return None
    flags: list[str] = []
    registrable, subdomains = _registrable(host)
    ip = _IPV4.match(host)
    if (ip and all(int(part) <= 255 for part in ip.groups())) or ":" in host:
        flags.append("ip_host")
    if "xn--" in host or any(ord(char) > 127 for char in host):
        flags.append("punycode")
    if "@" in parts.netloc:
        flags.append("at_sign")
    if had_scheme and parts.scheme.lower() == "http":
        flags.append("http")
    if host in SHORTENERS or registrable in SHORTENERS:
        flags.append("shortener")
    if host in MESSAGING_HOSTS or registrable in MESSAGING_HOSTS:
        flags.append("messaging_link")
    tld = host.rsplit(".", 1)[-1]
    if tld in HIGH_RISK_TLDS:
        flags.append("odd_tld")
    if parts.path.lower().endswith(".apk"):
        flags.append("apk_download")
    allowed = host in official_domains or registrable in official_domains or registrable.endswith(".gov.pk")
    if not ip and not allowed:
        main_label = registrable.split(".")[0]
        if _official_looking(main_label, official_names):
            flags.append("lookalike_official")
        elif any(_official_looking(label, official_names) for label in subdomains):
            flags.append("official_name_in_subdomain")
    if host.replace("xn--", "").count("-") >= 3:
        flags.append("many_hyphens")
    if PHISHY_WORDS.search(host + parts.path):
        flags.append("phishy_words")
    risk = "high" if URL_HIGH_RISK.intersection(flags) else "medium" if URL_MEDIUM_RISK.intersection(flags) else "low"
    return UrlFinding(defanged=defang(raw), host=host.replace(".", "[.]"), flags=tuple(flags), risk=risk)


def find_urls(text: str) -> list[str]:
    found: list[str] = []
    for match in URL_PATTERN.finditer(refang(text)):
        url = match.group(1).rstrip(_TRAILING)
        if url and url not in found:
            found.append(url)
        if len(found) >= MAX_URLS:
            break
    return found


# --- the sender -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SenderInfo:
    kind: str  # none | official | lookalike | mobile | short_code | number | alpha
    shown: str | None  # masked when it is a number


def _squash_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def analyse_sender(sender: str | None, official_sender: str = DEFAULT_OFFICIAL_SENDER) -> SenderInfo:
    if not sender or not sender.strip():
        return SenderInfo("none", None)
    value = normalise(sender)[:64]
    digits = re.sub(r"\D", "", value)
    if re.fullmatch(r"[+\d\s().-]{3,24}", value) and digits:
        masked = "•" * max(len(digits) - 3, 0) + digits[-3:]
        if re.fullmatch(r"(?:0092|92|0)?(?:3\d{9}|999\d{7})", digits):
            return SenderInfo("mobile", masked)
        if len(digits) <= 6:
            return SenderInfo("short_code", digits)
        return SenderInfo("number", masked)
    name, official = _squash_name(value), _squash_name(official_sender or DEFAULT_OFFICIAL_SENDER)
    if name == official:
        return SenderInfo("official", value.upper())
    leet = name.lower().translate(_LEET)
    if official.lower() in leet or fuzz.ratio(leet, official.lower()) >= 70 or fuzz.partial_ratio(official.lower(), leet) >= 80:
        return SenderInfo("lookalike", value.upper())
    if any(_official_looking(part, ()) for part in re.split(r"[^a-z0-9]+", value.lower()) if part):
        return SenderInfo("lookalike", value.upper()[:32])  # GOVT-RELIEF: official-sounding, and not our sender
    return SenderInfo("alpha", value.upper()[:32])


# --- money asks and other cues --------------------------------------------------------------------------


def _ur(*words: str) -> str:
    """Urdu words with letter boundaries, so 'پن' (PIN) does not match inside 'اپنا'."""
    return "|".join(rf"(?<![؀-ۿ]){w}(?![؀-ۿ])" for w in words)


_ASK = re.compile(
    r"(?i)\b(?:send|pay|deposit|transfer|share|tell|give|provide|forward|reply(?:\s+with)?|text\s+us|whatsapp\s+us"
    r"|bhej(?:ein|en|ain|o|iye|ye)|bhej\s+(?:dein|den|dain|do|dijiye|dijye)|jama\s+(?:karwain|karwayen|karwaein|karain|karein|karen|kar\s+dein"
    r"|krwa\s+dein|karwa\s+dein|karo|karwao|kr\s+dein)|ada\s+(?:karein|karen|karain|kar\s+dein)|de\s+(?:dein|den|do|dain)|dein|dain"
    r"|bata\s+(?:dein|den|dain|do|dijiye)|bata(?:in|yen|ein|o|yein|ye)|(?:share|send|transfer|reply|forward|enter|submit)\s+(?:karein|karen"
    r"|karain|kar\s+dein|kro|karo|krein))\b|"
    + _ur("بھیجیں", "بھیج دیں", "بھیجو", "بھیج دو", "بھجوائیں", "جمع کروائیں", "جمع کرائیں", "جمع کریں", "ادا کریں", "بتائیں", "بتا دیں",
          "بتاؤ", "شیئر کریں", "ارسال کریں", "فراہم کریں", "درج کریں", "دیں")
)  # fmt: skip
_FUTURE = re.compile("گ[ےی]")
_CONDITIONAL = re.compile(r"(?i)^\s*(?:if|agar|اگر)\b")
_FEE = re.compile(
    r"(?i)\b(?:fees?|charges?|processing|tax(?:es)?|kharcha|kharch|commission|advance|clearance)\b|"
    + _ur("فیس", "چارجز", "چارج", "ٹیکس", "خرچہ", "کمیشن", "ایڈوانس")
)
_PIN = re.compile(r"(?i)\b(?:pin|pin\s*code|password|passcode|mpin)\b|" + _ur("پن", "پاس ورڈ", "خفیہ نمبر"))
_OTP = re.compile(
    r"(?i)\b(?:otp|one[\s-]?time|verification\s+code|security\s+code|(?<!pin\s)code|kod)\b|"
    r"(?<![؀-ۿ])او ٹی پی(?![؀-ۿ])|(?<![؀-ۿ])(?<!پن\s)کوڈ(?![؀-ۿ])"
)
_CNIC = re.compile(r"(?i)\b(?:cnic|nic|id\s*card|identity\s*card|shanakhti|card\s*(?:number|no))\b|" + _ur("شناختی", "کارڈ نمبر"))
_MONEY = re.compile(
    r"(?i)\b(?:rs|rupees?|rupay|rupaye|rupey|pkr|paise|paisay|paisey|raqam|rakam|amount|money|cash)\b|" + _ur("روپے", "روپیہ", "رقم", "پیسے")
)
_RECEIVE = re.compile(
    r"(?i)\b(?:receive|claim|collect|withdraw|release|unlock|redeem|hasil|haasil|wusool|wasool|wusul|mosool|nikal(?:ne|wane|wa)?)\b|"
    r"\b(?:to|ke\s+liye)\s+get\b|" + _ur("حاصل", "وصول", "نکلوانے", "نکالنے", "جاری")
)
_NEGATION = re.compile(r"(?i)\b(?:never|not|don't|dont|no\s+one|nobody|kabhi|nahi|nahin|nhi|na|mat)\b|" + _ur("کبھی", "نہیں", "نہ", "مت"))
_PRIZE = re.compile(
    r"(?i)\b(?:you\s+(?:have\s+)?won|winner|lucky\s*draw|prize|jackpot|lottery|inaam|inam|jeet(?:a|i|e|\s+li|\s+liya)?|qurra|bumper)\b|"
    + _ur("انعام", "قرعہ", "لکی ڈرا", "جیت")
)
_CONGRATS = re.compile(r"(?i)\b(?:congratulations|congrats|mubarak|mubarik)\b|" + _ur("مبارک", "مبارکباد"))
_URGENCY = re.compile(
    r"(?i)\b(?:within\s+\d+\s+(?:hours?|hrs?|minutes?)|24\s*(?:hours?|hrs?|ghante)|immediately|urgent(?:ly)?|last\s+chance|right\s+now|act\s+now"
    r"|will\s+be\s+(?:blocked|closed|cancelled|canceled|suspended|deleted|expired)|otherwise|foran|fauran|jaldi|warna|aaj\s+hi|today\s+only"
    r"|band\s+ho\s+ja|block\s+ho\s+ja|khatam\s+ho\s+ja|zabt)\b|" + _ur("فوراً", "فوری", "جلدی", "ورنہ", "آج ہی", "بند ہو جائے", "منسوخ")
)
_OFFICIAL = re.compile(
    r"(?i)\b(?:rahat|relief|govt|government|sarkar|sarkari|hukumat|imdad|imdadi|program|programme|department|office|officer|ministry|bank"
    r"|helpline|head\s+office|official|inspector|police|thana)\b|" + _ur("راحت", "حکومت", "حکومتی", "سرکار", "سرکاری", "امداد", "امدادی",
                                                                          "پروگرام", "محکمہ", "دفتر", "افسر", "بینک", "ہیلپ لائن", "پولیس")
)  # fmt: skip
_SAFETY = re.compile(
    r"(?i)\b(?:never|will\s+not|won't|do\s+not|don't|dont)\s+(?:ask|call|share|tell|give|send)\b|\bnever\s+share\b"
    r"|\bkabhi\s+(?:bhi\s+)?(?:nahi|nahin|nhi)\s+(?:mang|poochh|pooch)|\bkisi\s+(?:ko|se)\s+(?:bhi\s+)?(?:na|mat)\s+(?:bata|share)"
    r"|نہیں\s+مانگت|نہیں\s+مانگ|نہیں\s+پوچھت|کسی\s+کو\s+(?:بھی\s+)?نہ\s+بتا|شیئر\s+نہ\s+کریں"
)
_CONTACT = re.compile(r"(?i)\b(?:call|contact|whatsapp|sms|ring|rabta|raabta|phone)\b|" + _ur("رابطہ", "کال", "فون", "واٹس ایپ"))
PHONE_IN_TEXT = re.compile(r"(?<!\d)(?:(?:\+|00)92[\s-]?\d{3}|0\d{3})[\s.-]?\d{7}(?!\d)")
EMAIL_IN_TEXT = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}\b")
# A dot or comma between digits ("Rs 2,500", "1.5") does not end a clause; "Rs." is not a full stop.
_CLAUSES = re.compile(r"(?:(?<!\d)[.,]|[.,](?!\d)|[!?۔؟\n;،])+")
_SENTENCES = re.compile(r"(?:(?<!\d)\.|\.(?!\d)|[!?۔؟\n])+")
_ABBREVIATION = re.compile(r"(?i)\b(rs|no|mr|dr|st)\.\s*")


def _requests(clause: str) -> bool:
    """A request verb in the clause, not negated ("never share your PIN" is advice) and not future tense."""
    if _NEGATION.search(clause) and not _CONDITIONAL.match(clause):
        return False  # "if you do not pay the fee ..." is a threat, so a conditional keeps its ask
    for match in _ASK.finditer(clause):
        if _FUTURE.search(clause[match.end(): match.end() + 4]):
            continue  # "بھیجیں گے" is "we will send", not a request
        return True
    return False


_ASK_OBJECTS = (("asks_fee", _FEE), ("asks_pin", _PIN), ("asks_otp", _OTP), ("asks_cnic", _CNIC), ("asks_money", _MONEY))
# A fee demanded without a request verb: "a customs fee of Rs 2,000 must be paid before delivery".
_FEE_DUE = re.compile(
    r"(?i)\b(?:fees?|charges?|tax(?:es)?|commission|clearance)\b[^.!?\n]{0,40}?\b(?:must\s+be\s+paid|to\s+be\s+paid|has\s+to\s+be\s+paid"
    r"|needs?\s+to\s+be\s+paid|is\s+required|are\s+required|payable)\b"
    r"|\b(?:fees?|charges|tax)\s+(?:ada|jama)\s+(?:karni|karna|karne|karwani)\s+(?:hogi|hoga|hongi|hai|hain|paregi|padegi)"
    r"|(?<![؀-ۿ])(?:فیس|ٹیکس|چارجز)(?![؀-ۿ])[^۔\n]{0,30}(?:ادا|جمع)\s+کر(?:نی|نا|وانی)\s+(?:ہو|ہوگی|ہوگا|پڑے)"
)


def cues(text: str) -> dict[str, bool]:
    """What the message asks for, and other cues. A request and its object must share a clause."""
    lowered = _ABBREVIATION.sub(r"\1 ", text.lower())
    found = dict.fromkeys(("asks_fee", "asks_pin", "asks_otp", "asks_cnic", "asks_money", "pay_to_receive"), False)
    for sentence in _SENTENCES.split(lowered):
        if not sentence.strip():
            continue
        receive = _RECEIVE.search(sentence) is not None
        for clause in _CLAUSES.split(sentence):
            if not clause.strip() or not _requests(clause):
                continue
            hits = {name: pattern.search(clause) is not None for name, pattern in _ASK_OBJECTS}
            for name, hit in hits.items():
                found[name] = found[name] or hit
            if receive and (hits["asks_fee"] or hits["asks_money"]):
                found["pay_to_receive"] = True
    if not found["asks_fee"]:
        found["asks_fee"] = any(_FEE_DUE.search(c) and not _NEGATION.search(c) for c in _CLAUSES.split(lowered))
    return {
        **found,
        "prize": _PRIZE.search(lowered) is not None,
        "congrats": _CONGRATS.search(lowered) is not None,
        "urgency": _URGENCY.search(lowered) is not None,
        "claims_official": _OFFICIAL.search(lowered) is not None,
        "safety_notice": _SAFETY.search(lowered) is not None,
        "phone_in_text": PHONE_IN_TEXT.search(text) is not None,
        "contact_request": PHONE_IN_TEXT.search(text) is not None and _CONTACT.search(lowered) is not None,
    }


# --- verify codes and our own templates ----------------------------------------------------------------

_CODE_WORD = re.compile(r"(?i)(?:\bcode|\bkod|\bkode|(?<![؀-ۿ])کوڈ)\s*[:#.-]?\s*([A-Za-z0-9]{3}[\s-]?[A-Za-z0-9]{3})(?![A-Za-z0-9])")
_BARE_CODE = re.compile(r"(?i)^\s*(?:(?:verify\s+)?code\s*[:#-]?\s*|کوڈ\s*)?([A-Za-z0-9]{3}[\s-]?[A-Za-z0-9]{3})\s*$")
_FORWARD_PREFIX = re.compile(r"(?i)^(?:(?:fwd|fw|forwarded(?:\s+message)?)\s*:?\s*)+")


def looks_like_our_code(code: str) -> bool:
    """Our codes use an alphabet without 0, 1, I, L and O, and almost always contain a letter (bank OTPs are digits)."""
    value = templates.normalise_code(code)
    return len(value) == templates.CODE_LENGTH and all(c in templates.CODE_ALPHABET for c in value) and any(c.isalpha() for c in value)


def code_candidates(text: str) -> tuple[list[str], bool]:
    """Codes written after 'Code'/'کوڈ', or a message that is only a code. Returns (codes, the whole text is a code)."""
    bare = _BARE_CODE.match(text)
    if bare:
        return [templates.normalise_code(bare.group(1))], True
    found: list[str] = []
    for match in _CODE_WORD.finditer(text):
        value = templates.normalise_code(match.group(1))
        if value not in found:
            found.append(value)
    return found[:3], False


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


@lru_cache(maxsize=1)
def _template_patterns() -> tuple[tuple[str, str, re.Pattern[str]], ...]:
    slot = {"tracking_code": "[A-Za-z0-9-]{0,32}", "amount": "[0-9,]{0,20}", "rail_ref": "[A-Za-z0-9-]{0,32}",
            "code": "[0-9]{0,8}"}  # the one-time sign-up code in registration messages
    patterns = []
    for name, by_lang in templates.TEMPLATES.items():
        for lang, template in by_lang.items():
            body = ""
            for literal, field_name, _, _ in string.Formatter().parse(template):
                body += re.escape(_squash(normalise(literal)))
                if field_name == "proof":
                    body += "(?:" + "|".join(re.escape(_squash(normalise(p[lang]))) for p in templates.PROOF_NAMES.values()) + ")"
                elif field_name:
                    body += slot[field_name]
            word = re.escape(_squash(normalise(templates.CODE_SUFFIX[lang].split("{")[0])))
            patterns.append((name, lang, re.compile("^" + body + "(?:" + word + "([A-Za-z0-9]{6}))?$")))
    return tuple(patterns)


@dataclass(frozen=True)
class TemplateMatch:
    template: str
    lang: str
    code: str | None


def match_template(text: str, only: str | None = None) -> TemplateMatch | None:
    """Does the text read exactly like one of our messages (spacing and a 'Fwd:' prefix aside)?"""
    squashed = _squash(_FORWARD_PREFIX.sub("", normalise(text).strip().strip("\"'")))
    for name, lang, pattern in _template_patterns():
        if only and name != only:
            continue
        match = pattern.match(squashed)
        if match:
            return TemplateMatch(name, lang, match.group(1))
    return None


# --- everything together --------------------------------------------------------------------------------

SIGNAL_NAMES: tuple[str, ...] = (
    "url_any", "url_lookalike", "url_shortener", "url_ip", "url_punycode", "url_http", "url_odd_tld", "url_apk", "url_messaging",
    "url_phishy_words", "asks_fee", "asks_pin", "asks_otp", "asks_cnic", "asks_money", "pay_to_receive", "prize", "congrats",
    "urgency", "phone_in_text", "contact_request", "claims_official", "safety_notice", "template_match", "sender_official",
    "sender_lookalike", "sender_mobile", "sender_mobile_official", "sender_alpha_other",
)  # fmt: skip
SCAM_SIDE_SIGNALS = frozenset(
    {"url_lookalike", "url_ip", "url_punycode", "url_apk", "asks_fee", "asks_pin", "asks_otp", "asks_cnic", "pay_to_receive", "sender_lookalike",
     "sender_mobile_official"}
)  # fmt: skip


@dataclass(frozen=True)
class Signals:
    text: str  # normalised, cut to MAX_TEXT_CHARS
    script: str
    word_count: int
    urls: tuple[UrlFinding, ...]
    sender: SenderInfo
    cue: dict[str, bool]
    codes: tuple[str, ...]
    bare_code: bool
    template: TemplateMatch | None
    values: dict[str, float] = field(default_factory=dict)

    def vector(self) -> list[float]:
        return [self.values.get(name, 0.0) for name in SIGNAL_NAMES]

    def fired(self) -> list[str]:
        return [name for name in SIGNAL_NAMES if self.values.get(name)]


def analyse(text: str, sender: str | None = None, *, official_sender: str = DEFAULT_OFFICIAL_SENDER,
            official_domains: frozenset[str] = frozenset()) -> Signals:  # fmt: skip
    clean = normalise(text)[:MAX_TEXT_CHARS]
    official_name = _squash_name(official_sender or DEFAULT_OFFICIAL_SENDER).lower()
    names = (official_name,) if official_name and official_name != "rahat" else ()
    urls = tuple(f for f in (analyse_url(u, official_domains=official_domains, official_names=names) for u in find_urls(clean)) if f)
    who = analyse_sender(sender, official_sender)
    cue = cues(clean)
    codes, bare = code_candidates(clean)
    template = match_template(clean)
    url_flags = {flag for finding in urls for flag in finding.flags}
    values: dict[str, float] = {
        "url_any": float(bool(urls)),
        "url_lookalike": float(bool({"lookalike_official", "official_name_in_subdomain"} & url_flags)),
        "url_shortener": float("shortener" in url_flags),
        "url_ip": float("ip_host" in url_flags),
        "url_punycode": float(bool({"punycode", "at_sign"} & url_flags)),
        "url_http": float("http" in url_flags),
        "url_odd_tld": float("odd_tld" in url_flags),
        "url_apk": float("apk_download" in url_flags),
        "url_messaging": float("messaging_link" in url_flags),
        "url_phishy_words": float(bool({"phishy_words", "many_hyphens"} & url_flags)),
        **{name: float(cue[name]) for name in ("asks_fee", "asks_pin", "asks_otp", "asks_cnic", "asks_money", "pay_to_receive", "prize",
                                                "congrats", "urgency", "phone_in_text", "contact_request", "claims_official", "safety_notice")},
        "template_match": float(template is not None),
        "sender_official": float(who.kind == "official"),
        "sender_lookalike": float(who.kind == "lookalike"),
        "sender_mobile": float(who.kind in ("mobile", "number")),
        "sender_mobile_official": float(who.kind in ("mobile", "number") and cue["claims_official"]),
        "sender_alpha_other": float(who.kind == "alpha"),
    }  # fmt: skip
    words = meaningful_words(PHONE_IN_TEXT.sub(" ", URL_PATTERN.sub(" ", clean)))
    return Signals(text=clean, script=script_of(clean), word_count=words, urls=urls, sender=who, cue=cue, codes=tuple(codes),
                   bare_code=bare, template=template, values=values)  # fmt: skip
