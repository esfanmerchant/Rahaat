"""Synthetic scam corpus: English, Urdu and Roman Urdu messages written from template families.

    uv run python -m app.modules.scam.corpus          write data/scam/corpus.jsonl and data/scam/manifest.json
    uv run python -m app.modules.scam.corpus --check  fail when the committed files differ from a fresh run

Every message is invented (SYNTHETIC). Phones are mock `0999-NNNNNNN`, IP hosts come from the documentation
ranges, and no real organisation is named. A family is one storyline (for example "pay a processing fee to
release your relief money"); its variants change spelling, script, numbers, senders and links. Train and test
are split by family, so every test storyline is unseen in training. Real Rahat messages are rendered by
`notifications.templates`, exactly as we send them.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.modules.notifications import templates
from app.modules.scam.signals import code_candidates

SEED = 20261121
GENERATOR_VERSION = "1"
TEST_SHARE = 0.3
DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "scam"
CORPUS_FILE = DATA_DIR / "corpus.jsonl"
MANIFEST_FILE = DATA_DIR / "manifest.json"

SCAM_LABELS = ("relief_scam", "phishing_link", "advance_fee", "impersonation")
LEGIT_LABELS = ("legit_program_message", "unknown")


@dataclass(frozen=True)
class Family:
    name: str
    label: str
    lang: str  # en | ur | roman | en+ur
    phrasings: tuple[str, ...]
    senders: str  # a key of SENDER_MIX
    n: int = 45
    code: str | None = None  # "fake": a code that looks like ours; "genuine": a real code on altered text


# --- slot values (all invented) -------------------------------------------------------------------------

PROGRAMS = ("Rahat", "Rahat Program", "Rahat Relief", "Rahat Relief Program", "Govt Relief Fund", "National Relief Package",
            "Imdadi Program", "Relief Card", "Madad Program", "Flood Relief Fund", "Hukumati Imdad", "Rahat Card")  # fmt: skip
PROGRAMS_UR = ("راحت پروگرام", "راحت ریلیف", "امدادی پروگرام", "حکومتی امداد", "ریلیف فنڈ", "مدد پروگرام", "راحت کارڈ", "سیلاب ریلیف فنڈ")
RELIEF_AMOUNTS = (8500, 10000, 12000, 14500, 15000, 25000, 35000)
FEES = (300, 500, 750, 1000, 1500, 2000, 2500)
BIG = (50000, 100000, 250000, 500000, 1000000)
SMALL = (500, 1000, 1500, 2000, 3000, 5000)
BANKS = ("Sitara Bank", "Noor Bank", "Indus Valley Bank", "your bank", "the bank")
WALLETS = ("mobile wallet", "mobile account", "wallet", "bank account", "e-wallet")
OFFICERS = ("Officer Kamran", "Inspector Tariq", "Assistant Director Saleem", "Officer Imran", "Mr Ahmed", "Officer Nadeem")
SHOPS = ("City Mart", "Karachi Grocers", "Al-Madina General Store", "Bismillah Kiryana", "Star Electronics", "Green Pharmacy")
SHOPS_UR = ("مدینہ جنرل سٹور", "سٹی مارٹ", "بسم اللہ کریانہ", "گرین فارمیسی")
NAMES = ("Bilal", "Sana", "Usman", "Hina", "Asad", "Farah", "Kashif", "Rabia")
BRANDS = ("Lucky Star", "Golden Draw", "Mega Inaam", "Sitara", "Noor", "SIM Inaam Scheme")
CLINICS = ("City Clinic", "Family Health Centre", "Noor Dental", "Shifa Lab")
AREAS = ("Saddar", "Gulshan", "Latifabad", "Clifton", "Korangi", "Qasimabad")
TELCOS = ("SIM company helpline", "network helpline", "mobile company office")
DATES = ("25 Nov", "30 Nov", "5 Dec", "10 Dec", "15 Dec")
LOOKALIKE_BASES = ("rahat-gov", "rahat-relief", "rahatprogram", "r4hat-pk", "gov-pk-rahat", "rahaat", "rahat-online", "imdad-portal",
                   "relief-fund-2026", "sarkari-imdad", "rahat-imdad", "govt-relief", "rahatcard", "rahat-pk-gov", "rehat-relief",
                   "official-rahat", "rahat-cash", "relief-payment")  # fmt: skip
SCAM_TLDS = ("xyz", "top", "online", "site", "info", "live", "icu", "click", "link", "buzz", "com", "net")
SHORT_HOSTS = ("bit.ly", "tinyurl.com", "cutt.ly", "rb.gy", "is.gd", "t.ly")
SCAM_PATHS = ("", "/claim", "/apply", "/verify", "/register", "/login", "/form", "/check-name", "/payment", "/kyc")
BENIGN_URLS = ("https://www.citymart.pk/offers", "https://sitarabank.com.pk/app", "https://karachigrocers.com/order",
               "https://www.noorbank.com.pk/help", "https://track.swiftcourier.pk/parcel", "https://www.greenpharmacy.pk",
               "https://starelectronics.pk/sale", "https://www.schoolportal.edu.pk/notice")  # fmt: skip
OFFICIAL_LOOKALIKE_SENDERS = ("RAHAT-GOV", "RAHAT-PK", "GOVT-RELIEF", "R4HAT", "RAHATPAY", "RELIEF-FUND", "RAHAT-INFO", "IMDAD-PK")
SCAM_ALPHA_SENDERS = ("INFO", "ALERT", "BANK-ALRT", "VERIFY", "NOTICE", "LUCKYDRAW", "PRIZE-PK", "HELPDESK")
BENIGN_ALPHA_SENDERS = ("SITARABANK", "NOORBANK", "CITYMART", "KGROCERS", "SWIFTCOUR", "GREENPHARM", "SCHOOL", "STARELEC")
CODE_ALPHABET = templates.CODE_ALPHABET

SENDER_MIX: dict[str, tuple[tuple[str, float], ...]] = {
    "relief": (("mobile", 0.55), ("lookalike", 0.2), ("none", 0.25)),
    "phish": (("mobile", 0.35), ("lookalike", 0.2), ("scam_alpha", 0.2), ("none", 0.25)),
    "adv": (("mobile", 0.6), ("scam_alpha", 0.1), ("none", 0.3)),
    "imp": (("mobile", 0.7), ("none", 0.3)),
    "program": (("official", 0.7), ("none", 0.2), ("mobile", 0.1)),
    "benign_org": (("benign_alpha", 0.6), ("none", 0.3), ("mobile", 0.1)),
    "family": (("mobile", 0.75), ("none", 0.25)),
}


class Slots:
    """Fills `{slot}` placeholders. Every value is invented; phones are mock numbers."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def phone(self) -> str:
        digits = f"{self.rng.randrange(10_000_000):07d}"
        style = self.rng.random()
        if style < 0.55:
            return f"0999-{digits}"
        if style < 0.8:
            return f"0999{digits}"
        if style < 0.9:
            return f"0999 {digits}"
        return f"+92 999 {digits}"

    def amount(self, values: tuple[int, ...]) -> str:
        value = self.rng.choice(values)
        style = self.rng.random()
        if style < 0.45:
            return f"{value:,}"
        if style < 0.8:
            return str(value)
        if value >= 100000 and value % 100000 == 0:
            return f"{value // 100000} lakh"
        return f"{value:,}/-"

    def code(self) -> str:
        while True:
            value = "".join(self.rng.choice(CODE_ALPHABET) for _ in range(templates.CODE_LENGTH))
            if any(c.isalpha() for c in value):
                return value

    def token(self, n: int) -> str:
        return "".join(self.rng.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(n))

    def scam_url(self) -> str:
        r = self.rng.random()
        if r < 0.45:
            host = f"{self.rng.choice(LOOKALIKE_BASES)}.{self.rng.choice(SCAM_TLDS)}"
            prefix = self.rng.choice(("http://", "https://", "", "www.", "http://www."))
            return prefix + host + self.rng.choice(SCAM_PATHS)
        if r < 0.6:
            host = f"rahat.gov.pk.{self.rng.choice(('verify', 'claim', 'secure', 'portal'))}-{self.token(4)}.{self.rng.choice(SCAM_TLDS)}"
            return self.rng.choice(("http://", "https://", "")) + host + self.rng.choice(SCAM_PATHS)
        if r < 0.8:
            return self.rng.choice(("", "https://", "http://")) + f"{self.rng.choice(SHORT_HOSTS)}/{self.token(self.rng.randint(5, 7))}"
        if r < 0.9:
            ip = f"{self.rng.choice(('192.0.2', '198.51.100', '203.0.113'))}.{self.rng.randint(2, 254)}"
            return f"http://{ip}{self.rng.choice(SCAM_PATHS) or '/claim'}"
        if r < 0.95:
            return f"https://xn--rhat-{self.token(3)}.{self.rng.choice(('com', 'pk', 'net'))}{self.rng.choice(SCAM_PATHS)}"
        return f"https://rаhat-relief.{self.rng.choice(('com', 'net'))}{self.rng.choice(SCAM_PATHS)}"  # Cyrillic a

    def apk_url(self) -> str:
        host = f"{self.rng.choice(LOOKALIKE_BASES)}.{self.rng.choice(SCAM_TLDS)}"
        scheme = self.rng.choice(("http://", "https://", ""))
        folder = self.rng.choice(("download", "app", "apk"))
        return f"{scheme}{host}/{folder}/{self.rng.choice(('rahat', 'relief-app', 'imdad'))}.apk"

    def wa_url(self) -> str:
        if self.rng.random() < 0.5:
            return f"https://wa.me/92999{self.rng.randrange(10_000_000):07d}"
        return f"https://chat.whatsapp.com/{self.token(10)}"

    def fill(self, phrasing: str) -> str:
        values: dict[str, Callable[[], str]] = {
            "program": lambda: self.rng.choice(PROGRAMS),
            "program_ur": lambda: self.rng.choice(PROGRAMS_UR),
            "amount": lambda: self.amount(RELIEF_AMOUNTS),
            "fee": lambda: self.amount(FEES),
            "big": lambda: self.amount(BIG),
            "small": lambda: self.amount(SMALL),
            "phone": self.phone,
            "url": self.scam_url,
            "url_apk": self.apk_url,
            "url_wa": self.wa_url,
            "benign_url": lambda: self.rng.choice(BENIGN_URLS),
            "bank": lambda: self.rng.choice(BANKS),
            "wallet": lambda: self.rng.choice(WALLETS),
            "officer": lambda: self.rng.choice(OFFICERS),
            "shop": lambda: self.rng.choice(SHOPS),
            "shop_ur": lambda: self.rng.choice(SHOPS_UR),
            "name": lambda: self.rng.choice(NAMES),
            "brand": lambda: self.rng.choice(BRANDS),
            "clinic": lambda: self.rng.choice(CLINICS),
            "area": lambda: self.rng.choice(AREAS),
            "telco": lambda: self.rng.choice(TELCOS),
            "date": lambda: self.rng.choice(DATES),
            "otp": lambda: f"{self.rng.randrange(100000, 999999)}",
            "last4": lambda: f"{self.rng.randrange(1000, 9999)}",
            "ref": lambda: f"TX{self.rng.randrange(10**8, 10**9)}",
            "order": lambda: f"{self.rng.randrange(10000, 99999)}",
            "hours": lambda: self.rng.choice(("24", "12", "48", "2")),
            "fakecode": self.code,
        }
        out = phrasing
        for key, make in values.items():
            while "{" + key + "}" in out:
                out = out.replace("{" + key + "}", make(), 1)
        return out


