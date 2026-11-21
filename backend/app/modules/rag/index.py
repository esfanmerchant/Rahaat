"""Local lexical retrieval: character n-gram TF-IDF (works for Urdu script and spelling variants) plus BM25.

No network and no new dependency. Two signals are combined into one score in [0, 1]:
- `char`: cosine similarity of character 2-4-gram TF-IDF vectors of the skeleton text;
- `coverage`: the share of the question's information (IDF-weighted words) that the passage contains.
  A word that appears nowhere in the corpus counts at the highest IDF, so off-topic questions score low.
BM25 orders passages with equal scores. Roman Urdu questions are expanded with Urdu-script and English
keywords (`expand`), because Urdu-script documents share no characters with Latin text.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from app.modules.guardrails.textnorm import collapse_repeats, skeleton, tokens

K1: Final = 1.5
B: Final = 0.75
CHAR_WEIGHT: Final = 0.5

_STOP_WORDS = (
    "a an the is are am was were be been to of in on at for with and or it its this that these those i me my we our you your "
    "do does did would should could there please tell about if so as by from any some much many "
    "what how when where which why who whom kaise kese kaisay kahan kyun kyon kaun kon "
    "hai hain ka ki ke ko se mein me main kya aur ya to bhi ho hota hoti hote hum ham mujhe mera meri mere aap ap apni apna "
    "ye yeh wo woh kar karna karte karein sakta sakti sakte raha rahi rahe tha thi the hy hun hoon hon jab tab koi kuch "
    "ہے ہیں کا کی کے کو سے میں کیا اور یا تو بھی ہو ہوتا ہوتی ہوتے ہم مجھے میرا میری میرے آپ اپنی اپنا یہ وہ کر کرنا کرتے "
    "کریں سکتا سکتی سکتے رہا رہی رہے تھا تھی تھے نے پر لیے کہ جو اس ان کوئی کچھ جب کیسے کہاں کیوں کون کسی"
)
STOP: Final = frozenset(tokens(_STOP_WORDS))

# Roman Urdu keyword -> words of the same meaning in Urdu script and in English.
_ROMAN: dict[str, tuple[str, str]] = {
    "paise": ("رقم پیسے", "payment money"), "paisay": ("رقم پیسے", "payment money"), "pese": ("رقم پیسے", "payment money"),
    "raqam": ("رقم", "payment money"), "rakam": ("رقم", "payment money"), "imdad": ("امدادی رقم", "relief payment"),
    "amdad": ("امدادی رقم", "relief payment"), "kitne": ("کتنی", "how much"), "kitni": ("کتنی", "how much"),
    "kitna": ("کتنی", "how much"), "milenge": ("ملتی دی جاتی", "get paid"), "milegi": ("ملتی دی جاتی", "get paid"),
    "milega": ("ملتی دی جاتی", "get paid"), "milti": ("ملتی", "get"), "milte": ("ملتی", "get"), "mil": ("مل", "get"),
    "darkhwast": ("درخواست", "application apply"), "darkhast": ("درخواست", "application apply"), "arzi": ("درخواست", "application"),
    "apply": ("درخواست", "apply"), "kaise": ("کیسے", "how"), "kese": ("کیسے", "how"), "kaisay": ("کیسے", "how"),
    "kab": ("کب دن دنوں وقت", "when days long"), "din": ("دن دنوں", "days"), "waqt": ("وقت", "time long"),
    "kaghaz": ("کاغذ کاغذات", "document paper"),
    "kaghzat": ("کاغذات", "documents"), "kagzat": ("کاغذات", "documents"), "kaagzat": ("کاغذات", "documents"),
    "dastavez": ("کاغذات", "documents"), "card": ("کارڈ", "card"), "tasveer": ("تصویر", "photo"), "tasvir": ("تصویر", "photo"),
    "photo": ("تصویر", "photo"), "appeal": ("اپیل", "appeal"), "apeel": ("اپیل", "appeal"), "apil": ("اپیل", "appeal"),
    "shikayat": ("شکایت", "complaint"), "faisla": ("فیصلہ", "decision"), "faisle": ("فیصلے", "decision"),
    "manzoor": ("منظور", "approved"), "namanzoor": ("منظور نہیں", "not approved"), "rad": ("رد", "rejects"),
    "bewa": ("بیوہ بیواؤں", "widows"), "bewah": ("بیواؤں", "widows"), "mazoor": ("معذور", "disability"),
    "mazoori": ("معذور", "disability"), "aamdani": ("آمدنی", "income"), "amdani": ("آمدنی", "income"), "tankhwah": ("تنخواہ آمدنی", "salary income"),
    "had": ("حد", "limit"), "hadd": ("حد", "limit"), "jaali": ("جعلی", "fake"), "jali": ("جعلی", "fake"), "nakli": ("جعلی", "fake"),
    "fake": ("جعلی", "fake"), "dhoka": ("جعلی", "fake"), "fraud": ("جعلی", "fake"), "paigham": ("پیغام", "message"),
    "message": ("پیغام", "message"), "sms": ("پیغام ایس ایم ایس", "message SMS"), "fees": ("فیس", "fee"), "fee": ("فیس", "fee"),
    "pin": ("پن کوڈ", "PIN"), "code": ("کوڈ", "code"), "otp": ("ایک بار کا کوڈ", "one-time code"), "link": ("لنک", "link"),
    "madadgar": ("مددگار", "helper"), "helper": ("مددگار", "helper"), "ijazat": ("اجازت", "permission"), "consent": ("اجازت", "permission"),
    "wapas": ("واپس", "taken back"), "internet": ("انٹرنیٹ", "internet"), "net": ("انٹرنیٹ", "internet"),
    "signal": ("انٹرنیٹ", "internet connection"), "tracking": ("ٹریکنگ کوڈ", "tracking code"), "track": ("ٹریکنگ", "tracking"),
    "status": ("حالت", "status"), "halat": ("حالت", "status"), "daftar": ("دفتر", "office"), "office": ("دفتر", "office"),
    "afsar": ("افسر", "officer"), "mangta": ("مانگتا", "ask"), "mangte": ("مانگتا", "ask"), "mangti": ("مانگتا", "ask"),
    "maangta": ("مانگتا", "ask"), "dein": ("دیں دینے", "apply"), "den": ("دیں دینے", "apply"), "dena": ("دیں دینے", "apply"),
    "rahat": ("راحت", "rahat"), "chahiye": ("ضرورت چاہیے", "need"), "chahiyen": ("ضرورت چاہیے", "need"), "tarjeeh": ("ترجیح", "priority"),
    "pehle": ("پہلے ترجیح", "first priority"),
    "shanakht": ("شناخت", "identity"), "shanakhti": ("شناختی", "identity ID"), "cnic": ("شناختی", "identity ID"),
    "record": ("ریکارڈ", "registry"), "awaz": ("بول", "speaking voice"), "bol": ("بول", "speaking"), "bolna": ("بول", "speaking"),
    "whatsapp": ("واٹس ایپ", "WhatsApp"), "wallet": ("والٹ", "wallet"), "account": ("اکاؤنٹ", "account"), "khata": ("اکاؤنٹ", "account"),
    "ghar": ("گھرانے گھر", "household home"), "gharana": ("گھرانہ", "household"), "khandan": ("خاندان گھرانہ", "family household"),
    "family": ("خاندان", "family"), "afraad": ("افراد", "people"), "galat": ("غلط", "wrong"), "ghalat": ("غلط", "wrong"),
    "durusti": ("درستی", "correction"), "kisko": ("کس کو", "who"),
    "mustahiq": ("رقم کس کو مل سکتی", "who can get payment"), "haqdar": ("رقم کس کو مل سکتی", "who can get payment"),
    "eligible": ("رقم کس کو مل سکتی", "who can get payment"), "eligibility": ("رقم کس کو مل سکتی", "who can get payment"),
    "qr": ("کیو آر", "QR"), "app": ("ایپ", "app"), "bheje": ("بھیجیں", "send"), "bhejna": ("بھیجیں", "send"),
    "registration": ("درخواست", "apply"), "sign": ("اندر", "sign"), "login": ("اندر", "sign in"), "zakat": ("امداد", "receiving payment"),
    "bisp": ("امداد", "receiving payment"), "mahana": ("ماہانہ", "monthly"), "mahine": ("ماہانہ", "month"), "30000": ("30,000", "30,000"),
}  # fmt: skip
ROMAN_EXPANSIONS: Final[dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    skeleton(k): (tuple(tokens(ur)), tuple(tokens(en))) for k, (ur, en) in _ROMAN.items()
}


_IRREGULAR: Final = {"goes": "go", "does": "do", "has": "have", "children": "child", "people": "person", "men": "man", "women": "woman"}


def stem(word: str) -> str:
    """A light English suffix stripper ("asks" -> "ask", "documents" -> "document"). Urdu words are left alone."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if not word.isascii() or not word.isalpha() or len(word) <= 3:
        return word
    for suffix, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not word.endswith("ss"):
            return word[: -len(suffix)] + keep
    return word


