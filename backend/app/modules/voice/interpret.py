"""Interpret one spoken answer against the type its question expects. Pure: no database, no network.

The interpreter proposes an answer and scores how sure it is. It abstains (route `ask_more`) when:
- the speech engine itself was unsure, or the transcript is empty;
- the text tries to act as an instruction (input guard, `transcript` surface);
- it heard two different answers ("paanch ya chhe", "haan... nahi"), or an answer of another type
  ("haan" to "how many people?");
- a number is out of range, is said relative to someone ("mere ilawa chaar"), is negated with no
  replacement ("paanch nahi"), or an income is not monthly ("roz ke 500") or has no unit ("pachees");
- the score is below the floor.

"I don't know" is a valid answer: the form value stays unknown (None). Corrections keep the last value
("chaar nahi, paanch" is five; "nahi, paanch" is five). Every accepted answer must still be read back.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Final, Literal

from app.contracts.common import IncomeBand, Route
from app.modules.guardrails.input_guard import check_input
from app.modules.guardrails.textnorm import skeleton, tokens
from app.modules.voice import lexicon as L
from app.modules.voice.parse import Item, Mention, Parsed, numbers, parse

QuestionKey = Literal["household_size", "income_band", "is_widow", "has_disability", "receives_other_aid", "full_name", "confirm"]
Expected = Literal["yes_no", "number", "income_band", "name_confirm"]

EXPECTED_FOR: Final[dict[str, str]] = {
    "household_size": "number",
    "income_band": "income_band",
    "is_widow": "yes_no",
    "has_disability": "yes_no",
    "receives_other_aid": "yes_no",
    "full_name": "name_confirm",
    "confirm": "yes_no",
}
FORM_FIELD_FOR: Final[dict[str, str | None]] = {
    "household_size": "household_size",
    "income_band": "income_band",
    "is_widow": "is_widow",
    "has_disability": "has_disability",
    "receives_other_aid": "receives_other_aid",
    "full_name": None,  # "yes" writes nothing (a spoken yes must not replace a signed name); "no" sends it to a person
    "confirm": None,
}
HOUSEHOLD_RANGE: Final = (1, 20)  # the household screen's own range; larger families use the keypad and a person

INTERPRETER_VERSION: Final = "voice-interpreter-v1"
STT_FLOOR: Final = 0.45  # below this the speech engine itself was unsure: ask again
# The training families alone pick 0.61 (the lowest floor with no wrong answer there); 0.70 adds a margin.
# At 0.70 the unseen test families and the later holdout both have no wrong-but-confident answer (evaluate.py).
CONFIDENCE_FLOOR: Final = 0.70

PENALTIES: Final[dict[str, float]] = {
    "ambiguous_number_word": 0.70,
    "correction_used": 0.88,
    "leading_yes": 0.97,
    "extra_number": 0.85,
    "approximate": 0.85,
    "range_same_band": 0.86,
    "alternatives_same_band": 0.86,
    "on_band_boundary": 0.93,
    "topic_statement": 0.88,
    "negation_then_unknown": 0.85,
    "speech_confidence_missing": 0.93,
    "fraction_word": 0.92,
    "bound_less_more": 0.90,
    "alone_word": 0.92,
    "zero_income_phrase": 0.92,
    "name_matches": 0.86,
    "different_name_spoken": 0.80,
    "ambiguous_spelling": 0.80,
    "repeated_answer": 1.0,
    "possible_negation_or_hedge": 0.75,
    "unknown_word_next_to_number": 0.85,
    "unreadable_statement": 0.80,
}


@dataclass(slots=True)
class Interpretation:
    question_key: str
    expected: str
    choice: str | None  # canonical label: "yes", "no", "unknown", "5", "under_15k"
    value: int | bool | str | None  # the form value; None for "I don't know" and for abstentions
    unknown: bool = False
    confidence: float = 0.0
    raw_score: float = 0.0
    abstained: bool = True
    route: Route = "ask_more"
    reasons: list[str] = field(default_factory=list)
    probabilities: dict[str, float] = field(default_factory=dict)
    guard: dict[str, object] = field(default_factory=dict)
    redacted_transcript: str = ""


@dataclass(slots=True)
class _Proposal:
    choice: str | None
    value: int | bool | str | None = None
    unknown: bool = False
    score: float = 1.0
    reasons: list[str] = field(default_factory=list)

    def penalise(self, reason: str) -> None:
        self.score *= PENALTIES[reason]
        if reason not in self.reasons:
            self.reasons.append(reason)


def _abstain(reason: str, *extra: str) -> _Proposal:
    return _Proposal(choice=None, score=0.0, reasons=[reason, *extra])


# --- numbers -------------------------------------------------------------------------------------------


def _negation_kinds() -> frozenset[str]:
    return frozenset({"NO", "NEG"})


def _final_mentions(parsed: Parsed, mentions: list[Mention], proposal: _Proposal) -> list[Mention] | None:
    """Apply corrections: a mention followed later by a negation or a correction marker is replaced.

    Returns None when a number is negated with nothing after it ("paanch nahi").
    """
    items = parsed.items
    kept: list[Mention] = []
    for idx, mention in enumerate(mentions):
        after_end = mentions[idx + 1].start if idx + 1 < len(mentions) else len(items)
        between = items[mention.end : after_end]
        corrected = any(i.kind in _negation_kinds() or i.kind in ("CORR", "CONF_NO") for i in between)
        if corrected:
            if idx + 1 >= len(mentions):
                return None
            proposal.penalise("correction_used")
            continue
        kept.append(mention)
    return kept


def _between(parsed: Parsed, a: Mention, b: Mention) -> list[str]:
    return [i.kind for i in parsed.items[a.end : b.start] if i.kind not in ("FILLER",)]


def _household(parsed: Parsed) -> _Proposal:
    p = _Proposal(choice=None)
    mentions = numbers(parsed)
    kinds = set(parsed.kinds())
    if "UNKNOWN" in kinds:
        if mentions or "HEDGE" in kinds:
            return _abstain("unknown_with_number")
        if "YES" in kinds:
            return _abstain("mixed_answers")
        if "NO" in kinds:
            p.penalise("negation_then_unknown")
        p.choice, p.value, p.unknown = "unknown", None, True
        return p
    if "BESIDES" in kinds:
        return _abstain("count_relative_to_someone")
    if "nine_or_no" in parsed.flags:
        return _abstain("ambiguous_number_word")
    if "HEDGE" in kinds:
        return _abstain("hedged_answer")
    if "CHILD" in kinds:
        return _abstain("counted_in_parts")  # "teen bachay aur do baray": the total is not said
    if "ALONE" in kinds and not mentions:
        if parsed.has("NO") or parsed.has("NEG"):
            return _abstain("negated_answer")
        p.choice, p.value = "1", 1
        p.penalise("alone_word")
        return p
    if not mentions:
        if parsed.has("YES") or parsed.has("NO") or parsed.has("TOPIC"):
            return _abstain("answer_type_mismatch")
        return _abstain("no_answer_found")
    if any(m.has_multiplier for m in mentions):
        return _abstain("answer_type_mismatch", "looks_like_money")
    if "LESS" in kinds or "MORE" in kinds:
        return _abstain("not_an_exact_number")
    final = _final_mentions(parsed, mentions, p)
    if final is None:
        return _abstain("negated_without_replacement")
    values = {m.value for m in final}
    if len(values) > 1:
        for a, b in zip(final, final[1:], strict=False):
            if "AND" in _between(parsed, a, b):
                return _abstain("sum_of_numbers")
        return _abstain("two_different_numbers")
    if len(final) > 1:
        p.penalise("repeated_answer")
    value = final[-1].value
    if value != int(value):
        return _abstain("not_a_whole_number")
    count = int(value)
    if not HOUSEHOLD_RANGE[0] <= count <= HOUSEHOLD_RANGE[1]:
        return _abstain("number_out_of_range")
    weak = min(m.weak for m in final)
    if weak < 1.0:
        p.score *= weak
        p.reasons.append("ambiguous_number_word")
    if "APPROX" in kinds:
        p.penalise("approximate")
    if parsed.has("YES") and not parsed.has("NO"):
        p.penalise("leading_yes")
    p.score *= min(m.fuzzy for m in final) / 100.0 if min(m.fuzzy for m in final) < 100 else 1.0
    p.choice, p.value = str(count), count
    return p


# --- income --------------------------------------------------------------------------------------------

_BANDS: Final[tuple[tuple[str, float, float], ...]] = (
    ("under_15k", 0, 14_999.999),
    ("15k_30k", 15_000, 30_000),  # 30,000 is at the income cap ("at or below Rs 30,000"), so it belongs here
    ("30k_50k", 30_000.001, 50_000),
    ("over_50k", 50_000.001, math.inf),
)
_BOUNDARIES: Final = (15_000.0, 30_000.0, 50_000.0)


def band_for(amount: float) -> IncomeBand:
    for name, low, high in _BANDS:
        if low <= amount <= high:
            return name  # type: ignore[return-value]
    return "over_50k"


def _range_band(low: float, high: float) -> str | None:
    """The band that contains the whole range, or None when it spans two."""
    a = band_for(low + 1 if low in _BOUNDARIES else low)
    b = band_for(high)
    return a if a == b else None


def _scaled(parsed: Parsed, mentions: list[Mention]) -> list[tuple[float, Mention]]:
    """"bees pachees hazaar" and "bees se pachees hazaar": the multiplier of the second applies to the first."""
    out: list[tuple[float, Mention]] = []
    for idx, m in enumerate(mentions):
        value = m.value
        if not m.has_multiplier and idx + 1 < len(mentions):
            nxt = mentions[idx + 1]
            gap = _between(parsed, m, nxt)
            if nxt.has_multiplier and all(k in ("LINK", "ALT", "NEUTRAL") for k in gap) and value >= 1:
                for scale in (100_000.0, 1000.0, 100.0):
                    if nxt.value >= scale and nxt.value / scale > value:
                        value = value * scale
                        break
        out.append((value, m))
    return out


def _income(parsed: Parsed) -> _Proposal:
    p = _Proposal(choice=None)
    kinds = set(parsed.kinds())
    mentions = numbers(parsed)
    if "UNKNOWN" in kinds:
        if mentions or "HEDGE" in kinds:
            return _abstain("unknown_with_number")
        p.choice, p.value, p.unknown = "unknown", None, True
        return p
    if "PERIOD" in kinds:
        return _abstain("income_not_monthly")
    if "HEDGE" in kinds:
        return _abstain("hedged_answer")
    if "ZERO" in kinds and not mentions:
        p.choice, p.value = "under_15k", "under_15k"
        p.penalise("zero_income_phrase")
        return p
    if not mentions:
        if parsed.has("YES") or parsed.has("NO") or parsed.has("TOPIC"):
            return _abstain("answer_type_mismatch")
        return _abstain("no_answer_found")
    final = _final_mentions(parsed, mentions, p)
    if final is None:
        return _abstain("negated_without_replacement")
    scaled = _scaled(parsed, final)
    amounts = [v for v, _ in scaled]
    if any(0 < a < 1000 for a in amounts):
        if len(amounts) == 1 or not any(m.has_multiplier for _, m in scaled):
            return _abstain("income_unit_missing")
    weak = min(m.weak for _, m in scaled)
    if weak < 1.0:
        p.score *= weak
        p.reasons.append("ambiguous_number_word")
    if any(not float(v).is_integer() for v in (m.value for m in final)) or parsed.has("FRACP"):
        p.penalise("fraction_word")
    if "LESS" in kinds or "MORE" in kinds:
        if len(amounts) != 1:
            return _abstain("unclear_bound")
        amount = amounts[0]
        band = _range_band(0, amount - 1) if "LESS" in kinds and "MORE" not in kinds else _range_band(amount, math.inf)
        if band is None:
            return _abstain("range_spans_bands")
        p.penalise("bound_less_more")
        p.choice = p.value = band
        return p
    if len(amounts) > 1:
        low, high = min(amounts), max(amounts)
        band = _range_band(low, high)
        if band is None:
            return _abstain("range_spans_bands")
        between_kinds = {k for a, b in zip(final, final[1:], strict=False) for k in _between(parsed, a, b)}
        if "AND" in between_kinds:
            return _abstain("sum_of_numbers")
        p.penalise("alternatives_same_band" if "ALT" in between_kinds else "range_same_band")
        p.choice = p.value = band
        return p
    amount = amounts[0]
    band = band_for(amount)
    if amount in _BOUNDARIES:
        p.penalise("on_band_boundary")
    if "APPROX" in kinds:
        p.penalise("approximate")
        if any(abs(amount - b) <= 0.1 * b for b in _BOUNDARIES):
            return _abstain("approximate_near_boundary")
    if parsed.has("YES") and not parsed.has("NO"):
        p.penalise("leading_yes")
    fuzzy = min(m.fuzzy for m in final)
    if fuzzy < 100:
        p.score *= fuzzy / 100.0
    p.choice = p.value = band
    return p


# --- yes / no ------------------------------------------------------------------------------------------


_TOPIC_QUESTIONS: Final = frozenset({"is_widow", "has_disability", "receives_other_aid"})
_ENGLISH_NEGATORS: Final = frozenset({"no", "not", "no one", "nobody", "none", "never"})
_PRONOUNS: Final = frozenset(tokens("i we me my main hum mera meri"))


_COPULA: Final = frozenset(tokens("hoon hun hu hai hain hay hen am is are was were ہوں ہے ہیں تھا تھی"))


def _unreadable_statement(parsed: Parsed) -> bool:
    """After the answer word comes a clause ("main ... hoon") with a word we could not read."""
    answer_at = next((i.start for i in parsed.items if i.kind in ("YES", "NO", "NEG", "CONF_YES", "CONF_NO")), None)
    if answer_at is None:
        return False
    after = [i for i in parsed.items if i.start > answer_at]
    return any(i.kind == "NOISE" for i in after) and any(t in _COPULA for t in parsed.tokens[answer_at + 1 :])


def _negates_topic(parsed: Parsed, item: Item, topic_start: int) -> bool:
    """An English negator close before the topic word, with no new subject in between, negates the statement."""
    if item.text not in _ENGLISH_NEGATORS or topic_start - item.end > 3:
        return False
    return not any(t in _PRONOUNS for t in parsed.tokens[item.end : topic_start])


def _yes_no(parsed: Parsed, question: str) -> _Proposal:
    p = _Proposal(choice=None)
    items = parsed.items
    kinds = parsed.kinds()
    confirm_words = question in ("confirm", "full_name")
    yes = kinds.count("YES") + (kinds.count("CONF_YES") if confirm_words else 0)
    no = kinds.count("NO") + kinds.count("NEG") + (kinds.count("CONF_NO") if confirm_words else 0)
    no += kinds.count("ZERO")  # "kuch nahi milta" (nothing comes) answers "do you get other help?"
    has_numbers = bool(numbers(parsed))
    if kinds.count("UNKNOWN"):
        if yes or "HEDGE" in kinds or "TOPIC" in kinds and question in _TOPIC_QUESTIONS:
            return _abstain("mixed_answers")
        p.choice, p.value, p.unknown = "unknown", None, True
        if no:
            p.penalise("negation_then_unknown")
        return p
    if "HEDGE" in kinds:
        return _abstain("hedged_answer")

    statement: str | None = None
    topics = [i for i in items if i.kind == "TOPIC"]
    if topics and question in _TOPIC_QUESTIONS:
        # "main bewa hoon" says yes; "main bewa nahi hoon" says no. A "no" only before the topic word
        # ("nahi, main bewa hoon") contradicts the statement, so nothing is guessed.
        first = topics[0].start
        negated_after = any(i.kind in ("NO", "NEG") and i.start > first for i in items)
        # English negates before the noun ("I am not a widow", "no one is disabled", "we get no aid"); Urdu
        # negates after it ("bewa nahi"). A "no" said first and apart from the statement is an answer of its own.
        negators_before = [i for i in items if i.kind in ("NO", "NEG") and i.start < first]
        english_negated = any(_negates_topic(parsed, i, first) for i in negators_before)
        interjections = [i for i in negators_before if not _negates_topic(parsed, i, first)]
        statement = "no" if (negated_after or english_negated) else "yes"
        if statement == "yes" and interjections:
            return _abstain("contradicts_statement")
        if statement == "no" and yes:
            return _abstain("mixed_answers")
    elif question == "full_name" and topics and parsed.has("NAME_THIS") and not yes and not no:
        statement = "yes"  # "yahi mera naam hai": this is my name
    if statement is None and yes and no:
        return _abstain("mixed_answers")
    if statement is not None:
        p.choice, p.value = statement, statement == "yes"
        if statement == "yes":
            explicit = bool(yes)
        else:
            explicit = any(i.kind == "NO" and i.start < topics[0].start and not _negates_topic(parsed, i, topics[0].start)
                           for i in items)
        if not explicit:
            p.penalise("topic_statement")
    elif no:
        p.choice, p.value = "no", False
    elif yes:
        p.choice, p.value = "yes", True
    else:
        if has_numbers:
            return _abstain("answer_type_mismatch")
        return _abstain("no_answer_found")
    if has_numbers:
        p.penalise("extra_number")
    if statement is None and question != "full_name" and _unreadable_statement(parsed):  # a spoken name is expected there
        p.penalise("unreadable_statement")  # "nahi, main bwa hoon": the part we cannot read may contradict the answer
    fuzzy = min((i.fuzzy for i in items if i.kind in ("YES", "NO", "NEG", "CONF_YES", "CONF_NO", "TOPIC")), default=100.0)
    if fuzzy < 100:
        p.score *= fuzzy / 100.0
    return p


def _name_confirm(parsed: Parsed, transcript: str, expected_name: str | None) -> _Proposal:
    base = _yes_no(parsed, "full_name")
    if base.choice is not None or base.reasons[:1] != ["no_answer_found"]:
        return base
    # No yes or no: did they say a name? Compare it with the name on the card (same script only).
    if expected_name and parsed.has("TOPIC"):
        from rapidfuzz import fuzz

        said = [t for t in tokens(transcript) if t not in _NAME_GLUE]
        wanted = [t for t in tokens(expected_name) if t not in _NAME_GLUE]
        if not said or not wanted:
            return _abstain("no_answer_found")
        score = fuzz.token_set_ratio(" ".join(said), " ".join(wanted))
        p = _Proposal(choice=None)
        if score >= 88:
            p.choice, p.value = "yes", True
            p.penalise("name_matches")
        elif score <= 50:
            p.choice, p.value = "no", False
            p.penalise("different_name_spoken")
        else:
            return _abstain("name_unclear")
        return p
    return _abstain("no_answer_found")


_NAME_GLUE: Final = frozenset(tokens("mera meri naam nam name is my hai ہے میرا نام the"))


# --- entry point ---------------------------------------------------------------------------------------


def _probabilities(expected: str, choice: str | None, confidence: float) -> dict[str, float]:
    if expected in ("yes_no", "name_confirm"):
        labels = ["yes", "no", "unknown"]
    elif expected == "income_band":
        labels = ["under_15k", "15k_30k", "30k_50k", "over_50k", "unknown"]
    else:
        labels = [choice] if choice else []
        if choice is None:
            return {}
        rest = round(1.0 - confidence, 4)
        return {choice: round(confidence, 4), "other": rest}
    if choice is None:
        return {label: round(1.0 / len(labels), 4) for label in labels}
    rest = (1.0 - confidence) / (len(labels) - 1)
    return {label: round(confidence if label == choice else rest, 4) for label in labels}


def interpret(
    question_key: str,
    transcript: str,
    *,
    expected: str | None = None,
    stt_confidence: float | None = None,
    expected_name: str | None = None,
    alternatives: tuple[str, ...] = (),
    floor: float | None = None,
) -> Interpretation:
    """`floor` overrides the confidence floor; only the evaluation uses it."""
    expected = expected or EXPECTED_FOR[question_key]
    floor = CONFIDENCE_FLOOR if floor is None else floor
    guard = check_input(transcript, "transcript")
    result = Interpretation(question_key=question_key, expected=expected, choice=None, value=None,
                            guard=guard.summary(), redacted_transcript=guard.redacted_text or "")  # fmt: skip
    if guard.blocked:
        result.reasons = ["guardrail_blocked", *guard.codes]
        result.probabilities = _probabilities(expected, None, 0.0)
        return result
    if not skeleton(transcript):
        result.reasons = ["empty_transcript"]
        return result
    speech = stt_confidence if stt_confidence and stt_confidence > 0 else None  # 0 means "not reported" on some engines
    if speech is not None and speech < STT_FLOOR:
        result.reasons = ["low_speech_confidence"]
        result.probabilities = _probabilities(expected, None, 0.0)
        return result

    proposal = _propose(question_key, expected, transcript, expected_name)
    if proposal.choice is not None:
        parsed = parse(transcript, question=question_key)
        total = max(len(parsed.tokens), 1)
        noise = parsed.noise_tokens
        if expected == "name_confirm" and parsed.has("TOPIC"):
            noise = 0  # after "mera naam", the unreadable words are the name itself: the evidence, not noise
        proposal.score *= 1.0 - 0.45 * (max(noise, 0) / total)
        if "ambiguous_spelling" in parsed.flags:
            proposal.penalise("ambiguous_spelling")
        if "possible_negation_or_hedge" in parsed.flags:
            proposal.penalise("possible_negation_or_hedge")
        if expected in ("number", "income_band") and _noise_next_to_number(parsed):
            proposal.penalise("unknown_word_next_to_number")
        if speech is None:
            proposal.penalise("speech_confidence_missing")
        else:
            proposal.score *= 0.55 + 0.45 * speech
        # Other hypotheses from the speech engine: disagreement lowers confidence, a confident rival abstains.
        for alt in alternatives[:4]:
            rival = _propose(question_key, expected, alt, expected_name)
            if rival.choice is not None and rival.choice != proposal.choice:
                proposal.score *= 0.6
                if "alternatives_disagree" not in proposal.reasons:
                    proposal.reasons.append("alternatives_disagree")
    result.raw_score = round(max(0.0, min(1.0, proposal.score)), 4)
    result.confidence = result.raw_score
    result.reasons = list(proposal.reasons)
    if proposal.choice is None:
        result.probabilities = _probabilities(expected, None, 0.0)
        return result
    if result.confidence < floor:
        result.reasons = ["low_confidence", *result.reasons]
        result.probabilities = _probabilities(expected, None, 0.0)
        return result
    result.choice = proposal.choice
    result.value = proposal.value
    result.unknown = proposal.unknown
    result.abstained = False
    result.route = "auto"
    result.reasons = ["read_back_required", *result.reasons]
    result.probabilities = _probabilities(expected, proposal.choice, result.confidence)
    return result


def _noise_next_to_number(parsed: Parsed) -> bool:
    """An unreadable word right beside a number may be a misheard number ("tehar chhabees hazaar")."""
    items = parsed.items
    for idx, item in enumerate(items):
        if item.kind != "NOISE":
            continue
        neighbours = [items[k].kind for k in (idx - 1, idx + 1) if 0 <= k < len(items)]
        if any(kind in ("NUM", "MULT") for kind in neighbours):
            return True
    return False


def _propose(question_key: str, expected: str, transcript: str, expected_name: str | None) -> _Proposal:
    parsed = parse(transcript, question=question_key)
    if expected == "number":
        return _household(parsed)
    if expected == "income_band":
        return _income(parsed)
    if expected == "name_confirm":
        return _name_confirm(parsed, transcript, expected_name)
    return _yes_no(parsed, question_key)


__all__ = ["EXPECTED_FOR", "FORM_FIELD_FOR", "Interpretation", "band_for", "interpret", "L"]
