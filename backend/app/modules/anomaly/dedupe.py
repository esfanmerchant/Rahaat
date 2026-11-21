"""One pattern opens one case. Pure: decides what to do with each finding given the cases that already exist.

    actions = plan_cases(findings, existing)

* an active case already holds this pattern: `refresh` it when the pattern grew (new applications), else `unchanged`;
* no active case, but a resolved one that already covered every application: `suppress` (a person reviewed exactly this);
* otherwise `open` a new case.

A ring that adds a fourth household after an officer dismissed three therefore comes back as a new case, and
the same three never come back twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.modules.anomaly.detectors import Finding

Kind = Literal["open", "refresh", "unchanged", "suppress"]


@dataclass(frozen=True, slots=True)
class ExistingCase:
    case_id: str
    pattern_key: str
    active: bool
    evidence_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class Action:
    kind: Kind
    finding: Finding
    case_id: str | None = None
    new_ids: tuple[str, ...] = ()


def plan_cases(findings: Iterable[Finding], existing: Sequence[ExistingCase]) -> list[Action]:
    by_key: dict[str, list[ExistingCase]] = {}
    for case in existing:
        by_key.setdefault(case.pattern_key, []).append(case)
    actions: list[Action] = []
    seen: set[str] = set()
    for finding in findings:
        if finding.pattern_key in seen:  # two findings of one run with one key are one pattern
            continue
        seen.add(finding.pattern_key)
        ids = set(finding.evidence_ids)
        cases = by_key.get(finding.pattern_key, [])
        active = [c for c in cases if c.active]
        if active:
            target = active[0]
            added = tuple(sorted(ids - target.evidence_ids))
            actions.append(Action("refresh", finding, target.case_id, added) if added else Action("unchanged", finding, target.case_id))
            continue
        reviewed = frozenset().union(*(c.evidence_ids for c in cases)) if cases else frozenset()
        if cases and ids <= reviewed:
            actions.append(Action("suppress", finding, cases[0].case_id))
        else:
            actions.append(Action("open", finding, None, tuple(sorted(ids - reviewed))))
    return actions