def content_terms(text: str) -> list[str]:
    words = (w if w.isdigit() else stem(w) for w in tokens(text))
    return [t for t in words if t not in STOP and len(t) > 1]


@dataclass(frozen=True, slots=True)
class Query:
    """What is searched: the text for character n-grams and the words for coverage and BM25."""

    char_text: str
    terms: frozenset[str]


def make_query(question: str, lang: str) -> Query:
    """Roman Urdu words are replaced by their meaning in the answer language ("kaghzat" -> "کاغذات")."""
    terms: set[str] = set()
    extra: list[str] = []
    for word in content_terms(question):
        hit = ROMAN_EXPANSIONS.get(word) or ROMAN_EXPANSIONS.get(collapse_repeats(word))
        if hit:
            meaning = hit[0] if lang == "ur" else hit[1]
            terms.update(t for t in meaning if t not in STOP)
            extra.extend(meaning)
        else:
            terms.add(word)
    return Query(char_text=" ".join([question, *extra]), terms=frozenset(terms))


@dataclass(frozen=True, slots=True)
class Passage:
    chunk_id: str
    document_id: str
    doc_key: str
    title: str
    version: int
    section_id: str
    heading: str
    lang: str
    sentences: tuple[str, ...]
    status: str = "approved"

    @property
    def text(self) -> str:
        return " ".join(self.sentences)


