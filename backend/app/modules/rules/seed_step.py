"""Seed: propose rule version 2 from the threshold analysis, as a draft for the four-eyes flow. Idempotent.

The analysis (B7) found that an income record older than a year is the largest avoidable reason an
eligible family is sent to a person. Version 2 lets such a record settle the income cap when it is at most
half the cap: the household's income would have to double for the answer to change. On the held-out
labelled cases this removed 28 needless hand-offs and proof requests with no extra wrong approval.

It is only a draft. An admin runs it in the Digital Twin and asks for approval; a second admin publishes.
Version 1 stays as it is, so every decision made under it still replays exactly.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.db import models

ORDER = 60
PROPOSAL_PARAM: Final = "stale_income_settles_below"
PROPOSAL_VALUE: Final = 0.5
DESCRIPTION_EN: Final = (
    "Proposed from the threshold analysis: an income record older than a year still settles the income cap when it is at "
    "most half the cap, because the household's income would have to double for the answer to change. Measured on 1,223 "
    "held-out labelled cases: 28 fewer eligible families sent to a person or asked for proof, no extra wrong approval."
)
DESCRIPTION_UR: Final = (
    "حد سے آدھی یا کم آمدنی کا ایک سال سے پرانا ریکارڈ بھی آمدنی کی شرط کے لیے کافی ہوگا، کیونکہ جواب بدلنے کے لیے گھرانے کی آمدنی دگنی ہونی چاہیے۔"
)


def proposed_dsl(dsl: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dsl)
    body["params"] = {**(body.get("params") or {}), PROPOSAL_PARAM: PROPOSAL_VALUE}
    return body


def seed(db: Session) -> None:
    rule_sets = db.scalars(
        select(models.RuleSet).join(models.Tenant, models.Tenant.id == models.RuleSet.tenant_id).where(models.Tenant.kind == "department")
    ).all()
    for rule_set in rule_sets:
        if rule_set.active_version_id is None:
            continue
        versions = db.scalars(select(models.RuleVersion).where(models.RuleVersion.rule_set_id == rule_set.id)).all()
        if any(PROPOSAL_PARAM in ((v.dsl or {}).get("params") or {}) for v in versions):
            continue  # already proposed (or adopted)
        active = db.get(models.RuleVersion, rule_set.active_version_id)
        if active is None or PROPOSAL_PARAM in ((active.dsl or {}).get("params") or {}):
            continue
        number = int(db.scalar(select(func.max(models.RuleVersion.version_no)).where(models.RuleVersion.rule_set_id == rule_set.id)) or 0) + 1
        draft = models.RuleVersion(
            id=uuid.uuid4(), tenant_id=rule_set.tenant_id, rule_set_id=rule_set.id, version_no=number, status="draft",
            dsl=proposed_dsl(active.dsl), description_en=DESCRIPTION_EN, description_ur=DESCRIPTION_UR, parent_version_id=active.id,
            created_by=None, high_impact=True,
        )  # fmt: skip
        db.add(draft)
        db.flush()
        audit.write(db, tenant_id=rule_set.tenant_id, action="rules.draft_created", actor_type="system", object_type="rule_version",
                    object_id=draft.id, rule_version_id=draft.id,
                    details={"version_no": number, "parent_version_id": str(active.id), "source": "seed", "proposal": "b7_stale_income"})  # fmt: skip