# --- families ---------------------------------------------------------------------------------------------

F = Family
FAMILIES: tuple[Family, ...] = (
    # relief_scam: fake relief payment messages
    F("relief.en.selected_fee", "relief_scam", "en", (
        "Congratulations! Your name has been selected for {program} relief of Rs {amount}. "
        "To receive the amount, pay a processing fee of Rs {fee} to {wallet} {phone}.",
        "Dear beneficiary, you are selected for {program}. Rs {amount} will be sent to you after you deposit Rs {fee} processing charges at {phone}.",
        "{program}: you qualify for Rs {amount}. Send the Rs {fee} release fee to {phone} today and the money comes to your account.",
    ), "relief"),
    F("relief.en.pin_release", "relief_scam", "en", (
        "{program}: Rs {amount} is ready in your name. Reply with your PIN and CNIC number to release the payment today.",
        "Your {program} payment of Rs {amount} is waiting. Send your wallet PIN and ID card number to this number to get it now.",
        "{program} notice: to release your Rs {amount} relief, share your account PIN with our team on {phone}.",
    ), "relief"),
    F("relief.en.call_officer", "relief_scam", "en", (
        "Dear beneficiary, your {program} payment of Rs {amount} is pending. "
        "Call our officer at {phone} within {hours} hours or the amount will be cancelled.",
        "{program}: your relief money of Rs {amount} is stuck. Contact {officer} on {phone} immediately to receive it.",
        "Important: your name is on the {program} list but your Rs {amount} is on hold. Call {phone} now, otherwise it will be returned.",
    ), "relief"),
    F("relief.en.registration_charge", "relief_scam", "en", (
        "{program} new registration is open. Send Rs {fee} registration charges to {phone} and get Rs {amount} every month.",
        "Register for {program} today. Only Rs {fee} fee, then receive Rs {amount} monthly. Send the fee to {wallet} {phone}.",
    ), "relief"),
    F("relief.en.tax_release", "relief_scam", "en", (
        "Your {program} grant of Rs {amount} is on hold. Deposit Rs {fee} government tax to release it and send the receipt on WhatsApp {phone}.",
        "{program}: Rs {amount} approved for you. A tax of Rs {fee} must be paid first. Pay to {phone} to receive your money.",
    ), "relief"),
    F("relief.en.otp_withdraw", "relief_scam", "en", (
        "{program} has transferred Rs {amount} to your account. To withdraw it, tell our agent the code you receive by SMS.",
        "Rs {amount} from {program} is in your wallet. Our agent will call you; give him the 4 digit code to withdraw the money.",
    ), "relief"),
    F("relief.en.template_hijack", "relief_scam", "en", (
        "Rahat: your application is approved. You will get Rs {amount}. To receive it, send Rs {fee} fee to {phone}. Code {fakecode}",
        "Rahat: Rs {amount} has been sent to you. To unlock it, pay Rs {fee} processing charge to {phone}. Code {fakecode}",
        "Rahat: we got your application. Send Rs {fee} to {phone} to confirm it. Code {fakecode}",
    ), "relief", n=40),
    F("relief.en.code_reuse", "relief_scam", "en", (
        "Rahat: your application is approved. You will get Rs {amount}. Pay a Rs {fee} release fee to {phone} first. Code {fakecode}",
        "Rahat: Rs {amount} has been sent to you. Share your PIN with our agent at {phone} to withdraw it. Code {fakecode}",
    ), "relief", n=30, code="genuine"),
    F("relief.ur.selected_fee", "relief_scam", "ur", (
        "مبارک ہو! آپ کا نام {program_ur} میں آ گیا ہے۔ {amount} روپے لینے کے لیے {fee} روپے فیس اس نمبر {phone} پر بھیجیں۔",
        "محترم، آپ {program_ur} کے لیے منتخب ہو گئے ہیں۔ {amount} روپے کی رقم کے لیے پہلے {fee} روپے پروسیسنگ فیس جمع کروائیں۔",
        "{program_ur}: آپ کو {amount} روپے ملیں گے۔ رقم وصول کرنے کے لیے {fee} روپے اس نمبر پر بھیج دیں {phone}",
    ), "relief"),
    F("relief.ur.pin_release", "relief_scam", "ur", (
        "{program_ur}: آپ کے نام {amount} روپے آ گئے ہیں۔ رقم وصول کرنے کے لیے اپنا پن کوڈ اور شناختی کارڈ نمبر بھیجیں۔",
        "آپ کی امدادی رقم {amount} روپے تیار ہے۔ رقم جاری کرنے کے لیے اپنا خفیہ پن اس نمبر {phone} پر بھیج دیں۔",
    ), "relief"),
    F("relief.ur.call_officer", "relief_scam", "ur", (
        "محترم، آپ کی {amount} روپے کی امدادی رقم رکی ہوئی ہے۔ آج ہی اس نمبر {phone} پر افسر سے رابطہ کریں ورنہ رقم واپس ہو جائے گی۔",
        "{program_ur} کی طرف سے اطلاع: آپ کی رقم {amount} روپے روک دی گئی ہے۔ فوراً {phone} پر کال کریں۔",
    ), "relief"),
    F("relief.ur.registration_fee", "relief_scam", "ur", (
        "{program_ur} کی نئی رجسٹریشن شروع۔ {fee} روپے رجسٹریشن فیس جمع کروائیں اور ہر ماہ {amount} روپے پائیں۔",
        "صرف {fee} روپے فیس دے کر {program_ur} میں نام لکھوائیں اور {amount} روپے ماہانہ حاصل کریں۔ رابطہ {phone}",
    ), "relief"),
    F("relief.ur.template_hijack", "relief_scam", "ur", (
        "راحت: آپ کی درخواست منظور ہو گئی ہے۔ آپ کو {amount} روپے ملیں گے۔ رقم کے لیے {fee} روپے فیس {phone} پر بھیجیں۔ کوڈ {fakecode}",
        "راحت: {amount} روپے آپ کو بھیج دیے گئے ہیں۔ رقم نکلوانے کے لیے اپنا پن کوڈ {phone} پر بتائیں۔ کوڈ {fakecode}",
    ), "relief", n=40),
    F("relief.roman.selected_fee", "relief_scam", "roman", (
        "Mubarak ho! Aap ka naam {program} mein aa gaya hai. {amount} rupay hasil karne ke liye {fee} rupay fee is number {phone} par bhejein.",
        "Aap {program} ke liye select ho gaye hain. {amount} rupay ki raqam ke liye pehle {fee} rupay processing fee jama karwain.",
        "{program}: aap ko {amount} rupay milenge. Raqam wusool karne ke liye {fee} rupay {phone} par bhej dein.",
    ), "relief"),
    F("relief.roman.pin_release", "relief_scam", "roman", (
        "{program}: aap ke naam {amount} rupay aa gaye hain. Raqam wusool karne ke liye apna PIN aur shanakhti card number reply karein.",
        "Aap ki imdadi raqam {amount} tayyar hai. Raqam jari karwane ke liye apna khufia PIN is number {phone} par bhejein.",
    ), "relief"),
    F("relief.roman.call_officer", "relief_scam", "roman", (
        "Aap ki {amount} ki imdadi raqam ruki hui hai. Foran is number {phone} par officer se rabta karein warna raqam wapas chali jayegi.",
        "{program} ki taraf se: aap ki raqam {amount} rupay rok di gayi hai. Aaj hi {officer} ko {phone} par call karein.",
    ), "relief"),
    F("relief.roman.registration", "relief_scam", "roman", (
        "{program} ki nayi registration shuru. Sirf {fee} rupay jama karwain aur har maah {amount} rupay hasil karein.",
        "Sirf {fee} rupay fee de kar {program} mein naam likhwayen aur {amount} rupay mahana payen. Rabta {phone}",
    ), "relief"),
    F("relief.roman.otp_agent", "relief_scam", "roman", (
        "Aap ke account mein {program} ke {amount} rupay transfer ho gaye hain. Nikalne ke liye jo code aaya hai woh hamare agent ko bata dein.",
        "{program} ki raqam {amount} aap ke wallet mein hai. Hamara agent call karega, us ko SMS wala code bata dein.",
    ), "relief"),
    # phishing_link: the hook is a link
    F("phish.en.kyc_update", "phishing_link", "en", (
        "Dear customer, your {wallet} will be blocked today. Update your KYC now at {url}",
        "Your {bank} account is suspended due to incomplete KYC. Verify within {hours} hours: {url}",
        "ALERT: your {wallet} needs biometric update. Click {url} to avoid closure.",
    ), "phish"),
    F("phish.en.relief_form", "phishing_link", "en", (
        "{program} registration 2026: check your eligibility and apply online at {url} before {date}.",
        "Apply for {program} online. Fill the form at {url} to get Rs {amount}.",
        "{program} list is out. See if your name is on it: {url}",
    ), "phish"),
    F("phish.en.parcel", "phishing_link", "en", (
        "Your parcel could not be delivered due to an incomplete address. Pay Rs {small} redelivery fee at {url}",
        "Courier: a package is waiting for you. Confirm your address and pay the delivery charge here {url}",
    ), "phish"),
    F("phish.en.sim_block", "phishing_link", "en", (
        "Your SIM will be blocked within {hours} hours due to biometric verification. Verify here: {url}",
        "Final notice: your mobile number will be closed. Re-verify your SIM at {url}",
    ), "phish"),
    F("phish.en.claim_link", "phishing_link", "en", (
        "You have Rs {amount} unclaimed {program} payment. Claim it here {url}",
        "{program}: your Rs {amount} is ready. Open {url} and enter your details to receive it.",
    ), "phish"),
    F("phish.ur.verify_card", "phishing_link", "ur", (
        "آپ کا شناختی کارڈ تصدیق نہ ہونے کی وجہ سے بند ہو جائے گا۔ فوراً اس لنک پر تصدیق کریں: {url}",
        "آپ کا موبائل اکاؤنٹ بند کیا جا رہا ہے۔ ابھی اس لنک سے معلومات اپ ڈیٹ کریں {url}",
    ), "phish"),
    F("phish.ur.relief_link", "phishing_link", "ur", (
        "{program_ur} میں اپنا نام چیک کرنے کے لیے یہ لنک کھولیں {url}",
        "{program_ur} کی نئی فہرست جاری ہو گئی ہے۔ اپنا نام دیکھنے کے لیے کلک کریں {url}",
    ), "phish"),
    F("phish.ur.prize_link", "phishing_link", "ur", (
        "آپ کا انعام تیار ہے، وصول کرنے کے لیے لنک پر کلک کریں {url}",
        "مبارک ہو آپ کو تحفہ ملا ہے۔ تفصیل کے لیے یہ لنک کھولیں {url}",
    ), "phish"),
    F("phish.roman.check_name", "phishing_link", "roman", (
        "Apna naam {program} ki list mein check karne ke liye is link par click karein {url}",
        "{program} ki nayi list aa gayi hai, apna naam dekhne ke liye link kholein {url}",
    ), "phish"),
    F("phish.roman.account_band", "phishing_link", "roman", (
        "Aap ka {wallet} band hone wala hai. Abhi is link se update karein {url} warna paise zabt ho jayenge.",
        "Aap ke account ki tasdeeq baqi hai. {hours} ghante mein is link par details dein {url}",
    ), "phish"),
    F("phish.roman.app_download", "phishing_link", "roman", (
        "{program} ki official app download karein aur raqam hasil karein: {url_apk}",
        "Raqam check karne ke liye ye app install karein {url_apk}",
    ), "phish", n=35),
    F("phish.roman.whatsapp_group", "phishing_link", "roman", (
        "{program} ki madad ke liye hamare WhatsApp group mein shamil hon {url_wa}",
        "Imdadi raqam ki tafseel ke liye is WhatsApp par message karein {url_wa}",
    ), "phish", n=35),
    # advance_fee: a prize, job or loan that needs a payment first
    F("adv.en.lucky_draw", "advance_fee", "en", (
        "Congratulations! Your number has won Rs {big} in the {brand} lucky draw. Pay Rs {fee} tax to claim your prize. Call {phone}.",
        "You are the lucky winner of {brand}! Prize Rs {big}. Send Rs {fee} processing fee to {phone} to collect it.",
    ), "adv"),
    F("adv.en.job_offer", "advance_fee", "en", (
        "Job offer: work from home and earn Rs {amount} per week. Pay Rs {fee} registration to start. WhatsApp {phone}.",
        "Online typing job, Rs {small} daily. Registration fee Rs {fee} only. Send it to {wallet} {phone}.",
    ), "adv"),
    F("adv.en.loan", "advance_fee", "en", (
        "Get an instant loan of Rs {big} without any documents. Send Rs {fee} file charges to {phone} to get approval.",
        "Loan approved: Rs {big} at zero interest. Pay Rs {fee} insurance charges first to {wallet} {phone}.",
    ), "adv"),
    F("adv.en.foreign_gift", "advance_fee", "en", (
        "A gift parcel from abroad is held at customs for you. Pay Rs {fee} clearance charges to receive it. Call {phone}.",
        "Your friend sent you a gift box with gold and cash. Customs fee of Rs {fee} must be paid before delivery.",
    ), "adv"),
    F("adv.ur.lucky_draw", "advance_fee", "ur", (
        "مبارک ہو! آپ کا نمبر {big} روپے کے انعام کے لیے منتخب ہوا ہے۔ انعام لینے کے لیے {fee} روپے ٹیکس جمع کروائیں۔",
        "آپ نے {brand} قرعہ اندازی میں {big} روپے جیت لیے ہیں۔ انعام کے لیے {fee} روپے فیس {phone} پر بھیجیں۔",
    ), "adv"),
    F("adv.ur.car_prize", "advance_fee", "ur", (
        "آپ نے قرعہ اندازی میں گاڑی جیت لی ہے۔ رجسٹریشن کے لیے {fee} روپے اس نمبر پر بھیجیں {phone}",
        "مبارک ہو آپ کی موٹر سائیکل نکلی ہے۔ ڈیلیوری چارجز {fee} روپے جمع کروائیں۔",
    ), "adv"),
    F("adv.ur.job", "advance_fee", "ur", (
        "گھر بیٹھے نوکری، ہر ہفتے {amount} روپے کمائیں۔ شروع کرنے کے لیے {fee} روپے فیس بھیجیں۔",
        "آن لائن کام کریں اور روزانہ {small} روپے کمائیں۔ رجسٹریشن فیس صرف {fee} روپے، رابطہ {phone}",
    ), "adv"),
    F("adv.roman.inaam", "advance_fee", "roman", (
        "Mubarak ho! Aap ka number {brand} ke inaam mein nikla hai. {big} rupay ka inaam lene ke liye {fee} rupay tax jama karwain.",
        "Aap ne {brand} mein {big} rupay jeet liye hain. Inaam ke liye {fee} rupay {phone} par bhejein.",
    ), "adv"),
    F("adv.roman.loan", "advance_fee", "roman", (
        "Bina kisi kagaz ke {big} rupay ka qarza hasil karein. Sirf {fee} rupay file charges bhejein {phone}",
        "Aap ka loan {big} rupay manzoor ho gaya hai. Pehle {fee} rupay insurance fee jama karwain.",
    ), "adv"),
    F("adv.roman.job", "advance_fee", "roman", (
        "Ghar baithe online kaam karein aur rozana {small} rupay kamayein. Registration fee sirf {fee} rupay.",
        "Naukri ka mauqa! Har hafte {amount} rupay. Shuru karne ke liye {fee} rupay {phone} par bhej dein.",
    ), "adv"),
    F("adv.roman.bike_prize", "advance_fee", "roman", (
        "Aap ne {brand} lucky draw mein motorcycle jeet li hai. Delivery charges {fee} rupay is account mein bhejein {phone}",
        "Mubarak! Aap ki gaari nikli hai. Registration ke {fee} rupay foran jama karwain.",
    ), "adv"),
    # impersonation: poses as an officer, a bank or family and asks for a secret or money directly
    F("imp.en.bank_officer", "impersonation", "en", (
        "This is {bank} head office. Your account is suspended. Please share the 6 digit code we just sent to unblock it.",
        "{bank} security team here. Someone is using your card. Tell us the OTP you received to stop the payment.",
    ), "imp"),
    F("imp.en.rahat_officer", "impersonation", "en", (
        "I am {officer} from the {program} office. For verification of your payment, tell me the PIN of your account.",
        "{program} department: {officer} speaking. Send me the code you got on SMS so I can verify your case.",
    ), "imp"),
    F("imp.en.family_new_number", "impersonation", "en", (
        "Hi Mum, this is my new number. My phone broke. I need Rs {small} urgently, please send it to this account.",
        "Dad it is me, I lost my phone. Please send Rs {small} to {phone} right now, I will explain later.",
    ), "imp"),
    F("imp.en.police", "impersonation", "en", (
        "This is the police station. Your son has been arrested. Send Rs {amount} now to settle the matter, do not tell anyone.",
        "Police here. Your relative is in custody after an accident. Pay Rs {amount} to {phone} immediately for release.",
    ), "imp"),
    F("imp.ur.bank", "impersonation", "ur", (
        "میں بینک سے بات کر رہا ہوں۔ آپ کا اکاؤنٹ بند ہو گیا ہے۔ جو کوڈ آپ کو ابھی آیا ہے وہ بتا دیں۔",
        "بینک ہیلپ لائن: آپ کے کارڈ سے غلط ادائیگی ہو رہی ہے۔ روکنے کے لیے او ٹی پی بتائیں۔",
    ), "imp"),
    F("imp.ur.relief_officer", "impersonation", "ur", (
        "میں {program_ur} کے دفتر سے افسر بول رہا ہوں۔ آپ کی تصدیق کے لیے اپنا پن کوڈ بتائیں۔",
        "محکمہ امداد سے بات ہو رہی ہے۔ آپ کے موبائل پر آنے والا کوڈ ہمیں بتا دیں تاکہ رقم بھیجی جا سکے۔",
    ), "imp"),
    F("imp.ur.family", "impersonation", "ur", (
        "امی یہ میرا نیا نمبر ہے، پرانا فون خراب ہو گیا۔ مجھے فوراً {small} روپے بھیج دیں، بہت ضروری ہے۔",
        "ابو میں مشکل میں ہوں، یہ دوست کا نمبر ہے۔ جلدی سے {small} روپے اس نمبر پر بھیج دو {phone}",
    ), "imp"),
    F("imp.roman.rahat_office", "impersonation", "roman", (
        "Assalam o alaikum, main {program} office se {officer} baat kar raha hoon. Aap ki tasdeeq ke liye jo code SMS mein aaya hai woh bata dein.",
        "Main {program} ka officer hoon. Aap ki raqam bhejne se pehle apna PIN bata dein.",
    ), "imp"),
    F("imp.roman.family", "impersonation", "roman", (
        "Abbu ye mera naya number hai. Mera phone gum ho gaya. Jaldi se {small} rupay is number par bhej dein, baad mein bataunga.",
        "Ammi main musibat mein hoon, ye dost ka number hai. Foran {small} rupay {phone} par bhej do.",
    ), "imp"),
    F("imp.roman.telecom", "impersonation", "roman", (
        "Main {telco} se bol raha hoon. Aap ki SIM band hone wali hai, tasdeeq ke liye apne card ke aakhri 4 hindse aur PIN bata dein.",
        "{telco}: aap ka number block ho raha hai. Jo code aaya hai woh foran bata dein.",
    ), "imp"),
    F("imp.roman.police", "impersonation", "roman", (
        "Main police station se bol raha hoon. Aap ke bete ka accident hua hai, foran {amount} rupay {phone} par bhejein.",
        "Thane se baat ho rahi hai. Aap ka rishtedar giraftar hai, chhurwane ke liye {amount} rupay abhi bhejein.",
    ), "imp"),
    # unknown: ordinary messages (hard negatives: OTPs, money between family, fees that are real)
    F("ben.en.bank_otp", "unknown", "en", (
        "{otp} is your one-time password for login. Do not share it with anyone. {bank} will never call you for it.",
        "Your verification code is {otp}. It expires in 5 minutes. Never share this code.",
    ), "benign_org"),
    F("ben.en.bank_debit", "unknown", "en", (
        "Rs {small} has been debited from your account ending {last4} on {date}. Not you? Call the number on the back of your card.",
        "Your account ending {last4} was credited with Rs {amount} on {date}. Available balance Rs {big}.",
    ), "benign_org"),
    F("ben.en.shop_offer", "unknown", "en", (
        "{shop}: 20% off on all groceries this weekend. Visit us at {area} or order at {benign_url}",
        "{shop} sale! Buy 2 get 1 free on rice and oil till {date}. Visit our {area} branch.",
    ), "benign_org"),
    F("ben.en.family", "unknown", "en", (
        "Please pick up the kids from school at 2. Also buy milk and bread on the way.",
        "I will be late tonight, keep the food in the fridge. Call me if you need anything.",
        "Did you reach home? Send me a message when you get there.",
    ), "family"),
    F("ben.en.wallet_received", "unknown", "en", (
        "You have received Rs {small} from {name}. Your new balance is Rs {amount}. Ref {ref}.",
        "Payment received: Rs {small} from customer {name}. Ref {ref}.",
    ), "benign_org"),
    F("ben.en.appointment", "unknown", "en", (
        "Reminder: your appointment at {clinic} is tomorrow at 10:30 am. Reply C to cancel.",
        "{clinic}: your test report is ready. You can collect it from the counter after 4 pm.",
    ), "benign_org"),
    F("ben.en.utility_school_fee", "unknown", "en", (
        "Your electricity bill of Rs {small} is due on {date}. Pay at any bank branch or through your banking app.",
        "Dear parents, please pay the school fee of Rs {small} at the school office by {date}.",
    ), "benign_org"),
    F("ben.en.delivery_ok", "unknown", "en", (
        "Your order #{order} has been dispatched and will arrive in 2 to 3 days. Track it at {benign_url}",
        "Your parcel #{order} was delivered today. Thank you for shopping with {shop}.",
    ), "benign_org"),
    F("ben.en.bank_warning", "unknown", "en", (
        "{bank} will never ask for your PIN or OTP on a call. Report suspicious calls at your nearest branch.",
        "Stay safe: do not share your card PIN with anyone, even if they say they are from the bank.",
    ), "benign_org"),
    F("ben.en.news", "unknown", "en", (
        "Relief camps are open in {area} this week. Families can visit the camp between 9 am and 5 pm.",
        "The community kitchen in {area} will serve free food after Friday prayers.",
    ), "family"),
    F("ben.ur.family", "unknown", "ur", (
        "بیٹا شام کو آتے ہوئے سبزی لے آنا اور امی کی دوائی بھی۔",
        "میں کل صبح گاؤں جا رہا ہوں، دکان کا خیال رکھنا۔",
        "خالہ کی طبیعت اب بہتر ہے، فکر نہ کریں۔",
    ), "family"),
    F("ben.ur.shop", "unknown", "ur", (
        "{shop_ur}: عید کے موقع پر تمام کپڑوں پر 30 فیصد رعایت۔ آج ہی تشریف لائیں۔",
        "{shop_ur} میں نیا مال آ گیا ہے۔ آٹا اور چینی مناسب قیمت پر دستیاب ہے۔",
    ), "benign_org"),
    F("ben.ur.bank_otp", "unknown", "ur", (
        "آپ کا ون ٹائم پاس ورڈ {otp} ہے۔ یہ کوڈ کسی کو نہ بتائیں۔ بینک کبھی آپ سے یہ کوڈ نہیں مانگتا۔",
        "آپ کے اکاؤنٹ میں {small} روپے جمع ہو گئے ہیں۔ شکریہ۔",
    ), "benign_org"),
    F("ben.ur.mosque_school", "unknown", "ur", (
        "اطلاع: جمعہ کی نماز ڈیڑھ بجے ہوگی۔ تمام حضرات وقت پر تشریف لائیں۔",
        "محترم والدین، کل اسکول میں چھٹی ہوگی۔ پیر کو اسکول معمول کے مطابق کھلے گا۔",
    ), "benign_org"),
    F("ben.ur.money_family", "unknown", "ur", (
        "امی میں نے آپ کو {small} روپے بھیج دیے ہیں، دوائی لے لینا۔",
        "بھائی اس مہینے کی کمیٹی کے {small} روپے دس تاریخ تک جمع کروا دینا۔",
    ), "family"),
    F("ben.roman.family_money", "unknown", "roman", (
        "Ammi maine aap ko {small} bhej diye hain, dawai le lena. Shaam ko call karunga.",
        "Bhai is mahine ki committee ke {small} rupay 10 tareekh tak jama karwa dena.",
    ), "family"),
    F("ben.roman.family_chat", "unknown", "roman", (
        "Bhai kal dukaan der se kholna, main subah mandi ja raha hoon maal lene.",
        "Beta khana kha liya? Raat ko jaldi so jana, subah school hai.",
        "Kal shaadi mein sab ne aana hai, kapray tayyar rakhna.",
    ), "family"),
    F("ben.roman.shop_customer", "unknown", "roman", (
        "Bhai 2 kilo cheeni aur 1 litre tel bhej do, paise shaam ko de dunga.",
        "Aaj dukaan par naya maal aa gaya hai, chawal aur daal sasti hai.",
    ), "family"),
    F("ben.roman.wallet_received", "unknown", "roman", (
        "Aap ko {name} se Rs {small} mosool hue hain. Naya balance Rs {amount}.",
        "Aap ke account mein {small} rupay jama ho gaye hain. Shukriya.",
    ), "benign_org"),
    F("ben.roman.reminder", "unknown", "roman", (
        "Kal subah 9 baje doctor ka appointment hai, card saath le jana.",
        "School ki fees {small} rupay 10 tareekh tak school office mein jama karwa dein.",
    ), "benign_org"),
    F("ben.roman.news", "unknown", "roman", (
        "{area} mein relief camp khul gaya hai, subah 9 se shaam 5 baje tak.",
        "Masjid mein juma ke baad muft khana taqseem hoga, sab tashreef layen.",
    ), "family"),
    F("ben.roman.short", "unknown", "roman", (
        "ok", "kahan ho?", "aa raha hoon", "khana kha liya?", "theek hai", "call karo", "acha", "shukriya bhai",
    ), "family", n=30),
    F("ben.en.short", "unknown", "en", ("ok thanks", "on my way", "call me", "see you soon", "yes", "where are you?"), "family", n=24),
)  # fmt: skip

