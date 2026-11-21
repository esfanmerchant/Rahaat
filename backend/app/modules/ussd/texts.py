"""Words for the feature-phone channel: USSD screens and SMS replies, keyed, in English and Roman Urdu.

Feature phones rarely draw Urdu script, so the regional option here is Roman Urdu (Urdu in Latin letters), not Urdu
script. Every USSD screen must fit the 182-character limit and every SMS reply one 160-character message with its
verify code; both limits are tests. Sentences are short (about grade 5) and there are at most three of them.
Nothing here is written by a model: citizens hear only these keyed texts.
"""

from __future__ import annotations

from typing import Final

LANGS: Final = ("en", "ru")
USSD_LIMIT: Final = 182
SMS_LIMIT: Final = 160

# Roman Urdu names for the tracking-code pictograms (contracts.common.TRACKING_SYMBOLS).
SYMBOL_NAMES: Final[dict[str, dict[str, str]]] = {
    "moon": {"en": "moon", "ru": "chand"}, "star": {"en": "star", "ru": "sitara"}, "fish": {"en": "fish", "ru": "machli"},
    "tree": {"en": "tree", "ru": "darakht"}, "house": {"en": "house", "ru": "ghar"}, "sun": {"en": "sun", "ru": "suraj"},
    "bird": {"en": "bird", "ru": "parinda"}, "flower": {"en": "flower", "ru": "phool"}, "key": {"en": "key", "ru": "chaabi"},
    "boat": {"en": "boat", "ru": "kashti"}, "lamp": {"en": "lamp", "ru": "chiragh"}, "leaf": {"en": "leaf", "ru": "patta"},
    "cup": {"en": "cup", "ru": "pyala"}, "drum": {"en": "drum", "ru": "dhol"}, "kite": {"en": "kite", "ru": "patang"},
    "bell": {"en": "bell", "ru": "ghanti"},
}  # fmt: skip

# What each application status means, in one short line. Nothing personal: no name, amount or reason.
STATUS_LINES: Final[dict[str, dict[str, str]]] = {
    "draft": {"en": "Not sent yet. Finish it in the Rahat app.", "ru": "Abhi bheji nahin. Rahat app mein poori karein."},
    "submitted": {"en": "We got it. A decision is coming.", "ru": "Mil gayi. Faisla aane wala hai."},
    "needs_proof": {
        "en": "We need one more paper. Open the app or ask your helper.", "ru": "Aik aur kaghaz chahiye. App kholein ya madadgar se kahein.",
    },
    "in_review": {"en": "A person is checking it. You need not do anything.", "ru": "Aik afsar dekh raha hai. Aap ko kuch nahin karna."},
    "approved": {"en": "Approved. We will message you when money is sent.", "ru": "Manzoor ho gayi. Paisay bhejne par paigham aayega."},
    "paid": {"en": "Approved and paid. Check your wallet.", "ru": "Manzoor aur paisay bhej diye. Apna wallet dekhein."},
    "rejected": {"en": "Not approved. You can ask a person to look again.", "ru": "Manzoor nahin hui. Aap afsar se dobara dekhne ko keh sakte hain."},
    "on_hold_consent": {"en": "On hold. You stopped sharing your data.", "ru": "Ruki hui hai. Aap ne data share karna roka hai."},
    "withdrawn": {"en": "You took this application back.", "ru": "Aap ne yeh darkhwast wapas le li."},
}  # fmt: skip
STATUS_FALLBACK: Final = {"en": "Not clear. A person can help.", "ru": "Wazeh nahin. Aik afsar madad karega."}

