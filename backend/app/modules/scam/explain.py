"""What a citizen reads and hears: short sentences keyed by reason code, in English and Urdu.

About grade 5, one sentence per reason, at most three reasons. Each sentence has an audio key
(`scam.reason.<code>`) so the audio script can record it. No scores reach a citizen.
"""

from __future__ import annotations

from typing import Any

LANGS = ("ur", "en")

REASONS: dict[str, dict[str, str]] = {
    "verify_code_confirmed": {"en": "This code matches a message we sent.", "ur": "یہ کوڈ ہمارے بھیجے ہوئے پیغام سے ملتا ہے۔"},
    "compare_with_app": {"en": "Check that the words match the message in your Rahat app.",
                         "ur": "دیکھ لیں کہ الفاظ راحت ایپ والے پیغام جیسے ہی ہوں۔"},
    "verify_code_not_found": {"en": "The code in it does not match any message we sent.", "ur": "اس کا کوڈ ہمارے کسی پیغام سے نہیں ملتا۔"},
    "code_typo_possible": {"en": "If you typed the code yourself, check it again.", "ur": "اگر کوڈ آپ نے خود لکھا ہے تو دوبارہ دیکھ لیں۔"},
    "code_real_text_changed": {"en": "The code is from a real message, but the words were changed.",
                               "ur": "کوڈ اصلی پیغام کا ہے، مگر الفاظ بدل دیے گئے ہیں۔"},
    "code_real_text_differs": {"en": "The code is real, but the words are not the same as our message.",
                               "ur": "کوڈ اصلی ہے، مگر الفاظ ہمارے پیغام جیسے نہیں۔"},
    "asks_fee": {"en": "It asks you to pay a fee, and Rahat never asks for a fee.", "ur": "اس میں فیس مانگی گئی ہے، اور راحت کبھی فیس نہیں مانگتا۔"},
    "asks_pin": {"en": "It asks for your PIN or password.", "ur": "اس میں آپ کا پن یا پاس ورڈ مانگا گیا ہے۔"},
    "asks_otp": {"en": "It asks for a secret code sent to your phone.", "ur": "اس میں فون پر آنے والا خفیہ کوڈ مانگا گیا ہے۔"},
    "asks_cnic": {"en": "It asks for your ID card number by message.", "ur": "اس میں پیغام کے ذریعے شناختی کارڈ نمبر مانگا گیا ہے۔"},
    "asks_money": {"en": "It asks you to send money.", "ur": "اس میں پیسے بھیجنے کا کہا گیا ہے۔"},
    "pay_to_receive": {"en": "It says you must pay first to get money.", "ur": "اس میں کہا گیا ہے کہ رقم لینے سے پہلے پیسے دیں۔"},
    "prize": {"en": "It says you won a prize you did not enter for.", "ur": "اس میں ایسے انعام کی بات ہے جس کے لیے آپ نے حصہ نہیں لیا۔"},
    "urgency": {"en": "It rushes you to act fast.", "ur": "یہ آپ کو جلدی کرنے پر مجبور کرتا ہے۔"},
    "link_lookalike": {"en": "The link looks like an official site, but it is not.", "ur": "لنک سرکاری لگتا ہے مگر سرکاری نہیں۔"},
    "link_hidden": {"en": "The link hides where it really goes.", "ur": "لنک اپنا اصل پتہ چھپاتا ہے۔"},
    "link_ip": {"en": "The link uses numbers instead of a website name.", "ur": "لنک میں ویب سائٹ کے نام کی جگہ نمبر ہیں۔"},
    "link_lookalike_letters": {"en": "The link uses letters that only look normal.", "ur": "لنک میں ملتے جلتے حروف استعمال ہوئے ہیں۔"},
    "link_not_secure": {"en": "The link is not secure.", "ur": "یہ لنک محفوظ نہیں۔"},
    "link_odd_ending": {"en": "The link has an unusual ending for an official site.", "ur": "لنک کا آخری حصہ سرکاری ویب سائٹ جیسا نہیں۔"},
    "link_app_file": {"en": "The link downloads an app file.", "ur": "یہ لنک ایپ کی فائل ڈاؤن لوڈ کرتا ہے۔"},
    "link_chat": {"en": "The link opens a chat with a stranger.", "ur": "یہ لنک کسی اجنبی سے چیٹ کھولتا ہے۔"},
    "link_phishy": {"en": "The link asks you to log in or claim something.", "ur": "لنک لاگ ان کرنے یا کچھ وصول کرنے کا کہتا ہے۔"},
    "has_link": {"en": "It asks you to open a link.", "ur": "اس میں لنک کھولنے کا کہا گیا ہے۔"},
    "sender_lookalike": {"en": "The sender name looks official, but it is not ours.", "ur": "بھیجنے والے کا نام سرکاری لگتا ہے مگر ہمارا نہیں۔"},
    "sender_mobile_official": {"en": "It says it is official, but it came from a personal mobile number.",
                               "ur": "یہ سرکاری ہونے کا دعویٰ کرتا ہے مگر ذاتی موبائل نمبر سے آیا ہے۔"},
    "contact_number": {"en": "It asks you to call or message a phone number.", "ur": "اس میں کسی نمبر پر کال یا پیغام کرنے کا کہا گیا ہے۔"},
    "reads_like_scam": {"en": "It reads like scam messages we know.", "ur": "یہ ان دھوکے والے پیغامات جیسا ہے جو ہم جانتے ہیں۔"},
    "too_short": {"en": "The message is too short to tell.", "ur": "پیغام بہت چھوٹا ہے، اس سے پتہ نہیں چلتا۔"},
    "mixed_signals": {"en": "Some parts look real and some look like a scam.", "ur": "اس کے کچھ حصے اصلی اور کچھ دھوکے جیسے لگتے ہیں۔"},
    "model_unsure": {"en": "We could not tell if it is real.", "ur": "ہم یہ نہیں جان سکے کہ یہ اصلی ہے یا نہیں۔"},
    "no_scam_signs": {"en": "We found no signs of a scam.", "ur": "ہمیں اس میں دھوکے کی کوئی نشانی نہیں ملی۔"},
    "matches_template": {"en": "The words match a real Rahat message.", "ur": "الفاظ راحت کے اصلی پیغام سے ملتے ہیں۔"},
    "official_sender": {"en": "It came from our official sender name.", "ur": "یہ ہمارے سرکاری نام سے آیا ہے۔"},
    "no_code_to_check": {"en": "Real Rahat messages end with a code, and this one has none to check.",
                         "ur": "راحت کے اصلی پیغام کے آخر میں کوڈ ہوتا ہے، اس میں چیک کرنے کو کوڈ نہیں۔"},
    "rahat_without_code": {"en": "It says it is from Rahat, but it has no code to check.",
                           "ur": "یہ راحت کے نام سے ہے مگر اس میں چیک کرنے کو کوڈ نہیں۔"},
}  # fmt: skip

