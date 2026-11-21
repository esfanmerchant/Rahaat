"""Words the voice interpreter knows, in Urdu script, Roman Urdu and English.

Every entry is folded with the shared text skeleton when the tables are built, so "نہيں" (Arabic yeh) and
"نہیں" are the same word, and "chhe", "chay" and "che" all mean six. Ambiguous words are listed apart:
"do" is two in Roman Urdu but also the verb "give" ("paise do") and English "do"; "no" may be nine (nau)
or English no; "tera" is thirteen or "your"; "bara" is twelve or "big"; "saath" is sixty or "with".
"""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.guardrails.textnorm import tokens

# 0..99: (Urdu script, Roman spellings). Spellings follow how people type Roman Urdu, not a standard.
_NUMBERS: dict[int, tuple[tuple[str, ...], tuple[str, ...]]] = {
    0: (("صفر",), ("sifar", "sifr", "zero")),
    1: (("ایک",), ("aik", "aek", "eik", "ekk")),  # bare "ek" is context-dependent (see AMBIGUOUS)
    2: ((), ("doh", "dou")),  # "do" and "دو" are ambiguous
    3: (("تین",), ("teen", "tin", "tiin", "theen")),
    4: (("چار",), ("char", "chaar", "chhar", "chaarr")),
    5: (("پانچ",), ("panch", "paanch", "panj", "paanj", "paach", "pach", "paanc")),
    6: (("چھ", "چھے", "چھہ", "چھے"), ("chhe", "che", "chay", "chhay", "chhah", "cheh", "chha", "chah", "chae", "chheh", "chey", "chhey")),
    7: (("سات",), ("saat", "sat", "satt")),
    8: (("آٹھ", "اٹھ"), ("aath", "ath", "aat", "aatth", "aatt")),
    9: (("نو", "نَو"), ("nau", "nao", "nou", "naw", "nau")),
    10: (("دس",), ("das", "dus", "dass", "duss")),
    11: (("گیارہ", "گیارا"), ("gyarah", "gyara", "giyara", "gyaara", "gyarha", "igyara", "giara")),
    12: (("بارہ", "بارا"), ("barah", "baara", "baarah", "barha", "baarha")),  # "bara" is ambiguous
    13: (("تیرہ",), ("terah", "tehra", "terha")),  # "tera" is ambiguous
    14: (("چودہ", "چودا"), ("chaudah", "choudah", "chauda", "choda", "chodah", "chowda", "chaudha", "chodha")),
    15: (("پندرہ", "پندرا"), ("pandrah", "pandra", "pundra", "pandara", "pandhra", "pandarah")),
    16: (("سولہ", "سولا"), ("solah", "sola", "solaa", "solha")),
    17: (("سترہ", "سترا"), ("satrah", "satra", "sathra", "sattrah", "satara")),
    18: (("اٹھارہ", "اٹھارا"), ("atharah", "athara", "athaara", "attharah", "atthara", "athaarah")),
    19: (("انیس",), ("unnees", "unees", "unis", "unnis", "uniss", "unnes")),
    20: (("بیس",), ("bees", "bis", "beess", "bes")),
    21: (("اکیس",), ("ikkees", "ikees", "ikis", "ikkis")),
    22: (("بائیس",), ("baees", "bais", "baais", "baeis", "baaes")),
    23: (("تئیس", "تیئس"), ("teyees", "taees", "tayees", "teis", "tais")),
    24: (("چوبیس",), ("chaubees", "chobis", "chaubis", "chobees", "chowbees")),
    25: (("پچیس",), ("pachees", "pachis", "pacchis", "pachchis", "pachhees")),
    26: (("چھبیس",), ("chhabbees", "chabbis", "chhabees", "chabees", "chhabis")),
    27: (("ستائیس",), ("sattaees", "satais", "sataees", "sattais")),
    28: (("اٹھائیس",), ("athaees", "athais", "atthais", "athaais")),
    29: (("انتیس",), ("untees", "untis", "unattis")),
    30: (("تیس",), ("tees", "tis", "teess")),
    31: (("اکتیس",), ("iktees", "iktis", "ikattis")),
    32: (("بتیس",), ("battees", "batis", "battis", "batees")),
    33: (("تینتیس", "تینتس"), ("taintees", "tentis", "taintis", "tetees")),
    34: (("چونتیس",), ("chauntees", "chontis", "chautis", "chontees")),
    35: (("پینتیس",), ("paintees", "pentis", "paintis", "paetees")),
    36: (("چھتیس",), ("chhattees", "chattis", "chhattis", "chattees")),
    37: (("سینتیس",), ("saintees", "sentis", "saintis")),
    38: (("اڑتیس",), ("artees", "artis", "adtis")),
    39: (("انتالیس",), ("untalees", "untalis", "unchalis")),
    40: (("چالیس",), ("chalees", "chalis", "chaalis", "chaalees")),
    41: (("اکتالیس",), ("iktalees", "iktalis")),
    42: (("بیالیس",), ("bayalees", "biyalis", "byalis", "bayalis")),
    43: (("تینتالیس",), ("taintalees", "tentalis")),
    44: (("چوالیس",), ("chawalees", "chauvalis", "chawalis")),
    45: (("پینتالیس",), ("paintalees", "pentalis", "paintalis")),
    46: (("چھیالیس",), ("chhiyalees", "chiyalis", "chhiyalis")),
    47: (("سینتالیس",), ("saintalees", "sentalis")),
    48: (("اڑتالیس",), ("artalees", "artalis", "adtalis")),
    49: (("انچاس",), ("unchaas", "unchas", "unanchas")),
    50: (("پچاس",), ("pachaas", "pachas", "pachass", "pchas")),
    51: (("اکیاون",), ("ikyawan", "ikyavan")),
    52: (("باون",), ("bawan", "baawan")),
    53: (("ترپن",), ("tirpan", "tripan")),
    54: (("چون",), ("chawan", "chauwan")),
    55: (("پچپن",), ("pachpan",)),
    56: (("چھپن",), ("chhappan", "chappan")),
    57: (("ستاون",), ("sattawan", "satawan")),
    58: (("اٹھاون",), ("athawan", "athaawan")),
    59: (("انسٹھ",), ("unsath", "unsatth")),
    60: (("ساٹھ",), ()),  # Roman "saath"/"sath" is ambiguous (with)
    61: (("اکسٹھ",), ("iksath",)),
    62: (("باسٹھ",), ("basath",)),
    63: (("تریسٹھ",), ("tirsath",)),
    64: (("چونسٹھ",), ("chaunsath", "chonsath")),
    65: (("پینسٹھ",), ("painsath", "pensath")),
    66: (("چھیاسٹھ",), ("chhiyasath", "chiyasath")),
    67: (("سڑسٹھ",), ("sarsath",)),
    68: (("اڑسٹھ",), ("arsath",)),
    69: (("انہتر",), ("unhattar",)),
    70: (("ستر",), ("sattar", "satar")),
    71: (("اکہتر",), ("ikhattar",)),
    72: (("بہتر",), ("bahattar",)),
    73: (("تہتر",), ("tihattar",)),
    74: (("چوہتر",), ("chauhattar",)),
    75: (("پچھتر",), ("pachhattar", "pachattar")),
    76: (("چھہتر",), ("chhihattar",)),
    77: (("ستتر",), ("sathattar", "satattar")),
    78: (("اٹھتر",), ("athattar",)),
    79: (("اناسی",), ("unasi", "unaasi")),
    80: (("اسی",), ("assi", "asi")),
    81: (("اکاسی",), ("ikasi",)),
    82: (("بیاسی",), ("bayasi",)),
    83: (("تراسی",), ("tirasi",)),
    84: (("چوراسی",), ("chaurasi",)),
    85: (("پچاسی",), ("pachasi",)),
    86: (("چھیاسی",), ("chhiyasi",)),
    87: (("ستاسی",), ("sattasi",)),
    88: (("اٹھاسی",), ("athasi",)),
    89: (("نواسی",), ("nawasi",)),
    90: (("نوے",), ("nabbe", "nabbay", "navve")),
    91: (("اکانوے",), ("ikanve",)),
    92: (("بانوے",), ("banve",)),
    93: (("ترانوے",), ("tiranve",)),
    94: (("چورانوے",), ("chauranve",)),
    95: (("پچانوے",), ("pachanve",)),
    96: (("چھیانوے",), ("chhiyanve",)),
    97: (("ستانوے",), ("sattanve",)),
    98: (("اٹھانوے",), ("athanve",)),
    99: (("ننانوے",), ("ninnanve", "nanyanve")),
}