@dataclass(frozen=True, slots=True)
class Hit:
    passage: Passage
    score: float
    char: float
    coverage: float
    bm25: float


@dataclass(slots=True)
class LexicalIndex:
    passages: list[Passage]
    _vectorizer: Any = field(default=None, repr=False)
    _matrix: Any = field(default=None, repr=False)
    _terms: list[Counter[str]] = field(default_factory=list, repr=False)
    _title_terms: list[set[str]] = field(default_factory=list, repr=False)
    _idf: dict[str, float] = field(default_factory=dict, repr=False)
    _max_idf: float = 1.0
    _avgdl: float = 1.0
    vocabulary: frozenset[str] = frozenset()

    @classmethod
    def build(cls, passages: Sequence[Passage]) -> LexicalIndex:
        from sklearn.feature_extraction.text import TfidfVectorizer  # heavy: imported on first use only

        index = cls(passages=list(passages))
        if not index.passages:
            return index  # a department with no documents in this language: every search finds nothing
        texts = [skeleton(f"{p.heading}. {p.text}") for p in index.passages]
        index._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True, lowercase=False)
        index._matrix = index._vectorizer.fit_transform(texts)
        index._terms = [Counter(content_terms(f"{p.heading} {p.text}")) for p in index.passages]
        index._title_terms = [set(content_terms(p.title)) for p in index.passages]
        index.vocabulary = frozenset(t for terms in index._terms for t in terms) | frozenset(t for ts in index._title_terms for t in ts)
        n = max(len(index.passages), 1)
        df: Counter[str] = Counter(t for terms in index._terms for t in terms)
        index._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        index._max_idf = math.log(1 + (n + 0.5) / 0.5)
        index._avgdl = sum(sum(c.values()) for c in index._terms) / n if index._terms else 1.0
        return index

    def idf(self, term: str) -> float:
        return self._idf.get(term, self._max_idf)

    def _char_scores(self, text: str) -> Any:
        vec = self._vectorizer.transform([skeleton(text)])
        return (self._matrix @ vec.T).toarray().ravel()

    def coverage(self, query_terms: set[str], doc_terms: Counter[str] | set[str], title_terms: set[str] | None = None) -> float:
        """IDF-weighted share of the question's words found in the passage; a word found only in the title counts half."""
        total = sum(self.idf(t) for t in query_terms)
        if total <= 0:
            return 0.0
        found = 0.0
        for t in query_terms:
            if t in doc_terms:
                found += self.idf(t)
            elif title_terms and t in title_terms:
                found += 0.5 * self.idf(t)
        return found / total

    def _bm25(self, query_terms: set[str], terms: Counter[str]) -> float:
        length = sum(terms.values()) or 1
        score = 0.0
        for t in query_terms:
            tf = terms.get(t, 0)
            if tf:
                score += self.idf(t) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / self._avgdl))
        return score

    def search(self, query: Query, k: int = 3) -> list[Hit]:
        if not self.passages:
            return []
        terms = set(query.terms)
        char = self._char_scores(query.char_text)
        hits = []
        for i, passage in enumerate(self.passages):
            coverage = self.coverage(terms, self._terms[i], self._title_terms[i]) if terms else 0.0
            score = CHAR_WEIGHT * float(char[i]) + (1 - CHAR_WEIGHT) * coverage
            hits.append(Hit(passage, round(score, 4), round(float(char[i]), 4), round(coverage, 4), self._bm25(terms, self._terms[i])))
        hits.sort(key=lambda h: (h.score, h.bm25), reverse=True)
        return hits[:k]

    def sentence_scores(self, query: Query, passage: Passage) -> list[tuple[str, float]]:
        vec = self._vectorizer.transform([skeleton(query.char_text)])
        out = []
        for sentence in passage.sentences:
            svec = self._vectorizer.transform([skeleton(sentence)])
            char = float((svec @ vec.T).toarray().ravel()[0])
            cov = self.coverage(set(query.terms), set(content_terms(sentence))) if query.terms else 0.0
            out.append((sentence, round(CHAR_WEIGHT * char + (1 - CHAR_WEIGHT) * cov, 4)))
        return out
