"""Compose an answer from retrieved text only. Pure: the caller gives the index and stores the result.

1. The input guard checks the question first; a blocked question is refused before any search.
2. Retrieval finds the best section in the asker's language. Below the threshold: "I am not sure, ask a person".
3. The answer is the section's own sentences (at most three) that are relevant to the question, copied word
   for word, each with a citation to the document, version and section.
4. The output guard checks every sentence against its cited chunk and for promises; any finding refuses.
A question about one's own eligibility or payment always gets the notice that only an officer decides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from app.modules.guardrails.concepts import Rule as ConceptRule
from app.modules.guardrails.concepts import concept, match
from app.modules.guardrails.input_guard import ACTION_CODES, check_input
from app.modules.guardrails.output_guard import CitedSentence, KnownChunk, check_answer
from app.modules.guardrails.textnorm import script_of, skeleton, tokens
from app.modules.guardrails.verdict import GuardVerdict
from app.modules.rag.index import ROMAN_EXPANSIONS, STOP, LexicalIndex, Passage, make_query, stem

ANSWER_VERSION: Final = "rag-lexical-v1"
# Below this retrieval score the assistant refuses. Chosen on the dev questions by cost (a wrong answer costs 5,
# a needless refusal 1, ties to the safer threshold); the test questions then had no wrong answer (evaluate.py).
THRESHOLD: Final = 0.34
SENTENCE_RELATIVE: Final = 0.55  # a sentence must score at least this share of the best sentence's score
MAX_SENTENCES: Final = 3
DECISION_SECTIONS: Final = frozenset({"who-can-get", "income-limit", "priority", "payment", "decision", "outcome"})

MESSAGES: Final[dict[str, dict[str, str]]] = {
    "ask_not_sure": {"en": "I am not sure. Please ask a person.", "ur": "مجھے یقین نہیں ہے۔ کسی شخص سے پوچھیں۔"},
    "ask_cannot_act": {
        "en": "I can only answer questions about the Rahat rules. A person decides on applications.",
        "ur": "میں صرف راحت کے قواعد کے بارے میں سوالوں کے جواب دے سکتا ہوں۔ درخواستوں کا فیصلہ ایک شخص کرتا ہے۔",
    },
    "ask_no_promise": {
        "en": "Only an officer can decide on an application. This answer is not a promise of payment.",
        "ur": "درخواست کا فیصلہ صرف ایک افسر کر سکتا ہے۔ یہ جواب رقم کا وعدہ نہیں ہے۔",
    },
}

_PERSONAL = {
    c.name: c
    for c in (
        concept("ME", ["i", "me", "my", "am i", "mujhe", "mujh", "main", "mai", "meri", "mera", "hamein", "humein", "hum",
                       "مجھے", "میں", "میری", "میرا", "ہمیں", "ہم"]),
        concept("GET_OR_QUALIFY", ["eligible", "qualify", "get", "receive", "approved", "milenge", "milega", "milegi", "mil",
                                   "mustahiq", "haqdar", "manzoor", "ملے", "ملیں", "ملے گی", "ملیں گے", "اہل", "مستحق", "منظور"]),
    )
}  # fmt: skip
_PERSONAL_RULES = (ConceptRule("personal_outcome", ("ME", "GET_OR_QUALIFY"), window=6),)

# "for a passport", "پاسپورٹ کے لیے", "licence ke liye": the question names its own subject.
_FOR_SUBJECT = re.compile(r"\bfor\s+(?:a|an|the|my|our|his|her|their|this|that)?\s*([a-z]+)")
_KE_LIYE = ("\u06a9\u06cc \u0644\u06cc\u06cc", "ke liye", "ke liay", "ke lie", "k liye")


def foreign_subject(question: str, index: LexicalIndex) -> str | None:
    """The subject the question is about, when the rules never mention it; else None."""
    folded = skeleton(question)
    candidates = [m.group(1) for m in _FOR_SUBJECT.finditer(folded)]
    words = tokens(folded)
    for marker in _KE_LIYE:
        parts = tokens(marker)
        for i in range(1, len(words) - len(parts) + 1):
            if tuple(words[i : i + len(parts)]) == tuple(parts):
                candidates.append(words[i - 1])
    for word in candidates:
        term = stem(word)
        if term in STOP or term in index.vocabulary or word in ROMAN_EXPANSIONS or len(term) < 3:
            continue
        return word
    return None


@dataclass(slots=True)
class AnswerSentence:
    text: str
    passage: Passage


@dataclass(slots=True)
class Answer:
    answered: bool
    lang: str
    # answered | low_retrieval | no_relevant_sentence | outside_the_rules | guardrail_blocked | output_blocked | empty_question
    reason: str
    sentences: list[AnswerSentence] = field(default_factory=list)
    top_score: float = 0.0
    second_score: float = 0.0
    top_section: str | None = None
    personal: bool = False
    message_key: str | None = None  # refusal message, or the no-promise notice when answered
    input_verdict: GuardVerdict | None = None
    output_verdict: GuardVerdict | None = None

    @property
    def passages(self) -> list[Passage]:
        seen: dict[str, Passage] = {}
        for s in self.sentences:
            seen.setdefault(s.passage.chunk_id, s.passage)
        return list(seen.values())


def answer_lang(question: str, requested: str | None) -> str:
    """Urdu script is answered in Urdu; otherwise the asker's language (Roman Urdu speakers choose)."""
    if script_of(question) == "ur":
        return "ur"
    return requested if requested in ("en", "ur") else "en"