# --- surface variants -------------------------------------------------------------------------------------

ROMAN_SPELLINGS: dict[str, tuple[str, ...]] = {
    "hai": ("hai", "he", "hy"), "aap": ("aap", "ap"), "ke liye": ("ke liye", "k liye", "ky liye", "kay liye"),
    "rupay": ("rupay", "rupees", "rupaye", "rs"), "bhejein": ("bhejein", "bhejen", "bhejain", "send karein"),
    "karein": ("karein", "karen", "krein", "karain"), "mubarak": ("mubarak", "mubarik", "MUBARAK"), "raqam": ("raqam", "rakam"),
    "naam": ("naam", "nam"), "hasil": ("hasil", "haasil"), "foran": ("foran", "fauran"), "abhi": ("abhi", "abi"),
    "mein": ("mein", "main", "me", "mai"), "par": ("par", "pe", "per"), "aur": ("aur", "or"), "number": ("number", "nmbr", "no."),
    "jama": ("jama", "jamaa"), "bata dein": ("bata dein", "bta dein", "bata den"), "hain": ("hain", "hen", "hn"),
}  # fmt: skip
ROMAN_TO_URDU = {"mubarak ho": "مبارک ہو", "raqam": "رقم", "rupay": "روپے", "fee": "فیس", "foran": "فوراً"}
URDU_TO_ENGLISH = {"فیس": "fee", "پن کوڈ": "PIN code", "اکاؤنٹ": "account", "رجسٹریشن": "registration", "او ٹی پی": "OTP"}
URDU_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
ARABIC_FORMS = str.maketrans({"ی": "ي", "ک": "ك"})


