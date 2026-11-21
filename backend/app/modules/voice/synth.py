"""Labelled synthetic transcripts for the voice interpreter, split by template family.

A family is one way of answering ("hum {n} log hain", "{a} nahi, {b}", "جی ہاں"). Whole families go to
either the training split (used to tune the confidence floor) or the test split, so every test transcript
comes from a phrasing the floor never saw. Noise is added on top: typos, fillers, mixed script, case and
punctuation, and the speech engine's own confidence (sometimes missing, sometimes low).

Gold labels: the intended answer ("5", "yes", "under_15k", "unknown"), or "abstain" when a careful human
would also ask again ("paanch ya chhe", "nahi, main bewa hoon", "roz ke 500").
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from app.modules.guardrails.textnorm import tokens
from app.modules.voice import lexicon as L
from app.modules.voice.interpret import band_for

SEED: Final = 20261121


@dataclass(frozen=True, slots=True)
class Example:
    family: str
    split: str  # train | test
    question_key: str
    transcript: str
    gold: str
    stt_confidence: float | None = None
    expected_name: str | None = None


def roman(n: int, rng: random.Random) -> str:
    spellings = L._NUMBERS[n][1]  # noqa: SLF001
    if n == 2:
        return "do"
    if n == 1:
        return rng.choice(["ek", "aik"])
    if n == 60:
        return "saath"
    return rng.choice(spellings[:3]) if spellings else str(n)


def urdu(n: int) -> str:
    if n == 2:
        return "دو"
    return L._NUMBERS[n][0][0]  # noqa: SLF001


ENGLISH = {v: k for k, v in {**L.ENGLISH_UNITS, **L.ENGLISH_TENS}.items() if k != "fourty"}


def english(n: int) -> str:
    if n in ENGLISH:
        return ENGLISH[n]
    tens, unit = divmod(n, 10)
    return f"{ENGLISH[tens * 10]} {ENGLISH[unit]}"


Gen = Callable[[random.Random], tuple[str, str]]  # rng -> (transcript, gold)
_FAMILIES: list[tuple[str, str, str, Gen]] = []  # (family, split, question, generator)


def family(name: str, split: str, question: str) -> Callable[[Gen], Gen]:
    def register(fn: Gen) -> Gen:
        _FAMILIES.append((name, split, question, fn))
        return fn

    return register


def _people(rng: random.Random, low: int = 1, high: int = 12) -> int:
    return rng.randint(low, high)


# --- household size ------------------------------------------------------------------------------------

family("H01_digit", "train", "household_size")(lambda r: (str(n := _people(r)), str(n)))
family("H02_roman_word", "train", "household_size")(lambda r: (roman(n := _people(r, 3), r), str(n)))
family("H03_urdu_word", "test", "household_size")(lambda r: (urdu(n := _people(r, 3)), str(n)))
family("H04_english_word", "train", "household_size")(lambda r: (english(n := _people(r, 2)), str(n)))
family("H05_roman_sentence", "train", "household_size")(
    lambda r: (r.choice(["hum {} log hain", "ghar mein {} log hain", "hum {} afraad hain"]).format(roman(n := _people(r, 3), r)), str(n)))
family("H06_urdu_sentence", "test", "household_size")(
    lambda r: (r.choice(["ہم {} لوگ ہیں", "گھر میں {} افراد ہیں"]).format(urdu(n := _people(r, 3))), str(n)))
family("H07_english_sentence", "test", "household_size")(
    lambda r: (r.choice(["we are {} people", "there are {} of us", "{} people live in my home"]).format(english(n := _people(r, 2))), str(n)))
family("H08_mixed_script", "test", "household_size")(
    lambda r: (r.choice(["ہم {} log hain", "ghar mein {} افراد", "{} لوگ hain"]).format(n := _people(r)), str(n)))
family("H09_fillers", "train", "household_size")(
    lambda r: (r.choice(["umm... {} ... ji", "acha {} log", "dekhiye, {} hain"]).format(roman(n := _people(r, 3), r)), str(n)))


def _two(rng: random.Random, low: int = 3, high: int = 12) -> tuple[int, int]:
    a, b = rng.sample(range(low, high + 1), 2)
    return a, b


@family("H10_correction_roman", "train", "household_size")
def _h10(r: random.Random) -> tuple[str, str]:
    a, b = _two(r)
    return r.choice(["{a} nahi, {b}", "{a}... nahi nahi {b}", "{a} matlab {b} log"]).format(a=roman(a, r), b=roman(b, r)), str(b)


@family("H11_correction_urdu", "test", "household_size")
def _h11(r: random.Random) -> tuple[str, str]:
    a, b = _two(r)
    return r.choice(["{a} نہیں، {b}", "{a} نہیں {b} لوگ"]).format(a=urdu(a), b=urdu(b)), str(b)


family("H12_leading_no", "test", "household_size")(
    lambda r: (r.choice(["nahi, {} log", "no, {}", "نہیں، {}"]).format(roman(n := _people(r, 3), r)), str(n)))


@family("H13_alternatives", "train", "household_size")
def _h13(r: random.Random) -> tuple[str, str]:
    a, b = _two(r)
    return r.choice(["{a} ya {b}", "{a} or {b}"]).format(a=roman(a, r), b=roman(b, r)), "abstain"


@family("H14_parts", "test", "household_size")
def _h14(r: random.Random) -> tuple[str, str]:
    a, b = _two(r, 3, 6)
    return r.choice(["{a} bachay aur {b} baray", "{a} بچے اور {b} بڑے"]).format(a=roman(a, r), b=roman(b, r)), "abstain"


family("H15_unknown_roman", "train", "household_size")(lambda r: (r.choice(["pata nahi", "mujhe nahi maloom", "kya pata"]), "unknown"))
family("H16_unknown_urdu_en", "test", "household_size")(lambda r: (r.choice(["مجھے نہیں معلوم", "پتہ نہیں", "I don't know"]), "unknown"))
family("H17_mismatch_yes", "train", "household_size")(lambda r: (r.choice(["haan ji", "jee bilkul", "yes"]), "abstain"))
family("H18_mismatch_urdu", "test", "household_size")(lambda r: (r.choice(["جی ہاں", "نہیں جی"]), "abstain"))
family("H19a_do_unit", "train", "household_size")(lambda r: (r.choice(["do log", "do afraad", "sirf do bande"]), "2"))
family("H19b_do_hain", "test", "household_size")(lambda r: (r.choice(["hum do hain", "ہم دو ہیں", "ہم دو لوگ ہیں"]), "2"))
family("H19c_do_verb", "test", "household_size")(lambda r: (r.choice(["aap hi bata do", "paise do", "madad kar do"]), "abstain"))
family("H20a_alone", "train", "household_size")(lambda r: (r.choice(["main akeli hoon", "akela hoon", "sirf main"]), "1"))
family("H20b_alone_other", "test", "household_size")(lambda r: (r.choice(["میں اکیلی ہوں", "I live alone", "only me"]), "1"))
family("H21a_relative", "test", "household_size")(lambda r: (f"mere ilawa {roman(_people(r, 3), r)}", "abstain"))
family("H21b_relative_urdu", "train", "household_size")(lambda r: (f"میرے علاوہ {urdu(_people(r, 3))}", "abstain"))
family("H22a_approx", "train", "household_size")(lambda r: (f"taqreeban {roman(n := _people(r, 3), r)}", str(n)))
family("H22b_approx_en", "test", "household_size")(lambda r: (f"about {english(n := _people(r, 2))} people", str(n)))
family("H23a_out_of_range", "train", "household_size")(lambda r: (f"{roman(r.randint(25, 45), r)} log", "abstain"))
family("H23b_out_of_range_ur", "test", "household_size")(lambda r: (f"ہم {urdu(r.randint(25, 45))} لوگ ہیں", "abstain"))
family("H24_negated", "test", "household_size")(lambda r: (f"{roman(_people(r, 3), r)} nahi", "abstain"))
family("H25a_digits_en", "test", "household_size")(lambda r: (f"{n} people" if (n := _people(r)) > 1 else "1 person", str(n)))
family("H25b_we_are_digit", "train", "household_size")(lambda r: (f"we are {(n := _people(r, 2))}", str(n)))
family("H26_no_people", "test", "household_size")(lambda r: (r.choice(["no log", "no afraad"]), "abstain"))


@family("H27_two_bare", "test", "household_size")
def _h27(r: random.Random) -> tuple[str, str]:
    a = _people(r, 3, 10)
    return f"{roman(a, r)} {roman(a + 1, r)} log", "abstain"


family("H28_urdu_long", "train", "household_size")(lambda r: (f"ہمارے گھر میں کل {urdu(n := _people(r, 3))} افراد رہتے ہیں", str(n)))
family("H29_roman_long", "test", "household_size")(
    lambda r: (f"hamare ghar mein kul {roman(n := _people(r, 3), r)} afraad rehte hain", str(n)))
family("H30a_hedge_en", "train", "household_size")(lambda r: (f"maybe {english(_people(r, 2))}", "abstain"))
family("H30b_hedge_roman", "test", "household_size")(lambda r: (f"shayad {roman(_people(r, 3), r)}", "abstain"))

# --- income --------------------------------------------------------------------------------------------

_THOUSANDS = [5, 7, 8, 10, 12, 13, 14, 18, 20, 22, 24, 25, 26, 28, 35, 40, 45, 48, 55, 60, 70, 80]


def _k(rng: random.Random) -> int:
    return rng.choice(_THOUSANDS)


def _band(k: int) -> str:
    return band_for(k * 1000)


family("I01_roman_hazaar", "train", "income_band")(lambda r: (f"{roman(k := _k(r), r)} hazaar", _band(k)))
family("I02_digits", "train", "income_band")(lambda r: (r.choice(["{:,}", "{}", "Rs. {}", "{} rupay"]).format((k := _k(r)) * 1000), _band(k)))
family("I03_urdu_hazaar", "test", "income_band")(lambda r: (f"{urdu(k := _k(r))} ہزار روپے", _band(k)))
family("I04_english", "test", "income_band")(lambda r: (f"{english(k := _k(r))} thousand rupees", _band(k)))
family("I05_roman_sentence", "train", "income_band")(lambda r: (f"mahine ke {roman(k := _k(r), r)} hazaar aate hain", _band(k)))
family("I06_urdu_sentence", "test", "income_band")(lambda r: (f"مہینے کے {urdu(k := _k(r))} ہزار آتے ہیں", _band(k)))
family("I07a_zero", "train", "income_band")(lambda r: (r.choice(["kuch nahi", "koi aamdani nahi", "kuch bhi nahi aata"]), "under_15k"))
family("I07b_zero_other", "test", "income_band")(lambda r: (r.choice(["کچھ نہیں", "nothing", "no income"]), "under_15k"))
family("I08a_period", "train", "income_band")(
    lambda r: (r.choice(["roz ke {} sau", "hafte ke {} hazaar", "din ka {} sau"]).format(roman(r.randint(3, 9), r)), "abstain"))
family("I08b_period_ur", "test", "income_band")(
    lambda r: (r.choice(["روزانہ {} سو", "ہفتے کے {} ہزار", "daily {} hundred"]).format(urdu(r.randint(3, 9))), "abstain"))


def _pair_same_band(rng: random.Random) -> tuple[int, int]:
    while True:
        a, b = sorted(rng.sample(_THOUSANDS, 2))
        if _band(a) == _band(b) and a * 1000 not in (15_000, 30_000, 50_000):
            return a, b


def _pair_spanning(rng: random.Random) -> tuple[int, int]:
    while True:
        a, b = sorted(rng.sample(_THOUSANDS, 2))
        if _band(a) != _band(b):
            return a, b


@family("I09a_adjacent_same", "test", "income_band")
def _i09a(r: random.Random) -> tuple[str, str]:
    a, b = _pair_same_band(r)
    return f"{roman(a, r)} {roman(b, r)} hazaar", _band(a)


@family("I09b_adjacent_span", "test", "income_band")
def _i09b(r: random.Random) -> tuple[str, str]:
    a, b = _pair_spanning(r)
    return f"{roman(a, r)} {roman(b, r)} hazaar", "abstain"


@family("I10a_se_same", "train", "income_band")
def _i10a(r: random.Random) -> tuple[str, str]:
    a, b = _pair_same_band(r)
    return f"{roman(a, r)} se {roman(b, r)} hazaar", _band(a)


@family("I10b_se_span", "train", "income_band")
def _i10b(r: random.Random) -> tuple[str, str]:
    a, b = _pair_spanning(r)
    return f"{roman(a, r)} se {roman(b, r)} hazaar", "abstain"


family("I11a_less", "train", "income_band")(lambda r: (r.choice(["pandrah hazaar se kam", "das hazaar se bhi kam"]), "under_15k"))
family("I11b_more_ur", "test", "income_band")(lambda r: (r.choice(["پچاس ہزار سے زیادہ", "more than fifty thousand"]), "over_50k"))
family("I11c_bound_span", "test", "income_band")(lambda r: (r.choice(["tees hazaar se kam", "bees hazaar se zyada"]), "abstain"))
family("I12a_unit_missing", "train", "income_band")(lambda r: (roman(r.randint(5, 45), r), "abstain"))
family("I12b_unit_missing_ur", "test", "income_band")(lambda r: (urdu(r.randint(5, 45)), "abstain"))


@family("I13a_correction", "test", "income_band")
def _i13a(r: random.Random) -> tuple[str, str]:
    a, b = r.sample(_THOUSANDS, 2)
    return f"{roman(a, r)} nahi, {roman(b, r)} hazaar", _band(b)


@family("I13b_correction_full", "train", "income_band")
def _i13b(r: random.Random) -> tuple[str, str]:
    a, b = r.sample(_THOUSANDS, 2)
    return f"{roman(a, r)} hazaar nahi {roman(b, r)} hazaar", _band(b)


family("I14a_lakh", "train", "income_band")(lambda r: (r.choice(["ek lakh", "aik lakh", "do lakh", "dedh lakh"]), "over_50k"))
family("I14b_lakh_ur", "test", "income_band")(lambda r: (r.choice(["ڈیڑھ لاکھ", "ایک لاکھ روپے", "one lakh"]), "over_50k"))
family("I15a_unknown", "train", "income_band")(lambda r: (r.choice(["pata nahi kitne", "mujhe nahi pata"]), "unknown"))
family("I15b_unknown_ur", "test", "income_band")(lambda r: (r.choice(["معلوم نہیں", "I am not sure"]), "unknown"))
family("I16_typo_unit", "test", "income_band")(lambda r: (f"{roman(k := _k(r), r)} {r.choice(['hazar', 'hajar', 'hazzar'])}", _band(k)))
family("I17a_mixed_ur", "test", "income_band")(lambda r: (f"{(k := _k(r))} ہزار", _band(k)))
family("I17b_mixed_roman", "train", "income_band")(lambda r: (f"{(k := _k(r))} hazaar", _band(k)))
family("I18_k_notation", "test", "income_band")(lambda r: (f"{(k := _k(r))}k", _band(k)))
family("I19a_boundary", "train", "income_band")(lambda r: (r.choice(["tees hazaar", "pandrah hazaar"]), "15k_30k"))
family("I19b_boundary_other", "test", "income_band")(
    lambda r: r.choice([("پندرہ ہزار", "15k_30k"), ("fifty thousand", "30k_50k"), ("تیس ہزار", "15k_30k")]))
family("I20a_mismatch", "train", "income_band")(lambda r: (r.choice(["haan", "nahi ji"]), "abstain"))
family("I20b_mismatch_ur", "test", "income_band")(lambda r: (r.choice(["جی ہاں", "yes"]), "abstain"))
family("I21a_approx_safe", "train", "income_band")(
    lambda r: r.choice([("lagbhag das hazaar", "under_15k"), ("taqreeban chalees hazaar", "30k_50k")]))
family("I21b_approx_boundary", "test", "income_band")(lambda r: (r.choice(["taqreeban tees hazaar", "about fifteen thousand"]), "abstain"))

# --- yes / no ------------------------------------------------------------------------------------------

YES_NO_QUESTIONS = ("is_widow", "has_disability", "receives_other_aid")
_TOPIC_YES = {
    "is_widow": (["main bewa hoon", "haan main bewa hoon"], ["میں بیوہ ہوں"], ["I am a widow"]),
    "has_disability": (["haan mera beta mazoor hai", "ghar mein ek mazoor hai"], ["ہاں، میری بیٹی معذور ہے"], ["yes, my son is disabled"]),
    "receives_other_aid": (["haan BISP se milte hain", "zakat milti hai"], ["ہاں، بینظیر سے ملتے ہیں"], ["yes, we get BISP"]),
}
_TOPIC_NO = {
    "is_widow": (["main bewa nahi hoon"], ["میں بیوہ نہیں ہوں"], ["I am not a widow"]),
    "has_disability": (["koi mazoor nahi"], ["کوئی معذور نہیں"], ["no one is disabled"]),
    "receives_other_aid": (["kuch nahi milta", "koi madad nahi milti"], ["کچھ نہیں ملتا"], ["we get no aid"]),
}


def _pick(choices: list[tuple[str, str]]) -> Gen:
    def gen(r: random.Random) -> tuple[str, str]:
        return r.choice(choices)

    return gen


def _pick_text(texts: list[str], gold: str) -> Gen:
    def gen(r: random.Random) -> tuple[str, str]:
        return r.choice(texts), gold

    return gen


def _yn(name: str, split: str, choices: list[tuple[str, str]]) -> None:
    for q in YES_NO_QUESTIONS:
        family(name, split, q)(_pick(choices))


_yn("Y01_roman_yes", "train", [("haan", "yes"), ("han", "yes"), ("ji", "yes"), ("haan ji", "yes")])
_yn("Y02_urdu_yes", "test", [("ہاں", "yes"), ("جی ہاں", "yes"), ("جی", "yes"), ("ہاں جی", "yes")])
_yn("Y03_roman_no", "train", [("nahi", "no"), ("nahin", "no"), ("na", "no"), ("nahi ji", "no")])
_yn("Y04_urdu_no", "test", [("نہیں", "no"), ("جی نہیں", "no"), ("نہیں جی", "no")])
_yn("Y05_english", "train", [("yes", "yes"), ("yeah", "yes"), ("no", "no"), ("nope", "no"), ("yes please", "yes")])
_yn("Y06_compound", "test", [("ji haan", "yes"), ("jee haan", "yes"), ("ji nahi", "no"), ("jee nahin", "no")])
_yn("Y07a_emphatic", "train", [("bilkul", "yes"), ("bilkul nahi", "no"), ("zaroor", "yes"), ("haan bilkul", "yes")])
_yn("Y07b_emphatic_ur", "test", [("بالکل نہیں", "no"), ("جی بالکل", "yes"), ("not at all", "no"), ("of course", "yes")])
_yn("Y11a_contradiction", "train", [("haan... nahi", "abstain"), ("nahi haan", "abstain")])
_yn("Y11b_contradiction_ur", "test", [("ہاں... نہیں", "abstain"), ("yes no", "abstain")])
_yn("Y12a_unknown", "train", [("pata nahi", "unknown"), ("mujhe nahi maloom", "unknown"), ("nahi pata", "unknown")])
_yn("Y12b_unknown_other", "test", [("معلوم نہیں", "unknown"), ("I don't know", "unknown"), ("مجھے نہیں پتا", "unknown")])
_yn("Y13a_mismatch", "train", [("paanch", "abstain"), ("teen log", "abstain"), ("das hazaar", "abstain")])
_yn("Y13b_mismatch_ur", "test", [("پانچ", "abstain"), ("five people", "abstain")])
_yn("Y14a_hedge", "train", [("shayad", "abstain"), ("maybe", "abstain"), ("shayad haan", "abstain")])
_yn("Y14b_hedge_ur", "test", [("شاید", "abstain"), ("perhaps", "abstain")])
_yn("Y17a_noise", "train", [("umm haan ji", "yes"), ("acha... nahi", "no")])
_yn("Y17b_noise_other", "test", [("hmm, ji haan", "yes"), ("dekhiye, nahi", "no")])
_yn("Y18_typos", "test", [("haaan", "yes"), ("nahii", "no"), ("nhi", "no"), ("nai", "no"), ("haanji", "yes")])

for _q in YES_NO_QUESTIONS:
    _roman_yes, _urdu_yes, _en_yes = _TOPIC_YES[_q]
    _roman_no, _urdu_no, _en_no = _TOPIC_NO[_q]
    family("Y08a_statement_yes", "train", _q)(_pick_text(_roman_yes, "yes"))
    family("Y08b_statement_yes_other", "test", _q)(_pick_text(_urdu_yes + _en_yes, "yes"))
    family("Y09a_statement_no", "train", _q)(_pick_text(_roman_no, "no"))
    family("Y09b_statement_no_other", "test", _q)(_pick_text(_urdu_no + _en_no, "no"))
family("Y10_contradicts_statement", "test", "is_widow")(lambda r: (r.choice(["nahi, main bewa hoon", "نہیں، میں بیوہ ہوں"]), "abstain"))

family("C01_confirm_roman", "train", "confirm")(
    lambda r: r.choice([("haan sahi hai", "yes"), ("ji theek hai", "yes"), ("nahi galat hai", "no"), ("galat", "no")]))
family("C02_confirm_other", "test", "confirm")(
    lambda r: r.choice([("ٹھیک ہے", "yes"), ("جی ہاں، صحیح", "yes"), ("غلط ہے", "no"), ("that's right", "yes"), ("wrong", "no")]))

# --- name ----------------------------------------------------------------------------------------------

family("N01a_name_yes", "train", "full_name")(lambda r: (r.choice(["haan yahi mera naam hai", "ji haan", "yahi naam hai"]), "yes"))
family("N01b_name_yes_ur", "test", "full_name")(lambda r: (r.choice(["جی ہاں، یہی میرا نام ہے", "yes, that is my name"]), "yes"))
family("N02a_name_no", "train", "full_name")(lambda r: (r.choice(["nahi yeh mera naam nahi", "ji nahi"]), "no"))
family("N02b_name_no_ur", "test", "full_name")(lambda r: (r.choice(["یہ میرا نام نہیں", "no, that is not my name", "galat naam hai"]), "no"))
family("N03_name_other", "test", "full_name")(lambda r: (f"nahi, mera naam {r.choice(['Rubina', 'Shazia', 'Kulsoom'])} hai", "no"))

_NAMES = ["Zainab Bibi", "Rukhsana Parveen", "Aslam Khan"]
_OTHER_NAMES = ["Shazia Akhtar", "Kulsoom Begum", "Nargis Ali"]


# --- noise ---------------------------------------------------------------------------------------------

_VOWEL_SWAP = {"aa": "a", "ee": "i", "oo": "u", "a": "aa", "i": "ee", "u": "oo"}
_SAFE_FILLERS = ["umm", "acha", "dekhiye", "hmm", "uh", "wo"]


def _vocabulary() -> dict[str, str]:
    from app.modules.voice.parse import tables

    return {w: f"{m[0]}:{m[1]}" for w, m in tables().vocabulary.items()}


def _typo(word: str, rng: random.Random, vocab: dict[str, str]) -> str:
    """One realistic slip on a Roman word. Never turns it into another real word with a different meaning."""
    if not word.isascii() or not word.isalpha() or len(word) < 4:
        return word
    meaning = vocab.get(word)
    for _ in range(6):
        op = rng.choice(["drop", "double", "swap", "vowel", "h"])
        i = rng.randrange(1, len(word))
        if op == "drop":
            new = word[:i] + word[i + 1 :]
        elif op == "double":
            new = word[:i] + word[i] + word[i:]
        elif op == "swap" and i < len(word) - 1:
            new = word[:i] + word[i + 1] + word[i] + word[i + 2 :]
        elif op == "vowel":
            keys = [k for k in _VOWEL_SWAP if k in word]
            if not keys:
                continue
            k = rng.choice(keys)
            new = word.replace(k, _VOWEL_SWAP[k], 1)
        else:
            new = word.replace("h", "", 1) if "h" in word[1:] else word
        if new != word and (new not in vocab or vocab[new] == meaning):
            return new
    return word


def _noisy(text: str, rng: random.Random, vocab: dict[str, str]) -> str:
    words = text.split(" ")
    if rng.random() < 0.35:
        idx = [i for i, w in enumerate(words) if w.isascii() and w.isalpha() and len(w) >= 4]
        if idx:
            i = rng.choice(idx)
            words[i] = _typo(words[i], rng, vocab)
    if rng.random() < 0.20:
        words.insert(rng.randrange(0, len(words) + 1), rng.choice(_SAFE_FILLERS))
    out = " ".join(words)
    if rng.random() < 0.25:
        out = out.capitalize() if rng.random() < 0.5 else out.upper()
    if rng.random() < 0.25:
        out = out + rng.choice([".", "...", "!", " ?"])
    return out


def _speech_confidence(rng: random.Random) -> float | None:
    roll = rng.random()
    if roll < 0.12:
        return None
    if roll < 0.20:
        return round(rng.uniform(0.15, 0.44), 2)  # the engine itself was unsure
    return round(rng.uniform(0.55, 0.98), 2)


def build(per_family: int = 8, seed: int = SEED) -> list[Example]:
    rng = random.Random(seed)
    vocab = _vocabulary()
    out: list[Example] = []
    for name, split, question, gen in _FAMILIES:
        for _ in range(per_family):
            transcript, gold = gen(rng)
            out.append(Example(name, split, question, _noisy(transcript, rng, vocab), gold, _speech_confidence(rng)))
    # "mera naam ... hai" with no yes or no: compared with the name on the card.
    for fam, split, gold in (("N04a_name_said_match", "test", "yes"), ("N04b_name_said_other", "train", "no")):
        for _ in range(per_family):
            expected = rng.choice(_NAMES)
            said = expected if gold == "yes" else rng.choice(_OTHER_NAMES)
            out.append(Example(fam, split, "full_name", f"mera naam {said} hai", gold, _speech_confidence(rng), expected_name=expected))
    return out



# --- holdout -------------------------------------------------------------------------------------------
# Written after the floor was frozen and never used to tune anything: new phrasings, new words. Reported
# separately, so the test split is not the only evidence.

def _holdout_families() -> list[tuple[str, str, Gen]]:
    def approx_income(r: random.Random) -> tuple[str, str]:
        k = _k(r)
        near = any(abs(k * 1000 - b) <= 0.1 * b for b in (15_000, 30_000, 50_000))
        return f"\u062a\u0642\u0631\u06cc\u0628\u0627\u064b {urdu(k)} \u06c1\u0632\u0627\u0631", "abstain" if near else _band(k)

    def correction_en(r: random.Random) -> tuple[str, str]:
        a, b = _two(r, 2, 9)
        return f"{english(a)}, no sorry, {english(b)}", str(b)

    return [
        ("X01_ji_sentence", "household_size", lambda r: (f"ji hamare ghar mein {roman(n := _people(r, 3), r)} log rehte hain", str(n))),
        ("X02_urdu_afraad", "household_size", lambda r: (f"{urdu(n := _people(r, 3))} \u0627\u0641\u0631\u0627\u062f", str(n))),
        ("X03_members_en", "household_size", lambda r: (f"{english(n := _people(r, 2))} members in my family", str(n))),
        ("X04_correction_en", "household_size", correction_en),
        ("X05_hain_ji", "household_size", lambda r: (f"{roman(n := _people(r, 3), r)} hain ji", str(n))),
        ("X06_har_mahine", "income_band", lambda r: (f"har mahine {roman(k := _k(r), r)} hazaar rupay", _band(k))),
        ("X07_approx_urdu", "income_band", approx_income),
        ("X08_digits_thousand", "income_band", lambda r: (f"{(k := _k(r))} thousand", _band(k))),
        ("X09_emphatic_pair", "is_widow", lambda r: r.choice([("ji haan bilkul", "yes"), ("nahi ji bilkul nahi", "no")])),
        ("X10_urdu_polite", "has_disability", lambda r: r.choice([("\u062c\u06cc\u060c \u0628\u0627\u0644\u06a9\u0644", "yes"),
                                                                   ("\u0646\u06c1\u06cc\u06ba \u062c\u06cc", "no")])),
        ("X11_english_short", "receives_other_aid", lambda r: r.choice([("yes it is", "yes"), ("no it is not", "no"), ("yes we do", "yes")])),
        ("X12_unknown_new_words", "is_widow", _pick([("mujhe ilm nahi", "unknown"), ("I have no idea", "unknown"),
                                                      ("\u0645\u062c\u06be\u06d2 \u0639\u0644\u0645 \u0646\u06c1\u06cc\u06ba", "unknown")])),
        ("X13_two_values_en", "household_size", lambda r: (f"{english(a := _people(r, 2, 6))} or {english(a + 2)}", "abstain")),
        ("X14_daily_en", "income_band", lambda r: (f"{english(r.randint(3, 9))} hundred a day", "abstain")),
        ("X15_contradiction_en", "is_widow", lambda r: r.choice([("no, I am a widow", "abstain"), ("yes, I am not a widow", "abstain")])),
    ]


def build_holdout(per_family: int = 10, seed: int = SEED + 1) -> list[Example]:
    rng = random.Random(seed)
    vocab = _vocabulary()
    out: list[Example] = []
    for name, question, gen in _holdout_families():
        for _ in range(per_family):
            transcript, gold = gen(rng)
            out.append(Example(name, "holdout", question, _noisy(transcript, rng, vocab), gold, _speech_confidence(rng)))
    return out


def counts(examples: list[Example]) -> dict[str, int]:
    return {
        "examples": len(examples),
        "families": len({e.family + e.question_key for e in examples}),
        "train": sum(e.split == "train" for e in examples),
        "test": sum(e.split == "test" for e in examples),
    }


def check_split(examples: list[Example]) -> None:
    """No family appears in both splits (the point of splitting by family)."""
    seen: dict[str, str] = {}
    for e in examples:
        if seen.setdefault(e.family, e.split) != e.split:
            raise AssertionError(f"family {e.family} is in both splits")
    assert all(tokens(e.transcript) or e.gold == "abstain" for e in examples)
