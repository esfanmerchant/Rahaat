"""Message templates in English and Urdu, and the verify code. Pure functions.

Urdu copy is plain (about grade 5) and at most three short sentences. Every official message ends with a
short verify code that anyone can check in the scam checker, and says that Rahat never asks for a fee or
a PIN, which is how relief scams usually start.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from typing import Any

TEMPLATES: dict[str, dict[str, str]] = {
    "application_received": {
        "en": "Rahat: we got your application {tracking_code}. We never ask for a fee or your PIN.",
        "ur": "راحت: آپ کی درخواست {tracking_code} مل گئی ہے۔ ہم کبھی فیس یا پن نہیں مانگتے۔",
    },
    "person_will_check": {
        "en": "Rahat: a person will check your application {tracking_code}. You do not need to do anything now. We will send you a message.",
        "ur": "راحت: ایک افسر آپ کی درخواست {tracking_code} دیکھے گا۔ آپ کو ابھی کچھ نہیں کرنا۔ ہم آپ کو پیغام بھیجیں گے۔",
    },
    "proof_needed": {
        "en": "Rahat: please send one more paper: {proof}. Open the Rahat app or ask your helper.",
        "ur": "راحت: ایک اور کاغذ بھیجیں: {proof}۔ راحت ایپ کھولیں یا اپنے مددگار سے کہیں۔",
    },
    "approved": {
        "en": "Rahat: your application is approved. You will get Rs {amount}. We never ask for a fee.",
        "ur": "راحت: آپ کی درخواست منظور ہو گئی ہے۔ آپ کو {amount} روپے ملیں گے۔ ہم کبھی فیس نہیں مانگتے۔",
    },
    "rejected": {
        "en": "Rahat: we could not approve your application {tracking_code}. You can ask a person to look again in the Rahat app or at an office.",
        "ur": "راحت: ہم آپ کی درخواست {tracking_code} منظور نہیں کر سکے۔ آپ راحت ایپ یا راحت دفتر میں کسی افسر سے دوبارہ دیکھنے کا کہہ سکتے ہیں۔",
    },
    "payment_sent": {
        "en": "Rahat: Rs {amount} has been sent to you. Reference {rail_ref}. We never ask for a fee or your PIN.",
        "ur": "راحت: {amount} روپے آپ کو بھیج دیے گئے ہیں۔ حوالہ {rail_ref}۔ ہم کبھی فیس یا پن نہیں مانگتے۔",
    },
    # Sign-up messages (sent at once to the number the person typed; see service.notify).
    "registration_code": {
        "en": "Rahat: your sign-up code is {code}. It works for 10 minutes. Never share it; we never ask for a fee or your PIN.",
        "ur": "راحت: آپ کا رجسٹریشن کوڈ {code} ہے۔ یہ 10 منٹ چلے گا۔ یہ کسی کو نہ بتائیں، ہم کبھی فیس یا پن نہیں مانگتے۔",
    },
    "registration_exists": {
        "en": "Rahat: this number already has an account, so sign in instead. If you did not ask for this, ignore it. "
              "We never ask for a fee or your PIN.",
        "ur": "راحت: اس نمبر پر پہلے سے اکاؤنٹ ہے، سائن ان کریں۔ اگر آپ نے نہیں مانگا تو یہ پیغام چھوڑ دیں۔ ہم کبھی فیس یا پن نہیں مانگتے۔",
    },
    "payment_delayed": {
        "en": "Rahat: your payment is approved but sending it is taking longer. We will try again. You do not need to do anything.",
        "ur": "راحت: آپ کی رقم منظور ہے مگر بھیجنے میں دیر ہو رہی ہے۔ ہم دوبارہ کوشش کریں گے۔ آپ کو کچھ نہیں کرنا۔",
    },
}

# Messages added after the scam corpus was frozen (A18). They are kept apart from TEMPLATES so that the committed corpus
# and the scam model trained on it stay reproducible; `render` knows both. TODO (Track C): add them to the scam checker's
# template patterns (scam/signals.py) and the corpus generator in the same change, then merge this dict into TEMPLATES.
EXTRA_TEMPLATES: dict[str, dict[str, str]] = {
    "appeal_received": {
        "en": "Rahat: we got your appeal for application {tracking_code}. A different officer will look at it again. We will send you a message.",
        "ur": "راحت: آپ کی درخواست {tracking_code} کی اپیل مل گئی ہے۔ کوئی دوسرا افسر اسے دوبارہ دیکھے گا۔ ہم آپ کو پیغام بھیجیں گے۔",
    },
    "appeal_upheld": {
        "en": "Rahat: a different officer looked again at application {tracking_code}. The first answer stays. You can ask at a Rahat office why.",
        "ur": "راحت: دوسرے افسر نے درخواست {tracking_code} دوبارہ دیکھی۔ پہلا فیصلہ قائم ہے۔ وجہ پوچھنے کے لیے راحت دفتر جا سکتے ہیں۔",
    },
    "appeal_overturned": {
        "en": "Rahat: good news. A different officer looked again and application {tracking_code} is now approved. You will get Rs {amount}.",
        "ur": "راحت: خوش خبری۔ دوسرے افسر نے دوبارہ دیکھا اور درخواست {tracking_code} اب منظور ہے۔ آپ کو {amount} روپے ملیں گے۔",
    },
    "complaint_received": {
        "en": "Rahat: we got your complaint. A person will read it. You do not need to do anything now.",
        "ur": "راحت: آپ کی شکایت مل گئی ہے۔ ایک افسر اسے پڑھے گا۔ آپ کو ابھی کچھ نہیں کرنا۔",
    },
    "complaint_resolved": {
        "en": "Rahat: we looked into your complaint and took action. Thank you for telling us.",
        "ur": "راحت: ہم نے آپ کی شکایت دیکھ کر کارروائی کی ہے۔ بتانے کا شکریہ۔",
    },
    "complaint_closed": {
        "en": "Rahat: we looked into your complaint and could not change anything. You can speak to a person at a Rahat office.",
        "ur": "راحت: ہم نے آپ کی شکایت دیکھی مگر کچھ بدل نہیں سکے۔ آپ راحت دفتر میں کسی افسر سے بات کر سکتے ہیں۔",
    },
}

PROOF_NAMES: dict[str, dict[str, str]] = {
    "rahat_id": {"en": "a clear photo of your Rahat card", "ur": "راحت کارڈ کی صاف تصویر"},
    "income_proof": {"en": "a paper that shows your monthly income", "ur": "ماہانہ آمدنی کا کاغذ"},
    "other": {"en": "the paper the officer asked for", "ur": "وہ کاغذ جو افسر نے مانگا ہے"},
}

# Messages the person asked for at sign-up: sent at once, carry their own code, no verify code appended.
ONE_TIME_TEMPLATES = frozenset({"registration_code", "registration_exists"})

LANGS = ("ur", "en")
CODE_SUFFIX = {"en": " Code {code}", "ur": " کوڈ {code}"}
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O, 1/I/L: easy to read out on the phone
CODE_LENGTH = 6

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9-]")
_SPACE_BEFORE_STOP = re.compile(r"\s+([.۔])")
_SPACES = re.compile(r"\s{2,}")
_SENTENCE_END = re.compile(r"[.۔?!؟]")


def choose_lang(requested: str | None, person_lang: str | None) -> str:
    for candidate in (requested, person_lang):
        if candidate in LANGS:
            return str(candidate)
    return "ur"  # Sindhi and anything unknown fall back to Urdu (DECISIONS 16)


def _token(value: Any) -> str:
    return _SAFE_TOKEN.sub("", str(value or ""))[:32]


def _amount(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return ""


def render(template: str, lang: str, payload: dict[str, Any]) -> str:
    """The message text for a template, without the verify code. Only known, sanitised values are filled in."""
    if template not in TEMPLATES and template not in EXTRA_TEMPLATES:
        raise ValueError(f"unknown notification template {template!r}")
    lang = choose_lang(lang, None)
    proof_kind = str(payload.get("proof_kind") or "other")
    values = {
        "tracking_code": _token(payload.get("tracking_code")),
        "amount": _amount(payload.get("amount_pkr")),
        "rail_ref": _token(payload.get("rail_ref")),
        "proof": PROOF_NAMES.get(proof_kind, PROOF_NAMES["other"])[lang],
        "code": re.sub(r"\D", "", str(payload.get("code") or ""))[:8],
    }
    text = (TEMPLATES.get(template) or EXTRA_TEMPLATES[template])[lang].format(**values)
    return _SPACES.sub(" ", _SPACE_BEFORE_STOP.sub(r"\1", text)).strip()


def sentence_count(text: str) -> int:
    return len(_SENTENCE_END.findall(text))


def verify_code(notification_id: uuid.UUID, body_hash: str, key: bytes) -> str:
    """A short code: a truncated HMAC over the notification id and the hash of its text."""
    digest = hmac.new(key, f"{notification_id}:{body_hash}".encode(), hashlib.sha256).digest()
    number = int.from_bytes(digest[:8], "big")
    chars = []
    for _ in range(CODE_LENGTH):
        number, index = divmod(number, len(CODE_ALPHABET))
        chars.append(CODE_ALPHABET[index])
    return "".join(chars)


def with_code(text: str, code: str, lang: str) -> str:
    return text + CODE_SUFFIX[choose_lang(lang, None)].format(code=code)


def text_without_code(body: str, code: str, lang: str) -> str | None:
    suffix = CODE_SUFFIX[choose_lang(lang, None)].format(code=code)
    return body[: -len(suffix)] if body.endswith(suffix) else None


def body_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalise_code(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", code).upper()[:CODE_LENGTH + 2]
