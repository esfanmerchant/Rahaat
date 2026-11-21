"""Name normalisation, transliteration, phonetic keys, similarity and record bands. DB-free."""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.mockdata import make_mock_id, make_mock_phone
from app.modules.matching.compare import BAND_ORDER, PersonRecord, blocking_keys, compare, compare_dob, valid_dob
from app.modules.matching.fixtures import build_fixtures, evaluate
from app.modules.matching.names import name_key, name_similarity, parse_name, phonetic_key, score_names, transliterate
from app.synth import names as N

GIVEN = sorted(set(N.FEMALE) | set(N.MALE) - {"Muhammad"})
FAMILY = sorted(N.FAMILY)
latin_names = st.builds(lambda g, f: f"{g} {f}", st.sampled_from(GIVEN), st.sampled_from(FAMILY))
any_text = st.text(alphabet=st.characters(categories=("L", "Zs", "P")), max_size=40)


@pytest.mark.parametrize(("left", "right"), [
    ("Mohammad Aslam", "Muhammed Aslam"), ("Mohd Aslam", "Muhammad Aslam"), ("Md. Aslam", "محمد اسلم"),
    ("Zainab Bibi", "زینب بی بی"), ("Mst. Zainab", "Zainab Begum"), ("Bibi Zainab", "Zainab Bi Bi"),
    ("Khan Aslam", "Aslam Khan"), ("Zainab Bibi w/o Muhammad Ali", "Zainab Bibi"), ("Aslam Khan s/o Akbar Khan", "Aslam Khan"),
    ("Fatima Bibi d/o Rashid", "فاطمہ"), ("Chaudhry Imran", "چوہدری عمران"), ("Imran Jatoi", "عمران جتوئی"),
    ("Ayesha Siddiqui", "عائشہ صدیقی"), ("Parveen Akhtar", "پروین اختر"), ("Haji Rashid Soomro", "Rasheed Sumro"),
])  # fmt: skip
def test_spellings_scripts_and_honorifics_of_one_name_score_high(left: str, right: str) -> None:
    assert name_similarity(left, right) >= 0.9, (left, right, score_names(left, right))


@pytest.mark.parametrize(("left", "right"), [
    ("Aslam Khan", "Akram Khan"), ("Nadia Malik", "Nasreen Malik"), ("Zainab Bibi", "Fatima Bibi"),
    ("Muhammad Ali", "Muhammad Bilal"), ("Shahid Butt", "Sadia Butt"), ("Imran Qureshi", "Usman Qureshi"),
])  # fmt: skip
def test_different_given_names_with_a_shared_family_name_do_not_score_high(left: str, right: str) -> None:
    assert name_similarity(left, right) < 0.88, (left, right, score_names(left, right))


def test_parsing_keeps_common_parts_apart_and_drops_titles_and_relations() -> None:
    parsed = parse_name("Mst. Zenab Bibi w/o Muhammad Ali")
    assert parsed.tokens == ("zenab",) and parsed.common == ("bibi",)
    assert "mst" in parsed.dropped and any("muhammad ali" in d for d in parsed.dropped)
    assert parse_name("محمد اسلم خان").tokens == ("aslm", "khan") and parse_name("محمد اسلم خان").common == ("muhammad",)
    assert parse_name("Muhammad Bibi").tokens == () and name_similarity("Muhammad", "Mohd") == 0.0
    assert parse_name("").tokens == () and parse_name(None).tokens == ()
    assert transliterate("زینب") == "zinb" and transliterate("پروین") == "prwin" and transliterate("شاہ") == "shah"


def test_phonetic_keys_merge_spellings() -> None:
    for group in (("Zainab", "Zenab", "Zaynab", "زینب"), ("Fatima", "Fatimah", "Fatma", "فاطمہ"), ("Siddiqui", "Siddiqi", "Sidiqui"),
                  ("Chaudhry", "Chaudhary", "Choudhry", "چوہدری"), ("Waseem", "Wasim", "وسیم"), ("Usman", "Osman")):  # fmt: skip
        assert len({phonetic_key(parse_name(name).tokens[0]) for name in group}) == 1, group
    assert name_key("Muhammed Aslam Khan") == name_key("Khan Aslam") == name_key("محمد اسلم خان") == "aslm+kn"
    assert name_key("Mohd") is None


@settings(max_examples=150, deadline=None)
@given(latin_names, latin_names)
def test_similarity_is_symmetric_and_bounded(a: str, b: str) -> None:
    left, right = name_similarity(a, b), name_similarity(b, a)
    assert left == right and 0.0 <= left <= 1.0


@settings(max_examples=150, deadline=None)
@given(any_text)
def test_identity_and_never_raises_on_any_text(text: str) -> None:
    score = name_similarity(text, text)
    assert score == (1.0 if parse_name(text).tokens else 0.0)
    assert name_similarity(text, "Zainab Bibi") >= 0.0


@settings(max_examples=100, deadline=None)
@given(latin_names, st.sampled_from(sorted(N.HONORIFICS)), st.booleans())
def test_titles_and_case_do_not_change_the_score(name: str, title: str, upper: bool) -> None:
    other = f"{title} {name}"
    assert name_similarity(name, other.upper() if upper else other) == 1.0


# --- records and bands ---------------------------------------------------------------------------------


def _person(**changes: object) -> PersonRecord:
    base = PersonRecord(ref="a", names=("Muhammed Aslam Khan",), dob="1981-09-02", gender="male", district="Hyderabad",
                        national_id=make_mock_id(4_400_001), phone=make_mock_phone(4_400_001))  # fmt: skip
    return replace(base, **changes)  # type: ignore[arg-type]


