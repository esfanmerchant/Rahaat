"""The mock registry's records. Pure functions: the same mock ID always gives the same record.

The demo citizens (`app.demo_accounts.demo_citizens()`) get the stories in `data/mock/registry_stories.json`,
which the demo depends on. Any other valid mock ID gets a record derived deterministically from the ID.
An ID with a wrong check digit, or anything that is not a mock ID, is not found.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.mockdata import mock_id_valid

STORIES_PATH = Path(__file__).resolve().parents[3] / "data" / "mock" / "registry_stories.json"

# Invented names for derived records. Common given names and family names, combined at random: no real person.
_FEMALE = ("Amna", "Bushra", "Farah", "Ghazala", "Hina", "Kiran", "Mehwish", "Nasreen", "Parveen", "Rabia", "Saima", "Tahira")
_MALE = ("Abdul Rauf", "Danish", "Faisal", "Ghulam Nabi", "Irfan", "Javed", "Kamran", "Naveed", "Rashid", "Sajid", "Tariq", "Waqar")
_FAMILY = ("Abbasi", "Baloch", "Channa", "Jatoi", "Khoso", "Memon", "Mangi", "Pathan", "Qazi", "Rajput", "Soomro", "Unar")
_DISTRICTS = ("Karachi East", "Karachi West", "Hyderabad", "Sukkur", "Larkana", "Thatta", "Badin", "Mirpur Khas")


@dataclass(frozen=True)
class MockPerson:
    """One registry entry. `full_name_ur` is used by the identity service only; the registry API omits it."""

    national_id: str
    full_name: str
    dob: str
    gender: str
    district: str
    household_size: int
    verified_income_pkr: int | None
    income_as_of: str | None
    receives_other_aid: bool
    is_widow: bool
    has_disability: bool
    full_name_ur: str | None = None
    record_version: str = "1"

    def registry_view(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("full_name_ur")
        return data


def _month_start(today: date) -> date:
    return today.replace(day=1)


def _months_back(start: date, months: int) -> date:
    year, month = start.year, start.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


@lru_cache
def _stories() -> dict[str, dict[str, Any]]:
    raw = json.loads(STORIES_PATH.read_text(encoding="utf-8"))
    return dict(raw["stories"])


def demo_records(today: date | None = None) -> dict[str, MockPerson]:
    """Registry entries for the demo citizens, keyed by mock ID."""
    from app.demo_accounts import demo_citizens

    today = today or date.today()
    records: dict[str, MockPerson] = {}
    for citizen in demo_citizens():
        story = _stories().get(citizen["name"])
        if story is None:
            continue
        as_of = story.get("income_as_of")
        if as_of == "this_month":
            as_of = _month_start(today).isoformat()
        records[citizen["national_id"]] = MockPerson(
            national_id=citizen["national_id"], full_name=citizen["name"], full_name_ur=citizen.get("name_ur") or None,
            dob=citizen["dob"], gender=citizen["gender"], district=citizen.get("district") or "Karachi East",
            household_size=int(story["household_size"]), verified_income_pkr=story.get("verified_income_pkr"),
            income_as_of=as_of, receives_other_aid=bool(story.get("receives_other_aid", False)),
            is_widow=bool(story.get("is_widow", False)), has_disability=bool(story.get("has_disability", False)),
        )  # fmt: skip
    return records


def derived_record(national_id: str, today: date | None = None) -> MockPerson:
    """A stable invented record for any valid mock ID that has no story."""
    today = today or date.today()
    n = int.from_bytes(hashlib.sha256(f"rahat-mock-registry:{national_id}".encode()).digest(), "big")
    female = n & 1 == 1
    given = (_FEMALE if female else _MALE)[(n >> 4) % len(_FEMALE)]
    family = _FAMILY[(n >> 12) % len(_FAMILY)]
    dob = date(1950, 1, 1) + timedelta(days=(n >> 20) % (54 * 365))
    has_income = (n >> 40) % 10 >= 2  # about one record in five has no income on file
    income = 8_000 + ((n >> 48) % 50) * 1_000 if has_income else None
    as_of = _months_back(_month_start(today), int((n >> 56) % 12)).isoformat() if has_income else None
    return MockPerson(
        national_id=national_id, full_name=f"{given} {family}", dob=dob.isoformat(), gender="female" if female else "male",
        district=_DISTRICTS[(n >> 32) % len(_DISTRICTS)], household_size=1 + int((n >> 36) % 9),
        verified_income_pkr=income, income_as_of=as_of, receives_other_aid=(n >> 64) % 7 == 0,
        is_widow=female and (n >> 68) % 5 == 0, has_disability=(n >> 72) % 9 == 0,
    )  # fmt: skip


def find(national_id: str, overrides: dict[str, MockPerson] | None = None, today: date | None = None) -> MockPerson | None:
    """The record for a mock ID, or None when the ID is not a valid mock ID."""
    national_id = national_id.strip()
    if not mock_id_valid(national_id):
        return None
    if overrides and national_id in overrides:
        return overrides[national_id]
    demo = demo_records(today)
    if national_id in demo:
        return demo[national_id]
    return derived_record(national_id, today)


def with_changes(record: MockPerson, changes: dict[str, Any]) -> MockPerson:
    allowed = {k: v for k, v in changes.items() if k in MockPerson.__dataclass_fields__ and k != "national_id"}
    return replace(record, **allowed)