def is_personal(question: str) -> bool:
    return bool(match(question, _PERSONAL, _PERSONAL_RULES))


def compose(indexes: dict[str, LexicalIndex], question: str, requested_lang: str | None, *,
            threshold: float = THRESHOLD) -> Answer:  # fmt: skip
    lang = answer_lang(question, requested_lang)
    verdict = check_input(question, "question")
    text = verdict.redacted_text or question  # personal data is masked before anything is searched
    if not text.strip():
        return Answer(False, lang, "empty_question", message_key="ask_not_sure", input_verdict=verdict)
    if verdict.blocked:
        key = "ask_cannot_act" if set(verdict.codes) & set(ACTION_CODES) and not _is_attack(verdict) else "ask_not_sure"
        return Answer(False, lang, "guardrail_blocked", message_key=key, input_verdict=verdict)
    personal = is_personal(text)
    index = indexes.get(lang)
    if index is None or not index.passages:
        return Answer(False, lang, "low_retrieval", message_key="ask_not_sure", input_verdict=verdict, personal=personal)
    outside = foreign_subject(text, index)
    if outside is not None:
        return Answer(False, lang, "outside_the_rules", message_key="ask_not_sure", input_verdict=verdict, personal=personal)
    query = make_query(text, lang)
    hits = index.search(query, k=3)
    top = hits[0] if hits else None
    second = hits[1].score if len(hits) > 1 else 0.0
    result = Answer(False, lang, "low_retrieval", top_score=top.score if top else 0.0, second_score=second,
                    top_section=top.passage.section_id if top else None, personal=personal, message_key="ask_not_sure",
                    input_verdict=verdict)  # fmt: skip
    if top is None or top.score < threshold:
        return result
    scored = index.sentence_scores(query, top.passage)
    best = max(score for _, score in scored)
    if best <= 0:
        result.reason = "no_relevant_sentence"
        return result
    chosen = [s for s, score in scored if score >= SENTENCE_RELATIVE * best][:MAX_SENTENCES]
    sentences = [AnswerSentence(s, top.passage) for s in chosen]
    known = {top.passage.chunk_id: KnownChunk(top.passage.chunk_id, top.passage.document_id, top.passage.version,
                                              top.passage.text, top.passage.status)}  # fmt: skip
    out = check_answer([CitedSentence(s.text, s.passage.chunk_id, s.passage.document_id, s.passage.version) for s in sentences], known)
    result.output_verdict = out
    if out.blocked:
        result.reason = "output_blocked"
        return result
    result.answered = True
    result.reason = "answered"
    result.sentences = sentences
    result.message_key = "ask_no_promise" if (personal or top.passage.section_id in DECISION_SECTIONS) else None
    return result


def _is_attack(verdict: GuardVerdict) -> bool:
    """An attack on the system gets the plain "not sure"; a plain request to act gets "I cannot do that"."""
    return bool({"instruction_override", "role_hijack", "prompt_extraction", "markup_injection", "jailbreak_terms",
                 "payment_redirect", "data_exfiltration"} & set(verdict.codes))  # fmt: skip
