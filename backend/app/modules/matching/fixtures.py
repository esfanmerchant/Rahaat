"""Labelled messy record pairs for measuring dedupe, built from a fixed seed. Mock identifiers only.

Each fixture is a pair of person records and the truth: one person or two. The kinds cover what goes
wrong in real registers: other spellings, swapped and dropped name parts, honorifics, Urdu script, typed
IDs with a wrong digit or check digit, impossible or mistyped dates of birth, missing fields, changed and
shared phones; and the traps on the other side: namesakes, siblings and spouses on one phone, one common
given name, a national ID reused under another name.

`evaluate()` reports precision and recall of every band, the wrong links (two people linked as one: must
be zero), and how many true duplicates blocking would have let through.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Final

from app.core.mockdata import make_mock_id, make_mock_phone
from app.modules.matching.compare import BAND_ORDER, PersonRecord, blocking_keys, compare
from app.synth import names as N

FIXTURE_SEED: Final = 20261121
PER_KIND: Final = 24


@dataclass(frozen=True, slots=True)
class NameFixture:
    fixture_id: str
    kind: str
    a: PersonRecord
    b: PersonRecord
    same_person: bool
    expected: frozenset[str]  # bands that are acceptable for this kind


class _Maker:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.serial = 3_100_000

    def next_serial(self) -> int:
        self.serial += self.rng.randint(1, 97)
        return self.serial

    def person(self, gender: str | None = None) -> dict[str, Any]:
        rng = self.rng
        gender = gender or rng.choice(("female", "male"))
        family = rng.choice(sorted(N.FAMILY))
        full, urdu = N.make_name(rng, gender, family)
        born = date(1950, 1, 1) + timedelta(days=rng.randint(0, 52 * 365))
        serial = self.next_serial()
        return {
            "names": (full,), "urdu": urdu, "gender": gender, "district": rng.choice(N.DISTRICTS), "dob": born.isoformat(),
            "national_id": make_mock_id(serial), "phone": make_mock_phone(serial), "family": family,
        }  # fmt: skip

    @staticmethod
    def record(ref: str, p: dict[str, Any], **changes: Any) -> PersonRecord:
        base = PersonRecord(ref=ref, names=p["names"], dob=p["dob"], gender=p["gender"], district=p["district"],
                            national_id=p["national_id"], phone=p["phone"])  # fmt: skip
        return replace(base, **changes)

    def variant(self, name: str, mess: float = 0.9) -> str:
        for _ in range(12):
            text = N.messy_variant(self.rng, name, mess=mess)
            if text != name:
                return text
        return name.upper()

    def other_phone(self) -> str:
        return make_mock_phone(self.next_serial() + 5_000_000)

    def other_id(self) -> str:
        return make_mock_id(self.next_serial() + 4_000_000)

    def wrong_check_digit(self, national_id: str) -> str:
        body, check = national_id[:-1], int(national_id[-1])
        return f"{body}{(check + self.rng.randint(1, 9)) % 10}"

    def one_digit_typo(self, national_id: str) -> str:
        positions = [i for i, ch in enumerate(national_id) if ch.isdigit() and 6 <= i <= 12]
        i = self.rng.choice(positions)
        digit = str((int(national_id[i]) + self.rng.randint(1, 9)) % 10)
        return national_id[:i] + digit + national_id[i + 1:]

    def dob_typo(self, dob: str) -> str:
        day = date.fromisoformat(dob)
        if day.day <= 12 and day.month != day.day and self.rng.random() < 0.5:
            return date(day.year, day.day, day.month).isoformat()  # day and month swapped
        return (day + timedelta(days=self.rng.choice((-1, 1)))).isoformat()

    def other_dob(self, dob: str) -> str:
        day = date.fromisoformat(dob)
        return (day + timedelta(days=self.rng.choice((-1, 1)) * self.rng.randint(400, 9000))).isoformat()

    def impossible_dob(self, dob: str) -> str:
        year = dob[:4]
        return self.rng.choice((f"{year}-02-30", f"{year}-13-05", "2031-04-01", f"{year}-00-11"))


def _urdu_family(p: dict[str, Any]) -> str:
    """The Urdu name with the Latin given name: mixed script, as typed by a helper on a Latin keyboard."""
    latin_first = p["names"][0].split()[0]
    urdu_rest = " ".join(p["urdu"].split()[1:])
    return f"{latin_first} {urdu_rest}".strip()


def _builders(m: _Maker) -> dict[str, tuple[bool, frozenset[str], Callable[[int], tuple[PersonRecord, PersonRecord]]]]:
    SAME, POSSIBLE, DISTINCT = frozenset({"same"}), frozenset({"possible"}), frozenset({"distinct"})
    LINK_OR_REVIEW = frozenset({"same", "possible"})

    def spelling_same_id(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, names=(m.variant(p["names"][0]),))

    def spelling_other_phone_no_id(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person(gender="male")
        name = p["names"][0] if p["names"][0].startswith("Muhammad") else f"Muhammad {p['names'][0]}"
        p = {**p, "names": (name,)}
        spelled = name.replace("Muhammad", m.rng.choice(("Mohammad", "Muhammed", "Mohammed", "Mohd", "Md")), 1)
        return (m.record(f"a{i}", p, national_id=None),
                m.record(f"b{i}", p, names=(spelled,), national_id=None, phone=m.other_phone()))  # fmt: skip

    def swapped_order(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        parts = p["names"][0].split()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, names=(" ".join(reversed(parts)),))

    def honorific_dob_phone(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        title = m.rng.choice(("Mst.", "Haji", "Syed", "Mian", "Mrs."))
        return m.record(f"a{i}", p, national_id=None), m.record(f"b{i}", p, names=(f"{title} {p['names'][0]}",), national_id=None)

    def urdu_script_same_id(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, names=(p["urdu"],), phone=None)

    def mixed_script(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, names=(_urdu_family(p),), phone=None)

    def wrong_check_digit(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, national_id=m.wrong_check_digit(p["national_id"]), phone=m.other_phone())

    def id_digit_typo(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, national_id=m.one_digit_typo(p["national_id"]), phone=None)

    def dob_typo_same_id(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, dob=m.dob_typo(p["dob"]), names=(m.variant(p["names"][0], 0.5),))

    def impossible_dob(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p, national_id=None), m.record(f"b{i}", p, dob=m.impossible_dob(p["dob"]), national_id=None)

    def missing_fields(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return (m.record(f"a{i}", p, national_id=None, district=None),
                m.record(f"b{i}", p, names=(m.variant(p["names"][0], 0.6),), national_id=None, dob=None, gender=None))  # fmt: skip

    def phone_changed_same_id(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", p, phone=m.other_phone())

    # --- two different people ---
    def household_shared_phone(i: int) -> tuple[PersonRecord, PersonRecord]:
        p = m.person()
        q = m.person()
        q_name = N.make_name(m.rng, q["gender"], p["family"])[0]
        return (m.record(f"a{i}", p),
                m.record(f"b{i}", q, names=(q_name,), phone=p["phone"], district=p["district"]))  # fmt: skip

    def common_given_name(i: int) -> tuple[PersonRecord, PersonRecord]:
        p, q = m.person(gender="male"), m.person(gender="male")
        given = m.rng.choice(("Ali", "Ahmed", "Bilal", "Imran"))
        return (m.record(f"a{i}", p, names=(f"Muhammad {given} {p['family']}",)),
                m.record(f"b{i}", q, names=(f"Muhammad {given} {q['family']}",)))  # fmt: skip

    def namesakes_other_dob(i: int) -> tuple[PersonRecord, PersonRecord]:
        p, q = m.person(), m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", q, names=p["names"], gender=p["gender"], dob=m.other_dob(p["dob"]))

    def namesakes_same_dob(i: int) -> tuple[PersonRecord, PersonRecord]:
        p, q = m.person(), m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", q, names=(m.variant(p["names"][0], 0.4),), gender=p["gender"], dob=p["dob"])

    def siblings_similar_names(i: int) -> tuple[PersonRecord, PersonRecord]:
        pairs = (("Sana", "Saima"), ("Nadia", "Naila"), ("Asif", "Arif"), ("Zahid", "Zahida"), ("Shahid", "Shahida"), ("Amina", "Amna"))
        first, second = m.rng.choice(pairs)
        p, q = m.person(), m.person()
        return (m.record(f"a{i}", p, names=(f"{first} {p['family']}",)),
                m.record(f"b{i}", q, names=(f"{second} {p['family']}",), phone=p["phone"], district=p["district"],
                         dob=m.other_dob(p["dob"])))  # fmt: skip

    def spouse_relation(i: int) -> tuple[PersonRecord, PersonRecord]:
        husband = m.person(gender="male")
        wife = m.person(gender="female")
        wife_name = f"{N.make_name(m.rng, 'female', husband['family'])[0]} w/o {husband['names'][0]}"
        return (m.record(f"a{i}", husband),
                m.record(f"b{i}", wife, names=(wife_name,), phone=husband["phone"], district=husband["district"]))  # fmt: skip

    def reused_id_other_name(i: int) -> tuple[PersonRecord, PersonRecord]:
        p, q = m.person(), m.person()
        return m.record(f"a{i}", p), m.record(f"b{i}", q, national_id=p["national_id"])

    return {
        "spelling_same_id": (True, SAME, spelling_same_id),
        "spelling_other_phone_no_id": (True, POSSIBLE, spelling_other_phone_no_id),
        "swapped_order": (True, SAME, swapped_order),
        "honorific_dob_and_phone": (True, SAME, honorific_dob_phone),
        "urdu_script_same_id": (True, SAME, urdu_script_same_id),
        "mixed_script_same_id": (True, SAME, mixed_script),
        "wrong_check_digit": (True, POSSIBLE, wrong_check_digit),
        "id_one_digit_typo": (True, LINK_OR_REVIEW, id_digit_typo),
        "dob_typo_same_id": (True, SAME, dob_typo_same_id),
        "impossible_dob": (True, LINK_OR_REVIEW, impossible_dob),
        "missing_fields": (True, POSSIBLE, missing_fields),
        "phone_changed_same_id": (True, POSSIBLE, phone_changed_same_id),
        "household_shared_phone": (False, DISTINCT, household_shared_phone),
        "common_given_name": (False, DISTINCT, common_given_name),
        "namesakes_other_dob": (False, DISTINCT, namesakes_other_dob),
        "namesakes_same_dob": (False, frozenset({"possible", "distinct"}), namesakes_same_dob),
        "siblings_similar_names": (False, DISTINCT, siblings_similar_names),
        "spouse_relation": (False, DISTINCT, spouse_relation),
        "reused_id_other_name": (False, POSSIBLE, reused_id_other_name),
    }


def build_fixtures(seed: int = FIXTURE_SEED, per_kind: int = PER_KIND) -> list[NameFixture]:
    maker = _Maker(seed)
    out: list[NameFixture] = []
    for kind, (same, expected, build) in _builders(maker).items():
        for i in range(per_kind):
            a, b = build(i)
            out.append(NameFixture(fixture_id=f"{kind}-{i:02d}", kind=kind, a=a, b=b, same_person=same, expected=expected))
    return out


def _precision_recall(rows: Sequence[tuple[bool, str]], band: str, positive_is_same: bool) -> dict[str, Any]:
    predicted = [same for same, got in rows if got == band]
    relevant = sum(1 for same, _ in rows if same == positive_is_same)
    hits = sum(1 for same in predicted if same == positive_is_same)
    return {"predicted": len(predicted), "precision": round(hits / len(predicted), 4) if predicted else None,
            "recall": round(hits / relevant, 4) if relevant else None}  # fmt: skip


def evaluate(fixtures: Sequence[NameFixture]) -> dict[str, Any]:
    """Precision and recall per band, wrong links, blocking recall, and results per kind."""
    rows: list[tuple[bool, str]] = []
    by_kind: dict[str, Counter[str]] = {}
    as_expected = 0
    blocked_out = 0
    failures: list[dict[str, Any]] = []
    for fx in fixtures:
        shares_key = bool(blocking_keys(fx.a) & blocking_keys(fx.b))
        result = compare(fx.a, fx.b)
        band = result.band if shares_key else "distinct"  # never compared: dedupe would call it distinct
        if fx.same_person and not shares_key:
            blocked_out += 1
        rows.append((fx.same_person, band))
        by_kind.setdefault(fx.kind, Counter())[band] += 1
        if band in fx.expected:
            as_expected += 1
        elif len(failures) < 25:
            failures.append({"fixture": fx.fixture_id, "band": band, "expected": sorted(fx.expected), "score": result.score,
                             "name_score": result.name.score, "fields": result.fields, "blocked_out": not shares_key})  # fmt: skip
    same_total = sum(1 for same, _ in rows if same)
    caught = sum(1 for same, band in rows if same and BAND_ORDER[band] >= 1)
    return {
        "fixtures": len(fixtures), "same_person_pairs": same_total, "different_people_pairs": len(rows) - same_total,
        "kinds": len(by_kind),
        "bands": {
            "same": _precision_recall(rows, "same", True),
            "possible": _precision_recall(rows, "possible", True),
            "distinct": _precision_recall(rows, "distinct", False),
        },
        "wrong_links": sum(1 for same, band in rows if not same and band == "same"),
        "duplicates_caught": {"count": caught, "recall": round(caught / same_total, 4) if same_total else None},
        "duplicates_missed": same_total - caught,
        "blocking": {"true_pairs_without_a_shared_key": blocked_out,
                     "recall": round(1 - blocked_out / same_total, 4) if same_total else None},  # fmt: skip
        "as_expected": round(as_expected / len(fixtures), 4) if fixtures else None,
        "by_kind": {kind: dict(counts) for kind, counts in by_kind.items()},
        "unexpected": failures,
        "note": "Precision of 'possible' is low by design: it is the review band. A wrong link is two people linked as one.",
    }  # fmt: skip