ENGLISH_UNITS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}  # fmt: skip
ENGLISH_TENS: dict[str, int] = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                                "eighty": 80, "ninety": 90}  # fmt: skip

# Words that are numbers only in the right context. Value, and why it is ambiguous.
AMBIGUOUS: dict[str, int] = {"do": 2, "دو": 2, "no": 9, "tera": 13, "bara": 12, "ek": 1, "ik": 1, "saath": 60, "sath": 60, "so": 100}

MULTIPLIERS_ENTRIES: dict[int, tuple[str, ...]] = {
    100: ("sau", "so", "hundred", "سو"),
    1000: ("hazaar", "hazar", "hajar", "hazzar", "hazaar", "hazār", "hajaar", "hazaron", "thousand", "k", "ہزار"),
    100_000: ("lakh", "lac", "laakh", "lakhs", "lacs", "لاکھ"),
    10_000_000: ("crore", "karor", "کروڑ"),
}
# dedh = one and a half, dhai = two and a half; sade adds a half, sawa a quarter, paune takes a quarter off.
FRACTION_WORDS: dict[str, float] = {"dedh": 1.5, "derh": 1.5, "ڈیڑھ": 1.5, "dhai": 2.5, "dhaai": 2.5, "adhai": 2.5, "اڑھائی": 2.5,
                                    "ڈھائی": 2.5}  # fmt: skip