def vary(rng: random.Random, text: str, family: Family) -> str:
    scam = family.label in SCAM_LABELS
    if family.lang == "roman":
        for word, options in ROMAN_SPELLINGS.items():
            if f" {word} " in f" {text} " and rng.random() < 0.6:
                text = (" " + text + " ").replace(f" {word} ", f" {rng.choice(options)} ", 1).strip()
        if rng.random() < 0.15:
            for roman, urdu in ROMAN_TO_URDU.items():
                if roman in text.lower() and rng.random() < 0.5:
                    text = text.replace(roman, urdu, 1)
        if rng.random() < 0.4:
            text = text.lower()
    elif family.lang == "ur":
        if rng.random() < 0.3:
            text = text.translate(URDU_DIGITS)
        if rng.random() < 0.2:
            for urdu, english in URDU_TO_ENGLISH.items():
                if urdu in text and rng.random() < 0.6:
                    text = text.replace(urdu, english, 1)
        if rng.random() < 0.1:
            text = text.translate(ARABIC_FORMS)
        if rng.random() < 0.2:
            text = text.replace("۔", " ")
    else:
        r = rng.random()
        if r < 0.1:
            text = text.lower()
        elif r < 0.18 and scam:
            text = text.upper()
    if scam and rng.random() < 0.12:
        text = text.rstrip(".") + rng.choice(("!!", "!!!", " !"))
    if rng.random() < 0.15:
        text = text.rstrip(".۔")
    if rng.random() < 0.12 and len(text) > 40:
        text = text.replace(". ", ".\n", 1).replace("۔ ", "۔\n", 1)
    if rng.random() < 0.08 and len(text) > 20:
        words = text.split(" ")
        i = rng.randrange(len(words))
        if len(words[i]) > 4 and words[i].isalpha():
            j = rng.randrange(len(words[i]) - 1)
            word = words[i]
            words[i] = word[:j] + word[j + 1] + word[j] + word[j + 2:]
            text = " ".join(words)
    if rng.random() < 0.05:
        text = rng.choice(("Fwd: ", "FW: ")) + text
    return text