# USSD screens. `{...}` values are filled by `screen`.
SCREENS: Final[dict[str, dict[str, str]]] = {
    "lang": {"en": "Rahat (prototype)\n1 English\n2 Roman Urdu", "ru": "Rahat (prototype)\n1 English\n2 Roman Urdu"},
    "menu": {
        "en": "Rahat (prototype)\n1 Check my application\n2 Check a message\n3 Stop sharing my data\n4 Talk to a person\n0 Back",
        "ru": "Rahat (prototype)\n1 Meri darkhwast dekhein\n2 Paigham check karein\n3 Mera data share rokein\n4 Kisi se baat karein\n0 Wapas",
    },
    "status_ask": {
        "en": "Type the 5 digits of your code (R-12345 is 12345).\n0 Back\n00 Menu",
        "ru": "Apne code ke 5 hindsay likhein (R-12345 matlab 12345).\n0 Wapas\n00 Menu",
    },
    "status_result": {"en": "{code} ({symbols})\n{line}\n0 Back\n00 Menu", "ru": "{code} ({symbols})\n{line}\n0 Wapas\n00 Menu"},
    "status_none": {
        "en": "Not found. Check the digits. Use the phone you signed up with.\nTry again.\n0 Back",
        "ru": "Nahin mila. Hindsay dekhein. Wohi phone use karein jo darj hai.\nDobara likhein.\n0 Wapas",
    },
    "status_format": {"en": "Please type exactly 5 digits, like 12345.\n0 Back", "ru": "Sirf 5 hindsay likhein, jaise 12345.\n0 Wapas"},
    "verify_ask": {
        "en": "Type the 6 letters or digits after the word Code at the end of the message.\n0 Back\n00 Menu",
        "ru": "Paigham ke aakhir mein lafz Code ke baad ke 6 harf ya hindsay likhein.\n0 Wapas\n00 Menu",
    },
    "verify_genuine": {
        "en": "This is a genuine Rahat message. Rahat never asks for a fee or your PIN.\n0 Back\n00 Menu",
        "ru": "Yeh asli Rahat paigham hai. Rahat kabhi fees ya PIN nahin mangta.\n0 Wapas\n00 Menu",
    },
    "verify_unknown": {
        "en": "We cannot confirm this message. Do not pay or share your PIN. Ask a person: menu, then 4.\n0 Back\n00 Menu",
        "ru": "Is paigham ki tasdeeq nahin hui. Paisay ya PIN na dein. Afsar se poochein: menu, phir 4.\n0 Wapas\n00 Menu",
    },
    "verify_format": {"en": "The code has 6 letters or digits.\n0 Back", "ru": "Code mein 6 harf ya hindsay hotay hain.\n0 Wapas"},
    "stop_ask": {
        "en": "To stop sharing your data, type your PIN.\nWe never ask for a fee.\n0 Back\n00 Menu",
        "ru": "Data share rokne ke liye apna PIN likhein.\nHum fees nahin mangte.\n0 Wapas\n00 Menu",
    },
    "stop_bad": {"en": "The PIN is not right.\nTry again.\n0 Back", "ru": "PIN durust nahin.\nDobara likhein.\n0 Wapas"},
    "stop_format": {"en": "The PIN has 4 to 6 digits.\n0 Back", "ru": "PIN mein 4 se 6 hindsay hotay hain.\n0 Wapas"},
    "stop_done": {
        "en": "Done. Rahat stopped using your data. Your application is on hold. You can allow it again in the app.",
        "ru": "Ho gaya. Rahat ne aap ka data istemal karna band kar diya. Darkhwast ruki hai. App mein dobara ijazat de sakte hain.",
    },
    "stop_locked": {"en": "Too many tries. Please try later.", "ru": "Bohat koshishein. Baad mein try karein."},
    "callback_confirm": {
        "en": "A person will call this phone.\n1 Yes, call me\n0 Back\n00 Menu",
        "ru": "Aik afsar is phone par call karega.\n1 Haan, call karein\n0 Wapas\n00 Menu",
    },
    "callback_done": {
        "en": "Thank you. If this number is registered, a person will call you in 2 working days.",
        "ru": "Shukriya. Agar yeh number darj hai to aik afsar 2 kaam ke dinon mein call karega.",
    },
    "too_many": {"en": "Too many wrong tries. Please dial again later.", "ru": "Bohat ghalat koshishein. Baad mein dobara dial karein."},
    "timeout": {"en": "Session ended. Dial *786# to start again.", "ru": "Session khatam. Dobara shuru karne ke liye *786# dial karein."},
    "throttled": {"en": "Too many requests. Please wait a minute.", "ru": "Bohat requests. Aik minute rukein."},
    "error": {"en": "Rahat is busy. Please try again later.", "ru": "Rahat masroof hai. Baad mein try karein."},
    "bye": {"en": "Goodbye. Rahat (prototype).", "ru": "Khuda hafiz. Rahat (prototype)."},
    "wrong": {"en": "Wrong choice.", "ru": "Ghalat intikhab."},
}  # fmt: skip

