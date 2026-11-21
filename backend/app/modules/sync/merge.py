"""Field-level merge for edits made offline (PLAN 6.9). Pure functions with DB-free tests.

An offline edit says which version of the application it was made against (`base_version`). Since then,
other edits may have arrived from the web, another device, a signed card or an officer's correction.
Each of those writes an audit row that names the fields it changed and the version it produced. So:

* a field nobody changed since `base_version` takes the offline value;
* a field someone changed to the same value is already right (nothing to do);
* a field someone changed to a different value is a real conflict: the server keeps its value and the
  client gets both values for its conflict screen;
* a field read from a signed card (verified) is never overwritten from a device: also a conflict, with
  the reason `field_locked`, so the person can ask for a correction instead.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

# Audit actions that change form fields. Each one stores {"fields": [...], "version": n} in its details.
FIELD_CHANGE_ACTIONS: Final = ("application.updated", "application.fields_verified", "application.corrected")


@dataclass(frozen=True, slots=True)
class FieldConflict:
    field: str
    server_value: Any
    your_value: Any
    reason: str  # changed_since_your_version | field_locked

    def as_dict(self) -> dict[str, Any]:
        return {"field": self.field, "server_value": self.server_value, "your_value": self.your_value, "reason": self.reason}


@dataclass(slots=True)
class MergePlan:
    accepted: dict[str, Any] = field(default_factory=dict)  # field -> the client's entry, to merge
    unchanged: list[str] = field(default_factory=list)  # the server already holds the client's value
    conflicts: list[FieldConflict] = field(default_factory=list)


def fields_changed_after(details: Iterable[str | Mapping[str, Any]], base_version: int) -> set[str]:
    """Union of the fields changed by edits that produced a version above `base_version`.

    An entry without a readable version is counted as changed: unsure means "someone may have changed it".
    """
    changed: set[str] = set()
    for item in details:
        try:
            entry = json.loads(item) if isinstance(item, str) else dict(item)
        except (TypeError, ValueError):
            continue
        fields_ = entry.get("fields") or []
        try:
            version = int(entry["version"])
        except (KeyError, TypeError, ValueError):
            version = None
        if version is None or version > base_version:
            changed.update(str(f) for f in fields_ if isinstance(f, str))
    return changed


def _value_of(entry: Any) -> Any:
    return entry.get("value") if isinstance(entry, Mapping) else entry


def plan_patch(current: Mapping[str, Any], patch: Mapping[str, Any], *, changed: set[str], locked: set[str],
               normalise: Callable[[str, Any], Any] | None = None) -> MergePlan:  # fmt: skip
    """Decide field by field. `current` is the server's form as JSON; `patch` is the client's form patch."""
    norm = normalise or (lambda _name, value: value)
    plan = MergePlan()
    for name, entry in patch.items():
        if name == "language":
            server_lang = current.get("language")
            if entry == server_lang:
                plan.unchanged.append(name)
            elif name in changed:
                plan.conflicts.append(FieldConflict(name, server_lang, entry, "changed_since_your_version"))
            else:
                plan.accepted[name] = entry
            continue
        raw_server = current.get(name)
        server_entry: dict[str, Any] = dict(raw_server) if isinstance(raw_server, Mapping) else {}
        server_value = norm(name, _value_of(server_entry))
        your_value = norm(name, _value_of(entry))
        if name in locked:
            if server_value == your_value:
                plan.unchanged.append(name)
            else:
                plan.conflicts.append(FieldConflict(name, server_entry, _value_of(entry), "field_locked"))
        elif server_value == your_value:
            plan.unchanged.append(name)
        elif name in changed:
            plan.conflicts.append(FieldConflict(name, server_entry, _value_of(entry), "changed_since_your_version"))
        else:
            plan.accepted[name] = entry
    return plan