def pick_sender(rng: random.Random, slots: Slots, mix: str) -> str | None:
    r, total = rng.random(), 0.0
    kind = SENDER_MIX[mix][-1][0]
    for option, share in SENDER_MIX[mix]:
        total += share
        if r < total:
            kind = option
            break
    if kind == "mobile":
        return slots.phone()
    if kind == "lookalike":
        return rng.choice(OFFICIAL_LOOKALIKE_SENDERS)
    if kind == "scam_alpha":
        return rng.choice(SCAM_ALPHA_SENDERS)
    if kind == "benign_alpha":
        return rng.choice(BENIGN_ALPHA_SENDERS)
    if kind == "official":
        return "RAHAT"
    return None


def _program_messages(rng: random.Random, slots: Slots) -> list[dict[str, Any]]:
    """Real Rahat messages, rendered by the same code that sends them. Most carry their verify code."""
    rows: list[dict[str, Any]] = []
    for template in templates.TEMPLATES:
        for lang in ("en", "ur"):
            for i in range(40):
                payload = {
                    "tracking_code": f"R-{rng.randrange(100000):05d}", "amount_pkr": rng.choice((12000, 12000, 10000, 15000)),
                    "rail_ref": f"MR-{rng.randrange(16**10):010X}", "proof_kind": rng.choice(("rahat_id", "income_proof", "other")),
                }  # fmt: skip
                text = templates.render(template, lang, payload)
                code: dict[str, Any] | None = None
                if rng.random() < 0.75:
                    value = slots.code()
                    text = templates.with_code(text, value, lang)
                    code = {"value": value, "genuine": True}
                if rng.random() < 0.06:
                    text = "Fwd: " + text
                if rng.random() < 0.1:
                    text = text.replace(". ", ".\n").replace("۔ ", "۔\n")
                rows.append({"id": f"program.{template}.{lang}-{i:03d}", "family": f"program.{template}", "label": "legit_program_message",
                             "lang": lang, "text": text, "sender": pick_sender(rng, slots, "program"), "code": code})  # fmt: skip
    return rows