# SMS replies. Each ends with a verify code (12 characters more) when sent, so the base text stays short.
SMS: Final[dict[str, dict[str, str]]] = {
    "status_ok": {
        "en": "Rahat: {code} ({symbols}). {line}",
        "ru": "Rahat: {code} ({symbols}). {line}",
    },
    "status_none": {
        "en": "Rahat: we could not find that code for this phone. Check the digits and send STATUS again.",
        "ru": "Rahat: yeh code is phone ke liye nahin mila. Hindsay dekh kar dobara STATUS bhejein.",
    },
    "verify_genuine": {
        "en": "Rahat: that is a genuine Rahat message. We never ask for a fee or your PIN.",
        "ru": "Rahat: woh asli Rahat paigham hai. Hum fees ya PIN nahin mangte.",
    },
    "verify_unknown": {
        "en": "Rahat: we cannot confirm that message. Do not pay or share your PIN. A person can help: dial *786#.",
        "ru": "Rahat: us paigham ki tasdeeq nahin hui. Paisay ya PIN na dein. Madad ke liye *786# dial karein.",
    },
    "stop_done": {
        "en": "Rahat: we stopped using your data. Your application is on hold. You can allow it again in the app.",
        "ru": "Rahat: hum ne aap ka data istemal karna band kar diya. Darkhwast ruki hai. App mein dobara ijazat dein.",
    },
    "stop_bad": {
        "en": "Rahat: the PIN is not right. Send STOP and your PIN again. We never ask for a fee.",
        "ru": "Rahat: PIN durust nahin. STOP aur apna PIN dobara bhejein. Hum fees nahin mangte.",
    },
    "stop_locked": {"en": "Rahat: too many tries. Please try later.", "ru": "Rahat: bohat koshishein. Baad mein try karein."},
    "help": {
        "en": "Rahat: send STATUS 12345, VERIFY CODE or STOP PIN. For a person dial *786#. We never ask for a fee or PIN.",
        "ru": "Rahat: STATUS 12345, VERIFY CODE ya STOP PIN bhejein. Afsar ke liye *786# dial karein. Hum fees ya PIN nahin mangte.",
    },
    "scam_warning": {
        "en": "Rahat: that message looks like a scam. Do not pay, click or share your PIN. Dial *786# for a person.",
        "ru": "Rahat: woh paigham scam lagta hai. Paisay, link ya PIN na dein. Afsar ke liye *786# dial karein.",
    },
    "throttled": {"en": "Rahat: too many messages. Please wait a minute.", "ru": "Rahat: bohat paigham. Aik minute rukein."},
}  # fmt: skip


def pick_lang(lang: str | None) -> str:
    return lang if lang in LANGS else "en"


def symbols_text(symbols: list[str] | tuple[str, ...], lang: str) -> str:
    lang = pick_lang(lang)
    return " ".join(SYMBOL_NAMES[s][lang] for s in symbols if s in SYMBOL_NAMES)


def status_line(status: str, lang: str) -> str:
    return STATUS_LINES.get(status, STATUS_FALLBACK)[pick_lang(lang)]


def screen(key: str, lang: str, **values: str) -> str:
    return SCREENS[key][pick_lang(lang)].format(**values)


def sms(key: str, lang: str, **values: str) -> str:
    return SMS[key][pick_lang(lang)].format(**values)
