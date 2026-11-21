"""Invented names for the synthetic world, with the spelling variants seen in Pakistani records.

Common given names and family names only, always paired with mock IDs (00000-...) and mock phones (0999-...),
so no generated record can describe a real person.
"""

from __future__ import annotations

import random
from typing import Final

FEMALE: Final[dict[str, str]] = {
    "Zainab": "زینب", "Fatima": "فاطمہ", "Ayesha": "عائشہ", "Khadija": "خدیجہ", "Maryam": "مریم", "Sana": "ثنا",
    "Rukhsana": "رخسانہ", "Nasreen": "نسرین", "Shazia": "شازیہ", "Parveen": "پروین", "Amina": "آمنہ", "Bushra": "بشریٰ",
    "Saima": "صائمہ", "Nadia": "نادیہ", "Razia": "رضیہ", "Shabana": "شبانہ", "Farzana": "فرزانہ", "Kulsoom": "کلثوم",
    "Sughra": "صغریٰ", "Hajra": "ہاجرہ",
}  # fmt: skip
MALE: Final[dict[str, str]] = {
    "Muhammad": "محمد", "Ahmed": "احمد", "Ali": "علی", "Hassan": "حسن", "Bilal": "بلال", "Imran": "عمران", "Asif": "آصف",
    "Tariq": "طارق", "Kashif": "کاشف", "Faisal": "فیصل", "Usman": "عثمان", "Zahid": "زاہد", "Naveed": "نوید",
    "Shahid": "شاہد", "Akbar": "اکبر", "Rashid": "راشد", "Junaid": "جنید", "Salman": "سلمان", "Waseem": "وسیم",
    "Arshad": "ارشد",
}  # fmt: skip
FAMILY: Final[dict[str, str]] = {
    "Khan": "خان", "Shah": "شاہ", "Qureshi": "قریشی", "Siddiqui": "صدیقی", "Ansari": "انصاری", "Baloch": "بلوچ",
    "Memon": "میمن", "Soomro": "سومرو", "Abbasi": "عباسی", "Butt": "بٹ", "Malik": "ملک", "Chaudhry": "چوہدری",
    "Mirza": "مرزا", "Sheikh": "شیخ", "Rajput": "راجپوت", "Jatoi": "جتوئی", "Magsi": "مگسی", "Bhatti": "بھٹی",
}  # fmt: skip
FEMALE_SUFFIX: Final[dict[str, str]] = {"Bibi": "بی بی", "Begum": "بیگم"}

SPELLINGS: Final[dict[str, tuple[str, ...]]] = {
    "Muhammad": ("Mohammad", "Muhammed", "Mohd", "Mohammed", "M."), "Ahmed": ("Ahmad",), "Hassan": ("Hasan",),
    "Fatima": ("Fatma", "Fatimah"), "Ayesha": ("Aisha", "Ayisha"), "Khadija": ("Khadijah",), "Maryam": ("Mariam", "Maryum"),
    "Nasreen": ("Nasrin",), "Parveen": ("Parvin", "Perveen"), "Amina": ("Aminah", "Ameena"), "Razia": ("Raziya",),
    "Kulsoom": ("Kulsum", "Kalsoom"), "Sughra": ("Soghra",), "Hajra": ("Hajira", "Hajrah"), "Usman": ("Osman",),
    "Zahid": ("Zaheed",), "Naveed": ("Navid",), "Shahid": ("Shaheed",), "Rashid": ("Rasheed",), "Waseem": ("Wasim",),
    "Chaudhry": ("Chaudhary", "Choudhry"), "Siddiqui": ("Siddiqi", "Sidiqui"), "Qureshi": ("Qurashi",),
    "Sheikh": ("Shaikh",), "Soomro": ("Sumro",), "Zainab": ("Zenab", "Zaynab"), "Bibi": ("Bi Bi", "Bb"),
    "Begum": ("Begam",),
}  # fmt: skip
HONORIFICS: Final[tuple[str, ...]] = ("Mst.", "Mrs.", "Syed", "Haji", "Mian")

DISTRICTS: Final[tuple[str, ...]] = (
    "Karachi East", "Karachi West", "Karachi South", "Hyderabad", "Thatta", "Badin", "Sukkur", "Larkana", "Dadu",
    "Tharparkar", "Mirpurkhas", "Sanghar",
)  # fmt: skip


def make_name(rng: random.Random, gender: str, family: str) -> tuple[str, str]:
    """A canonical Latin-script name and its Urdu-script form."""
    pool = FEMALE if gender == "female" else MALE
    given = rng.choice(sorted(pool))
    parts = [given]
    urdu = [pool[given]]
    if gender == "male" and given != "Muhammad" and rng.random() < 0.3:
        parts.insert(0, "Muhammad")
        urdu.insert(0, MALE["Muhammad"])
    if gender == "female" and rng.random() < 0.45:
        suffix = rng.choice(sorted(FEMALE_SUFFIX))
        parts.append(suffix)
        urdu.append(FEMALE_SUFFIX[suffix])
    else:
        parts.append(family)
        urdu.append(FAMILY[family])
    return " ".join(parts), " ".join(urdu)


def messy_variant(rng: random.Random, name: str, *, mess: float = 0.5) -> str:
    """How a name may be typed, spoken or transcribed: other spellings, honorifics, dropped parts, case."""
    parts = name.split()
    out: list[str] = []
    for part in parts:
        options = SPELLINGS.get(part)
        out.append(rng.choice(options) if options and rng.random() < mess else part)
    if len(out) > 2 and rng.random() < mess * 0.4:
        out.pop(1)
    if rng.random() < mess * 0.25:
        out.insert(0, rng.choice(HONORIFICS))
    if len(out) >= 2 and rng.random() < mess * 0.1:
        out[0], out[-1] = out[-1], out[0]
    text = " ".join(out)
    roll = rng.random()
    if roll < mess * 0.2:
        text = text.upper()
    elif roll < mess * 0.3:
        text = text.lower()
    if rng.random() < mess * 0.1:
        text = text.replace(" ", "  ", 1)
    return text


def name_variants(rng: random.Random, name: str, count: int = 3) -> tuple[str, ...]:
    seen: list[str] = []
    for _ in range(count * 3):
        variant = messy_variant(rng, name, mess=0.7)
        if variant != name and variant not in seen:
            seen.append(variant)
        if len(seen) >= count:
            break
    return tuple(seen)