def _family_messages(rng: random.Random, slots: Slots, family: Family) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempts = 0
    while len(rows) < family.n and attempts < family.n * 20:
        attempts += 1
        phrasing = family.phrasings[len(rows) % len(family.phrasings)] if attempts <= len(family.phrasings) else rng.choice(family.phrasings)
        text = vary(rng, slots.fill(phrasing), family)
        if text in seen and not family.name.endswith(".short"):
            continue
        seen.add(text)
        code = None
        if "Code " in text or "کوڈ " in text:
            found, _ = code_candidates(text)
            if found:
                code = {"value": found[-1], "genuine": family.code == "genuine"}
        rows.append({"id": f"{family.name}-{len(rows):03d}", "family": family.name, "label": family.label, "lang": family.lang,
                     "text": text, "sender": pick_sender(rng, slots, family.senders), "code": code})  # fmt: skip
    return rows


def _split(rng: random.Random, families: list[tuple[str, str, str]]) -> dict[str, str]:
    """Hold out about 30% of the families in every (label, language) group; at least one where a group has two."""
    groups: dict[tuple[str, str], list[str]] = {}
    for name, label, lang in sorted(families):
        groups.setdefault((label, lang), []).append(name)
    split: dict[str, str] = {}
    for key in sorted(groups):
        names = sorted(groups[key])
        rng.shuffle(names)
        n_test = max(1, round(len(names) * TEST_SHARE)) if len(names) >= 2 else 0
        for i, name in enumerate(names):
            split[name] = "test" if i < n_test else "train"
    return split


