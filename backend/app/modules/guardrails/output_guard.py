"""Output guard: nothing reaches a person that promises an outcome or cites a source that does not exist.

Checks, in order:
1. Every cited chunk exists, is from an approved document, and has the cited version.
2. Every sentence appears word for word in the chunk it cites (groundedness).
3. No sentence promises eligibility or a payment, in English, Urdu or Roman Urdu ("you will get Rs 12,000",
   "آپ کو رقم ملے گی", "aap eligible hain"). Only an officer or the rules decide; an answer never does.
4. No personal data in the answer.

Any finding blocks the answer; the caller then refuses ("I am not sure, ask a person").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.modules.guardrails import pii
from app.modules.guardrails.concepts import Concept, Rule, concept, match
from app.modules.guardrails.verdict import GuardVerdict, text_hash

MODEL_VERSION: Final = "guardrails-output-v1"
MAX_SENTENCES: Final = 3

_C: dict[str, Concept] = {
    c.name: c
    for c in (
        concept("YOU", ["you", "your", "yours", "aap", "ap", "aapko", "apko", "aapka", "aapki", "tum", "tumhe", "tumko",
                        "tumhara", "tumhari", "آپ", "آپکو", "آپکا", "آپکی", "تم", "تمہیں", "تمہارا", "تمہاری"]),
        concept("WILL_GET", [
            "will get", "will receive", "will be paid", "will be given", "will be sent", "are going to get", "is going to get",
            "will qualify", "will be approved", "gets", "get", "receive", "receives",
            "milenge", "milega", "milegi", "mil jayenge", "mil jayega", "mil jaye gi", "mil jaegi", "mil jaenge", "diye jayenge",
            "ملیں گے", "ملے گا", "ملے گی", "مل جائیں گے", "مل جائے گی", "مل جائے گا", "دیے جائیں گے", "دی جائے گی",
        ]),
        concept("ELIGIBLE_STATE", [
            "eligible", "qualify", "qualifies", "qualified", "approved", "entitled", "accepted", "selected",
            "mustahiq", "mustahaq", "ahl", "ahil", "haqdar", "haqdaar", "manzoor",
            "اہل", "مستحق", "حقدار", "منظور",
        ]),
        concept("GUARANTEE", [
            "guarantee", "guaranteed", "guarantees", "definitely", "certainly", "surely", "sure to", "promise", "promised",
            "promises", "100%", "zaroor", "zarur", "yaqeenan", "yakeenan", "pakka", "pakki",
            "ضرور", "یقیناً", "یقینا", "یقینی", "پکا", "پکی", "وعدہ",
        ]),
        concept("MONEY", [
            "money", "payment", "paid", "rs", "rupees", "rupee", "rupay", "rupaye", "rupey", "pkr", "12000", "12,000", "amount", "cash", "funds",
            "raqam", "rakam", "paise", "paisay", "imdad", "amdad", "رقم", "پیسے", "روپے", "امداد",
        ]),
        concept("NEGATION", ["not", "never", "no", "cannot", "nahi", "nahin", "na", "kabhi", "نہیں", "نہ", "کبھی"]),
    )
}  # fmt: skip

_RULES: tuple[Rule, ...] = (
    Rule("payment_promise", ("YOU", "WILL_GET", "MONEY"), window=8),
    Rule("eligibility_claim", ("YOU", "ELIGIBLE_STATE"), window=5),
    Rule("guarantee", ("GUARANTEE",), window=6, any_of=(("MONEY", "ELIGIBLE_STATE", "WILL_GET"),), unless=("NEGATION",)),
)


@dataclass(frozen=True, slots=True)
class CitedSentence:
    text: str
    chunk_id: str
    document_id: str
    version: int


@dataclass(frozen=True, slots=True)
class KnownChunk:
    chunk_id: str
    document_id: str
    version: int
    text: str
    status: str = "approved"


def _flat(text: str) -> str:
    return " ".join(text.split())


def promise_codes(text: str) -> list[str]:
    """Promise and personal-determination findings in one piece of text."""
    return match(text, _C, _RULES)


def check_answer(sentences: Sequence[CitedSentence], known: Mapping[str, KnownChunk]) -> GuardVerdict:
    """The output verdict for an extractive answer. Pure; the caller stores it in the audit log."""
    codes: list[str] = []
    if len(sentences) > MAX_SENTENCES:
        codes.append("too_many_sentences")
    for sentence in sentences:
        chunk = known.get(sentence.chunk_id)
        if chunk is None:
            codes.append("invented_citation")
            continue
        if chunk.document_id != sentence.document_id or chunk.version != sentence.version:
            codes.append("citation_version_mismatch")
        if chunk.status != "approved":
            codes.append("citation_not_approved")
        if not sentence.text.strip() or _flat(sentence.text) not in _flat(chunk.text):
            codes.append("ungrounded_sentence")
        codes.extend(promise_codes(sentence.text))
        if pii.mask(sentence.text).found:
            codes.append("pii_in_answer")
    codes = list(dict.fromkeys(codes))
    joined = " ".join(s.text for s in sentences)
    return GuardVerdict(guard="output", surface="answer", verdict="block" if codes else "allow", codes=codes,
                        text_hash=text_hash(joined), model_version=MODEL_VERSION)  # fmt: skip
