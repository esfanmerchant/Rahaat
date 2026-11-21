"""The rules assistant without a database: corpus integrity, groundedness, refusals, Urdu, and the output guard."""

from __future__ import annotations

import pytest

from app.modules.guardrails import pii
from app.modules.guardrails.output_guard import promise_codes
from app.modules.rag import answer as A
from app.modules.rag import evaluate as E
from app.modules.rag.corpus import CorpusError, load_corpus, parse_document
from app.modules.rag.eval_set import HOLDOUT, QUESTIONS
from app.modules.rag.index import LexicalIndex, Passage, make_query
from app.seed import RULES_V1


@pytest.fixture(scope="module")
def indexes() -> dict[str, LexicalIndex]:
    return E.indexes_from_files()


def test_corpus_is_complete_bilingual_and_versioned() -> None:
    docs = load_corpus()
    assert len(docs) == 14
    by_lang = {lang: {(d.doc_key, s.section_id) for d in docs if d.lang == lang for s in d.sections} for lang in ("en", "ur")}
    assert by_lang["en"] == by_lang["ur"], "every section exists in English and in Urdu"
    for doc in docs:
        assert doc.version >= 1 and doc.status == "approved" and doc.rule_version == 1
        assert all(1 <= len(s.sentences) <= A.MAX_SENTENCES for s in doc.sections), doc.path


def test_corpus_matches_rule_version_1() -> None:
    rules = {d.lang: d for d in load_corpus() if d.doc_key == "rahat-rules"}
    cap = f"{RULES_V1['params']['income_cap']:,}"
    pay = f"{RULES_V1['payment_pkr']:,}"
    for lang, doc in rules.items():
        text = " ".join(s.text for s in doc.sections)
        assert cap in text and pay in text, lang
    english = " ".join(s.text for s in rules["en"].sections)
    for needed in ("identity", "signed Rahat card", "registry", "already receive", "Widows", "disability", "five or more"):
        assert needed in english, needed


def test_no_corpus_sentence_promises_or_holds_personal_data() -> None:
    for doc in load_corpus():
        for section in doc.sections:
            for sentence in section.sentences:
                assert promise_codes(sentence) == [], (doc.path, sentence)
                assert not pii.mask(sentence).found, (doc.path, sentence)


def test_malformed_documents_are_refused() -> None:
    with pytest.raises(CorpusError):
        parse_document("no front matter", "x.md")
    head = "---\ndoc: d\nlang: en\nversion: 1\ntitle: T\nstatus: approved\n---\n"
    with pytest.raises(CorpusError):
        parse_document(head + "## Heading without id\nText.\n", "x.md")
    with pytest.raises(CorpusError):
        parse_document(head + "## A {#a}\nOne.\n## B {#a}\nTwo.\n", "x.md")


def test_every_answer_sentence_is_in_its_cited_chunk(indexes: dict[str, LexicalIndex]) -> None:
    answered = 0
    for q in (*QUESTIONS, *HOLDOUT):
        result = A.compose(indexes, q.question, q.lang)
        assert len(result.sentences) <= A.MAX_SENTENCES
        for sentence in result.sentences:
            assert sentence.text in sentence.passage.sentences
            assert sentence.text in sentence.passage.text
            answered += 1
        if result.answered:
            assert result.output_verdict is not None and result.output_verdict.verdict == "allow"
    assert answered > 100


def test_off_topic_and_attacks_are_refused(indexes: dict[str, LexicalIndex]) -> None:
    for q in (*QUESTIONS, *HOLDOUT):
        if q.kind == "answerable":
            continue
        result = A.compose(indexes, q.question, q.lang)
        assert not result.answered, (q.id, result.reason, result.top_score)
        assert result.message_key in ("ask_not_sure", "ask_cannot_act")


def test_attacks_never_reach_retrieval(indexes: dict[str, LexicalIndex]) -> None:
    for q in QUESTIONS:
        if q.kind == "attack":
            result = A.compose(indexes, q.question, q.lang)
            assert result.reason == "guardrail_blocked" and result.top_score == 0.0


def test_urdu_questions_get_urdu_answers(indexes: dict[str, LexicalIndex]) -> None:
    result = A.compose(indexes, "اپیل کیسے کریں؟", "en")  # Urdu script wins over the requested language
    assert result.answered and result.lang == "ur"
    assert all(s.passage.lang == "ur" for s in result.sentences)
    assert result.sentences[0].passage.section_id == "appeal"
    roman = A.compose(indexes, "paise kitne milenge", "ur")
    assert roman.answered and roman.lang == "ur" and roman.sentences[0].passage.section_id == "payment"
    english = A.compose(indexes, "paise kitne milenge", "en")
    assert english.answered and english.lang == "en" and "12,000" in english.sentences[0].text


def test_personal_questions_carry_the_no_promise_notice(indexes: dict[str, LexicalIndex]) -> None:
    for question, lang in (("Am I eligible?", "en"), ("کیا مجھے رقم ملے گی؟", "ur"), ("Will I get the money?", "en")):
        result = A.compose(indexes, question, lang)
        if result.answered:
            assert result.message_key == "ask_no_promise", question
            assert all(promise_codes(s.text) == [] for s in result.sentences)


def test_a_planted_promise_is_blocked_by_the_output_guard() -> None:
    fake = Passage(chunk_id="c-1", document_id="d-1", doc_key="evil", title="Payment news", version=1, section_id="news",
                   heading="When the money comes", lang="en", sentences=("You will get Rs 12,000 next week.",))  # fmt: skip
    result = A.compose({"en": LexicalIndex.build([fake])}, "When will I get the Rs 12,000 money?", "en", threshold=0.05)
    assert not result.answered and result.reason == "output_blocked"
    assert result.output_verdict is not None and "payment_promise" in result.output_verdict.codes


def test_foreign_subject_is_refused(indexes: dict[str, LexicalIndex]) -> None:
    assert A.compose(indexes, "What documents do I need for a passport?", "en").reason == "outside_the_rules"
    assert A.compose(indexes, "پاسپورٹ کے لیے کون سے کاغذات چاہییں؟", "ur").reason == "outside_the_rules"
    assert A.compose(indexes, "Does Rahat ever ask for my PIN?", "en").answered  # "for my PIN": the rules know PINs


def test_personal_data_in_a_question_is_masked_before_search(indexes: dict[str, LexicalIndex]) -> None:
    result = A.compose(indexes, "My ID is 00000-1000201-8, how do I appeal?", "en")
    assert result.input_verdict is not None and result.input_verdict.verdict == "mask"
    assert "1000201" not in (result.input_verdict.redacted_text or "")
    assert result.answered and result.sentences[0].passage.section_id == "appeal"


def test_measured_quality() -> None:
    report = E.report()
    assert report["test"]["wrong_answers"] == 0, report["test"]["mistakes"]
    assert report["test"]["groundedness"] == 1.0 and report["dev"]["groundedness"] == 1.0
    assert report["test"]["answer_accuracy"] >= 0.9
    assert report["holdout"]["groundedness"] == 1.0
    assert report["holdout"]["off_topic_and_attacks_refused"] == "6/6"
    assert report["threshold_chosen_on_dev"] == A.THRESHOLD


def test_an_empty_index_refuses_instead_of_failing() -> None:
    empty = LexicalIndex.build([])
    assert empty.search(make_query("How do I apply?", "en")) == []
    result = A.compose({"en": empty, "ur": empty}, "How do I apply?", "en")
    assert not result.answered and result.reason == "low_retrieval" and result.message_key == "ask_not_sure"