HEADLINES: dict[str, dict[str, str]] = {
    "likely_scam": {"en": "This message is most likely a scam.", "ur": "یہ پیغام غالباً دھوکا ہے۔"},
    "might_be_scam": {"en": "This message might be a scam.", "ur": "یہ پیغام دھوکا ہو سکتا ہے۔"},
    "not_sure": {"en": "We are not sure about this message.", "ur": "ہمیں اس پیغام کا یقین نہیں۔"},
    "looks_real": {"en": "This message looks real.", "ur": "یہ پیغام اصلی لگتا ہے۔"},
    "confirmed_real": {"en": "This is a real message from Rahat.", "ur": "یہ راحت کا اصلی پیغام ہے۔"},
}

WHAT_TO_DO: dict[str, dict[str, str]] = {
    "likely_scam": {"en": "Do not reply, call, pay or share your PIN, and delete the message.",
                    "ur": "جواب نہ دیں، کال نہ کریں، پیسے یا پن نہ دیں، اور پیغام مٹا دیں۔"},
    "might_be_scam": {"en": "Do not pay or share your PIN, and ask a person to check it.", "ur": "پیسے یا پن نہ دیں، اور کسی افسر سے چیک کروائیں۔"},
    "not_sure": {"en": "Do not act on it yet; tap Ask a person and an officer will check it.",
                 "ur": "ابھی اس پر عمل نہ کریں؛ افسر سے پوچھیں دبائیں، افسر اسے دیکھے گا۔"},
    "looks_real": {"en": "Still, never pay a fee or share your PIN.", "ur": "پھر بھی کبھی فیس نہ دیں اور پن کسی کو نہ بتائیں۔"},
    "confirmed_real": {"en": "You can follow it in the Rahat app.", "ur": "آپ راحت ایپ میں اس پر عمل کر سکتے ہیں۔"},
}  # fmt: skip

LABEL_NAMES: dict[str, dict[str, str]] = {
    "relief_scam": {"en": "Fake relief payment message", "ur": "جعلی امدادی رقم کا پیغام"},
    "phishing_link": {"en": "Fake link message", "ur": "جعلی لنک والا پیغام"},
    "advance_fee": {"en": "Pay-first prize, job or loan trick", "ur": "پہلے پیسے مانگنے والا انعام، نوکری یا قرض کا دھوکا"},
    "impersonation": {"en": "Someone pretending to be official or family", "ur": "سرکاری یا گھر والا بن کر دھوکا"},
    "legit_program_message": {"en": "Rahat message", "ur": "راحت کا پیغام"},
    "unknown": {"en": "Ordinary message", "ur": "عام پیغام"},
    "not_sure": {"en": "Not sure", "ur": "یقین نہیں"},
}