def test_mohammad_against_muhammed_with_another_phone_is_a_possible_duplicate_not_a_link() -> None:
    existing = _person(national_id=None)
    newcomer = _person(ref="b", names=("Mohammad Aslam Khan",), national_id=None, phone=make_mock_phone(4_499_999))
    result = compare(existing, newcomer)
    assert result.band == "possible" and "phone" in result.conflicts and result.name.score >= 0.95
    # Even when the same national ID is typed, a contradicting phone keeps it for a person to decide.
    with_id = compare(_person(), _person(ref="b", names=("Mohammad Aslam Khan",), phone=make_mock_phone(4_499_999)))
    assert with_id.band == "possible"
    linked = compare(_person(), _person(ref="b", names=("Mohammad Aslam Khan",)))
    assert linked.band == "same" and linked.corroborated


none_or = st.one_of(st.none(), st.just("x"))


@settings(max_examples=200, deadline=None)
@given(latin_names, st.booleans(), st.booleans(), st.booleans(), st.sampled_from(["1981-09-02", "1990-01-01", None, "1981-02-30"]))
def test_a_name_alone_never_links(name: str, other_id: bool, other_phone: bool, gender_known: bool, dob: str | None) -> None:
    """With no national ID and no phone in common, the best any pair can get is 'possible', whatever the names."""
    gender = "male" if gender_known else None
    a = PersonRecord(ref="a", names=(name,), dob="1981-09-02", gender=gender, national_id=make_mock_id(4_500_001) if other_id else None,
                     phone=make_mock_phone(4_500_001) if other_phone else None)  # fmt: skip
    b = PersonRecord(ref="b", names=(name,), dob=dob, gender=gender, national_id=make_mock_id(4_500_777) if other_id else None,
                     phone=make_mock_phone(4_500_777) if other_phone else None)  # fmt: skip
    assert compare(a, b).band != "same"


@settings(max_examples=120, deadline=None)
@given(latin_names, latin_names, st.sampled_from(["national_id", "phone", "dob", "gender"]))
def test_monotone_an_agreeing_field_never_lowers_and_a_conflicting_one_never_raises(a_name: str, b_name: str, field: str) -> None:
    values = {"national_id": make_mock_id(4_600_001), "phone": make_mock_phone(4_600_001), "dob": "1975-05-06", "gender": "female"}
    others = {"national_id": make_mock_id(4_600_555), "phone": make_mock_phone(4_600_555), "dob": "1999-12-01", "gender": "male"}
    a = PersonRecord(ref="a", names=(a_name,))
    b = PersonRecord(ref="b", names=(b_name,))
    base = compare(a, b)
    agree = compare(replace(a, **{field: values[field]}), replace(b, **{field: values[field]}))  # type: ignore[arg-type]
    conflict = compare(replace(a, **{field: values[field]}), replace(b, **{field: others[field]}))  # type: ignore[arg-type]
    assert agree.score >= base.score >= conflict.score
    assert BAND_ORDER[agree.band] >= BAND_ORDER[base.band] >= BAND_ORDER[conflict.band] or base.band == "possible" and field == "national_id"
    assert compare(b, a).score == base.score and compare(b, a).band == base.band


def test_identity_of_a_full_record_links_with_itself() -> None:
    record = _person()
    result = compare(record, replace(record, ref="b"))
    assert result.band == "same" and result.score >= 0.99


def test_dates_impossible_or_typed_wrong() -> None:
    assert valid_dob("1978-02-30") is None and valid_dob("2031-01-01") is None and valid_dob("1978-13-01") is None
    assert compare_dob("1978-03-14", "1978-03-14") == "same"
    assert compare_dob("1978-03-14", "1978-03-15") == "near" and compare_dob("1978-03-04", "1978-04-03") == "near"
    assert compare_dob("1978-03-14", "1988-07-01") == "different" and compare_dob("1978-02-30", "1978-03-01") == "unknown"


def test_national_id_typos_and_check_digits_are_near_not_same() -> None:
    real = make_mock_id(4_700_123)
    wrong_check = real[:-1] + str((int(real[-1]) + 1) % 10)
    a, b = _person(national_id=real), _person(ref="b", national_id=wrong_check, phone=None)
    result = compare(a, b)
    assert result.fields["national_id"] == "near" and result.band == "possible"


def test_blocking_keys_cover_identifiers_dates_and_names() -> None:
    keys = blocking_keys(_person(names=("Muhammed Aslam Khan", "محمد اسلم خان")))
    assert {k.split(":")[0] for k in keys} == {"id", "ph", "dob", "nk"} and "nk:aslm+kn" in keys
    assert blocking_keys(PersonRecord(ref="x", names=("Mohd",), dob="1978-02-30")) == set()


def test_messy_fixtures_precision_and_recall_per_band() -> None:
    fixtures = build_fixtures()
    report = evaluate(fixtures)
    print(f"\nname fixtures: {report['fixtures']} pairs, {report['kinds']} kinds; bands {report['bands']}; "
          f"wrong links {report['wrong_links']}; caught {report['duplicates_caught']}; blocking {report['blocking']}")  # fmt: skip
    assert report["fixtures"] >= 200 and report["kinds"] >= 15
    assert report["wrong_links"] == 0, "two different people were linked as one"
    assert report["bands"]["same"]["precision"] == 1.0
    assert report["bands"]["distinct"]["precision"] >= 0.98
    assert report["duplicates_caught"]["recall"] >= 0.97
    assert report["blocking"]["recall"] >= 0.97
    assert report["as_expected"] >= 0.95
    assert evaluate(build_fixtures()) == report, "fixtures and results are reproducible"