def generate(seed: int = SEED) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    slots = Slots(rng)
    rows = _program_messages(rng, slots)
    for family in FAMILIES:
        rows.extend(_family_messages(rng, slots, family))
    meta = sorted({(r["family"], r["label"], "both" if r["family"].startswith("program.") else r["lang"]) for r in rows})
    split = _split(random.Random(seed + 1), meta)
    for row in rows:
        row["split"] = split[row["family"]]
        row["synthetic"] = True
    return sorted(rows, key=lambda r: r["id"])


def serialise(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")


def manifest(rows: list[dict[str, Any]], data: bytes) -> dict[str, Any]:
    families = {r["family"]: (r["label"], r["split"]) for r in rows}
    return {
        "notice": "SYNTHETIC. Every message is invented for testing the Rahat prototype scam checker. Phones are mock 0999 numbers.",
        "seed": SEED,
        "generator_version": GENERATOR_VERSION,
        "sha256": hashlib.sha256(data).hexdigest(),
        "messages": len(rows),
        "families": len(families),
        "by_split_and_label": {f"{s}:{lb}": n for (s, lb), n in sorted(Counter((r["split"], r["label"]) for r in rows).items())},
        "by_lang": dict(sorted(Counter(r["lang"] for r in rows).items())),
        "test_families": sorted(name for name, (_, split) in families.items() if split == "test"),
    }


def load(path: Path = CORPUS_FILE) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def corpus_bytes(path: Path = CORPUS_FILE) -> bytes:
    return path.read_bytes()


def main(argv: list[str]) -> int:
    rows = generate()
    data = serialise(rows)
    info = manifest(rows, data)
    if "--check" in argv:
        same = CORPUS_FILE.exists() and CORPUS_FILE.read_bytes() == data
        print("corpus is up to date" if same else "corpus differs from a fresh run; regenerate it")
        return 0 if same else 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CORPUS_FILE.write_bytes(data)
    MANIFEST_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in info.items() if k != "test_families"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