URL_FLAGS: dict[str, dict[str, str]] = {
    "lookalike_official": {"en": "pretends to be an official site", "ur": "سرکاری ویب سائٹ کی نقل"},
    "official_name_in_subdomain": {"en": "hides a fake site behind an official name", "ur": "سرکاری نام کے پیچھے جعلی ویب سائٹ"},
    "shortener": {"en": "hides the real address", "ur": "اصل پتہ چھپاتا ہے"},
    "ip_host": {"en": "numbers instead of a name", "ur": "نام کی جگہ نمبر"},
    "punycode": {"en": "look-alike letters", "ur": "ملتے جلتے حروف"},
    "at_sign": {"en": "hides the real address", "ur": "اصل پتہ چھپاتا ہے"},
    "http": {"en": "not secure", "ur": "محفوظ نہیں"},
    "odd_tld": {"en": "unusual ending", "ur": "غیر معمولی آخری حصہ"},
    "apk_download": {"en": "downloads an app file", "ur": "ایپ فائل ڈاؤن لوڈ کرتا ہے"},
    "messaging_link": {"en": "opens a chat with a stranger", "ur": "اجنبی سے چیٹ کھولتا ہے"},
    "phishy_words": {"en": "asks you to log in or claim", "ur": "لاگ ان یا وصولی کا لالچ"},
    "many_hyphens": {"en": "an odd address", "ur": "عجیب پتہ"},
}

# Which citizen reason a fired signal becomes. Signals without an entry are never shown on their own.
SIGNAL_REASON: dict[str, str] = {
    "asks_fee": "asks_fee", "asks_pin": "asks_pin", "asks_otp": "asks_otp", "asks_cnic": "asks_cnic", "asks_money": "asks_money",
    "pay_to_receive": "pay_to_receive", "prize": "prize", "urgency": "urgency", "url_lookalike": "link_lookalike",
    "url_shortener": "link_hidden", "url_ip": "link_ip", "url_punycode": "link_lookalike_letters", "url_http": "link_not_secure",
    "url_odd_tld": "link_odd_ending", "url_apk": "link_app_file", "url_messaging": "link_chat", "url_phishy_words": "link_phishy",
    "url_any": "has_link", "sender_lookalike": "sender_lookalike", "sender_mobile_official": "sender_mobile_official",
    "contact_request": "contact_number",
}  # fmt: skip

MAX_REASONS = 3


def lang_from_header(accept_language: str | None) -> str:
    """'ur' or 'en' from Accept-Language (quality values respected); Sindhi and anything else fall back to Urdu."""
    best, best_q = "ur", -1.0
    for part in (accept_language or "").split(","):
        tag, _, params = part.strip().partition(";")
        base = tag.strip().lower().split("-")[0]
        try:
            q = float(params.split("=", 1)[1]) if "q=" in params else 1.0
        except ValueError:
            q = 0.0
        if base in LANGS and q > best_q:
            best, best_q = base, q
    return best


def citizen_text(certainty: str, label: str | None, reason_codes: list[str], lang: str) -> dict[str, Any]:
    lang = lang if lang in LANGS else "ur"
    shown = [code for code in reason_codes if code in REASONS][:MAX_REASONS]
    return {
        "headline": HEADLINES[certainty][lang],
        "label_text": LABEL_NAMES[label or "not_sure"][lang],
        "reasons": [{"code": code, "text": REASONS[code][lang]} for code in shown],
        "what_to_do": WHAT_TO_DO[certainty][lang],
        "audio_keys": [f"scam.certainty.{certainty}", *(f"scam.reason.{code}" for code in shown), f"scam.todo.{certainty}"],
    }


def url_flag_texts(flags: list[str] | tuple[str, ...], lang: str) -> list[str]:
    lang = lang if lang in LANGS else "ur"
    out: list[str] = []
    for flag in flags:
        text = URL_FLAGS.get(flag, {}).get(lang)
        if text and text not in out:
            out.append(text)
    return out


def audio_manifest() -> dict[str, dict[str, str]]:
    """Every fixed sentence of the scam checker, keyed by audio key, for the audio generation script."""
    out: dict[str, dict[str, str]] = {}
    for code, texts in REASONS.items():
        out[f"scam.reason.{code}"] = texts
    for certainty, texts in HEADLINES.items():
        out[f"scam.certainty.{certainty}"] = texts
    for certainty, texts in WHAT_TO_DO.items():
        out[f"scam.todo.{certainty}"] = texts
    return out