FRACTION_PREFIX: dict[str, float] = {"sade": 0.5, "saade": 0.5, "saarhe": 0.5, "sarhe": 0.5, "ساڑھے": 0.5, "sawa": 0.25, "سوا": 0.25,
                                     "paune": -0.25, "پونے": -0.25}  # fmt: skip


def _single(entries: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for entry in entries:
        parts = tokens(entry)
        if len(parts) == 1:
            out.add(parts[0])
    return out


def _phrases(entries: Iterable[str]) -> list[tuple[str, ...]]:
    return [tuple(tokens(e)) for e in entries if tokens(e)]


def number_words() -> dict[str, int]:
    out: dict[str, int] = {}
    for value, (urdu, roman) in _NUMBERS.items():
        for word in _single((*urdu, *roman)):
            out[word] = value
    for word, value in {**ENGLISH_UNITS, **ENGLISH_TENS}.items():
        out[word] = value
    for word in AMBIGUOUS:
        out.pop(tokens(word)[0], None)
    return out


def multiplier_words() -> dict[str, int]:
    out: dict[str, int] = {}
    for value, entries in MULTIPLIERS_ENTRIES.items():
        for word in _single(entries):
            out[word] = value
    out.pop("so", None)  # English "so"; a multiplier only right after a number (handled in the parser)
    return out


# Phrase tables. Longer phrases win over their parts ("pata nahi" is "I don't know", not "no").
UNKNOWN = _phrases([
    "pata nahi", "pata nahin", "pata nai", "pta nahi", "pta nai", "nahi pata", "nahin pata", "nai pata", "nhi pata",
    "maloom nahi", "malum nahi", "maaloom nahi", "maloom nahin", "nahi maloom", "nahi malum", "nahin maloom",
    "mujhe nahi pata", "mujhe nahi maloom", "mujhe pata nahi", "mujhe maloom nahi", "kya pata", "koi idea nahi", "idea nahi",
    "i don't know", "i dont know", "i do not know", "don't know", "dont know", "do not know", "not sure", "no idea",
    "i am not sure", "i'm not sure", "im not sure", "not known", "unknown", "can't say", "cannot say", "keh nahi sakti",
    "keh nahi sakta", "ilm nahi", "mujhe ilm nahi", "koi ilm nahi", "khabar nahi", "mujhe khabar nahi", "no clue",
    "i have no idea", "علم نہیں", "مجھے علم نہیں", "کوئی علم نہیں", "خبر نہیں", "مجھے خبر نہیں", "پتہ نہیں", "پتا نہیں", "معلوم نہیں",
    "نہیں معلوم", "نہیں پتا", "نہیں پتہ", "مجھے نہیں پتا",
    "مجھے نہیں پتہ", "مجھے معلوم نہیں", "مجھے نہیں معلوم", "کیا پتا", "کیا پتہ", "کہہ نہیں سکتی", "کہہ نہیں سکتا",
])  # fmt: skip
YES = _phrases([
    "haan", "han", "haa", "haanji", "hanji", "haan ji", "han ji", "ji haan", "ji han", "jee haan", "jee han", "ji", "jee", "jii",
    "g", "bilkul", "zaroor", "zarur", "jee bilkul", "ji bilkul", "haan bilkul", "yes", "yeah", "yea", "yep", "yup", "sure",
    "of course", "absolutely", "yes please", "yes sir", "yes madam",
    "ہاں", "جی", "جی ہاں", "ہاں جی", "بالکل", "جی بالکل", "ہاں بالکل", "ضرور", "جی ضرور",
])  # fmt: skip
NO = _phrases([
    "nahi", "nahin", "nai", "nhi", "nahee", "nahiin", "na", "naa", "no", "nope", "nah", "never", "not at all",
    "bilkul nahi", "bilkul nahin", "ji nahi", "jee nahi", "ji nahin", "nahi ji", "nahin ji", "nai ji", "no no", "nahi nahi",
    "koi nahi", "koi nahin", "kabhi nahi", "no one", "nobody", "none", "no sir", "no madam",
    "نہیں", "نہ", "نا", "جی نہیں", "نہیں جی", "بالکل نہیں", "کوئی نہیں", "کبھی نہیں", "نہیں نہیں",
])  # fmt: skip
# "ji" and "jee" are a polite particle next to an answer: every pairing is listed so it never reads as yes.
_JI = ("ji", "jee", "jii", "g")
YES += _phrases([f"{j} {h}" for j in _JI for h in ("haan", "han", "haa")] + [f"{h} {j}" for j in _JI for h in ("haan", "han", "haa")])
NO += _phrases([f"{j} {n}" for j in _JI for n in ("nahi", "nahin", "nai", "nhi", "na", "naa")]
               + [f"{n} {j}" for j in _JI for n in ("nahi", "nahin", "nai", "nhi", "na", "naa")])
CONFIRM_YES = _phrases(["sahi", "sahih", "theek", "thik", "theek hai", "thik hai", "durust", "correct", "right", "that's right",
                        "thats right", "ok", "okay", "صحیح", "ٹھیک", "ٹھیک ہے", "درست"])  # fmt: skip
CONFIRM_NO = _phrases(["galat", "ghalat", "wrong", "incorrect", "not right", "theek nahi", "sahi nahi", "غلط", "ٹھیک نہیں", "صحیح نہیں"])
NEGATORS = _phrases(["nahi", "nahin", "nai", "nhi", "nahee", "na", "naa", "not", "no", "never", "نہیں", "نہ", "نا"])
CORRECTION = _phrases([
    "matlab", "mtlb", "yaani", "yani", "i mean", "i meant", "sorry", "galti se", "maaf", "maaf kijiye", "actually", "rather",
    "nahi nahi", "no no", "nahin nahin", "دراصل", "میرا مطلب", "مطلب", "معاف کیجیے", "معاف کیجئے", "نہیں نہیں", "یعنی",
])  # fmt: skip
ALTERNATIVE = _phrases(["ya", "yaa", "or", "or maybe", "یا"])
CONJUNCTION = _phrases(["aur", "and", "plus", "اور"])
BESIDES = _phrases(["ilawa", "alawa", "siwa", "siwaye", "besides", "except", "apart from", "other than", "plus me", "علاوہ", "سوا", "سوائے"])
APPROX = _phrases(["taqreeban", "takreeban", "taqriban", "lagbhag", "lag bhag", "about", "around", "approximately", "roughly",
                   "almost", "nearly", "kareeb", "qareeb", "تقریباً", "تقریبا", "لگ بھگ", "قریب"])  # fmt: skip
HEDGE = _phrases(["shayad", "shaayad", "shaid", "maybe", "perhaps", "probably", "possibly", "ho sakta", "ho sakta hai",
                  "شاید", "ہو سکتا ہے", "ہوسکتا"])  # fmt: skip
LESS = _phrases(["kam", "less", "less than", "under", "below", "se kam", "کم", "سے کم"])
MORE = _phrases(["zyada", "ziada", "zaida", "ziyada", "more", "more than", "over", "above", "se zyada", "kam se kam", "at least",
                 "زیادہ", "سے زیادہ", "کم از کم"])  # fmt: skip
RANGE_LINK = _phrases(["se", "to", "till", "until", "tak", "سے", "تک"])
PERIOD_OTHER = _phrases([
    "roz", "rozana", "roza", "din", "dihari", "dihaari", "daily", "per day", "a day", "every day", "hafta", "hafte", "haftay",
    "weekly", "week", "per week", "saal", "salana", "yearly", "annual", "annually", "year", "per year",
    "روز", "روزانہ", "دن", "دیہاڑی", "ہفتہ", "ہفتے", "سال", "سالانہ",
])  # fmt: skip
PERIOD_MONTH = _phrases(["mahina", "mahine", "maheena", "mahinay", "mahenay", "month", "monthly", "per month", "a month",
                         "مہینہ", "مہینے", "ماہانہ", "ماہ"])  # fmt: skip
PEOPLE_UNITS = _phrases([
    "log", "loag", "logg", "afraad", "afrad", "fard", "bande", "banday", "bandey", "admi", "aadmi", "insaan", "insan",
    "members", "member", "people", "persons", "person", "family members", "jan", "jaan",
    "لوگ", "افراد", "فرد", "بندے", "آدمی", "انسان", "ممبر", "جان",
])  # fmt: skip
CHILD_ADULT = _phrases(["bachay", "bache", "bachche", "bacche", "bachon", "children", "kids", "child", "baray", "bare", "bade",
                        "adults", "بچے", "بچوں", "بڑے"])  # fmt: skip
CURRENCY = _phrases(["rupay", "rupaye", "rupey", "rupee", "rupees", "rupiya", "rs", "pkr", "روپے", "روپیہ", "روپیے"])
ZERO_INCOME = _phrases([
    "kuch nahi", "kuchh nahi", "kuch nahin", "kuch bhi nahi", "kuch nai", "koi aamdani nahi", "koi amdani nahi", "koi income nahi",
    "aamdani nahi", "amdani nahi", "nothing", "no income", "zero income", "no money", "nothing comes",
    "کچھ نہیں", "کچھ بھی نہیں", "کوئی آمدنی نہیں", "آمدنی نہیں",
])  # fmt: skip
ALONE = _phrases(["akela", "akeli", "akele", "alone", "by myself", "only me", "just me", "sirf main", "main akeli", "main akela",
                  "اکیلا", "اکیلی", "اکیلے", "صرف میں"])  # fmt: skip
FILLERS = _phrases([
    "umm", "um", "uh", "uhh", "hmm", "hm", "er", "err", "erm", "acha", "achha", "accha", "achaa", "dekhiye", "dekhen", "suniye",
    "wo", "woh", "yaar", "bhai", "baji", "sahib", "sahab", "madam", "sir", "beta", "behen", "beti", "ammi", "abbu",
    "ek minute", "ek second", "ek min", "ek pal", "aik minute", "one minute", "one second", "wait", "ruko", "rukiye",
    "noise", "inaudible", "unclear", "ok so", "so", "well", "like", "basically",
    "اچھا", "دیکھیے", "سنیے", "وہ", "یار", "بھائی", "باجی", "صاحب", "ایک منٹ", "رکیے",
])  # fmt: skip
NEUTRAL = _phrases([
    "main", "mai", "mein", "me", "mien", "hum", "ham", "mujhe", "mujhay", "hamein", "humein", "hame", "hume", "humare", "hamare", "hamara",
    "humara", "hamari", "humari", "mera", "meri",
    "mere", "meray", "ghar", "gher", "hain", "hai", "hen", "hy", "he", "hoon", "hun", "ho", "rehte", "rehtay", "rahte", "rehti",
    "rehta", "total", "kul", "sirf", "bas", "only", "just", "we", "are", "there", "is", "in", "my", "our", "the", "a", "an", "of",
    "house", "home", "family", "ke", "ki", "ka", "ko", "ne", "to", "bhi", "sab", "sare", "saare", "tha", "thay", "thi", "aate",
    "aata", "aati", "ate", "milte", "milta", "milti", "kamate", "kamati", "kamai", "income", "aamdani", "amdani", "tankhwah",
    "salary", "it", "its", "it's", "i", "am", "us", "of us", "live", "living", "lives", "here", "comes", "come", "get", "gets",
    "earn", "earns", "jee", "family mein", "ghar mein", "ghar walay", "ghar wale", "walay", "wale", "kitne", "kitna", "that",
    "this", "yeh", "ye", "woh", "per", "for", "every", "har", "koi", "kisi", "kis", "kuch", "shohar", "husband", "biwi", "wife",
    "maa", "baap", "behan", "bacha", "son", "daughter", "mother", "father", "unka", "unki", "uska", "uski", "hamesha", "abhi",
    "se", "mil", "you", "someone", "anyone", "with",
    "میں", "ہم", "ہمارے", "ہمارا", "ہماری", "میرا", "میری", "میرے", "گھر", "ہیں", "ہے", "ہوں", "رہتے", "رہتی", "کل", "صرف", "کوئی", "کسی",
    "مجھے", "ہمیں", "شوہر", "بیٹا", "بیٹی",
    "بس", "کے", "کی", "کا", "کو", "نے", "تو", "بھی", "سب", "آتے", "آتی", "آتا", "ملتے", "ملتی", "ملتا", "کماتے", "آمدنی",
    "تنخواہ", "والے", "یہ", "ہر", "تھے", "تھی",
])  # fmt: skip

# Question-specific statements: a topic word plus no negation means yes ("main bewa hoon"), with negation no.
TOPIC_WORDS: dict[str, list[tuple[str, ...]]] = {
    "is_widow": _phrases(["bewa", "bewah", "beva", "widow", "widowed", "shohar fot", "husband died", "husband passed away",
                          "بیوہ", "شوہر فوت", "شوہر کا انتقال"]),  # fmt: skip
    "has_disability": _phrases(["mazoor", "mazur", "maazoor", "mazoori", "disabled", "disability", "handicapped", "maazoori",
                                "معذور", "معذوری"]),  # fmt: skip
    "receives_other_aid": _phrases(["bisp", "benazir", "ehsaas", "ehsas", "zakat", "pension", "imdad", "amdad", "madad", "aid",
                                    "support", "بینظیر", "احساس", "زکوٰۃ", "زکوۃ", "پنشن", "امداد", "مدد"]),  # fmt: skip
    "full_name": _phrases(["naam", "nam", "name", "نام"]),
}
NAME_THIS = _phrases(["yahi", "yehi", "yeh", "ye", "this", "that", "یہی", "یہ"])

# Words before "do"/"دو" that make it the verb "give" ("kar do", "bata do"), not the number two.
VERB_STEMS = frozenset(tokens(" ".join([
    "kar", "de", "bata", "likh", "sun", "dekh", "bol", "rakh", "chhod", "chhor", "le", "bhej", "samjha", "dikha", "laga", "utha",
    "bula", "dal", "daal", "paise", "paisay", "raqam", "madad", "jawab", "bana", "batla", "kr", "krdo", "chala",
    "کر", "دے", "بتا", "لکھ", "سن", "دیکھ", "بول", "رکھ", "چھوڑ", "لے", "بھیج", "سمجھا", "دکھا", "لگا", "اٹھا", "بلا", "ڈال", "پیسے",
    "بنا",
])))  # fmt: skip
