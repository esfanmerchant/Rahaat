"""Test helpers: applications, decisions and cases made directly with the models (the applications API is Track A's other agent's)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.contracts.application import ApplicationFormV1, FieldValue
from app.contracts.decision import HandoffPackage, Hypothesis, UncertainField
from app.core.db import system_session
from app.db import models
from app.modules.cases.service import open_case


def program(tenant_id: uuid.UUID, *, payment_pkr: int = 12_000) -> tuple[uuid.UUID, uuid.UUID]:
    """A program with an active rule version. Returns (program_id, rule_version_id)."""
    with system_session() as db:
        prog = models.Program(id=uuid.uuid4(), tenant_id=tenant_id, slug=f"p-{uuid.uuid4().hex[:8]}", name="Test relief program")
        db.add(prog)
        db.flush()
        rule_set = models.RuleSet(id=uuid.uuid4(), tenant_id=tenant_id, program_id=prog.id, name="Test rules")
        db.add(rule_set)
        db.flush()
        version = models.RuleVersion(id=uuid.uuid4(), tenant_id=tenant_id, rule_set_id=rule_set.id, version_no=1, status="published",
                                     dsl={"payment_pkr": payment_pkr, "all": []})  # fmt: skip
        db.add(version)
        db.flush()
        rule_set.active_version_id = version.id
        return prog.id, version.id


def form(**overrides: Any) -> dict[str, Any]:
    base = ApplicationFormV1(
        full_name=FieldValue[str](value="Test Citizen", confidence=0.9, provenance="typed"),
        household_size=FieldValue[int](value=5, confidence=0.8, provenance="spoken"),
        payout_account=FieldValue[str](value="mock-wallet-0042", confidence=1.0, provenance="typed"),
    )
    data = base.model_dump(mode="json")
    data.update(overrides)
    return data


def application(tenant_id: uuid.UUID, person_id: uuid.UUID, program_id: uuid.UUID, *, status: str = "in_review") -> uuid.UUID:
    with system_session() as db:
        row = models.Application(id=uuid.uuid4(), tenant_id=tenant_id, program_id=program_id, person_id=person_id, status=status,
                                 form=form(), tracking_code=f"R-{uuid.uuid4().int % 100000:05d}", submitted_at=datetime.now(UTC))  # fmt: skip
        db.add(row)
        db.flush()
        return row.id


def decision(tenant_id: uuid.UUID, application_id: uuid.UUID, person_id: uuid.UUID, rule_version_id: uuid.UUID, *,
             outcome: str = "needs_human", route: str = "human", p_ok: float = 0.81) -> uuid.UUID:  # fmt: skip
    with system_session() as db:
        row = models.Decision(id=uuid.uuid4(), tenant_id=tenant_id, application_id=application_id, person_id=person_id,
                              rule_version_id=rule_version_id, model_version="test-model", input_hash="0" * 64, route=route,
                              outcome=outcome, p_ok=p_ok, probabilities={"p_eligible": 0.83, "p_genuine": 0.98})  # fmt: skip
        db.add(row)
        db.flush()
        return row.id


def handoff() -> HandoffPackage:
    return HandoffPackage(
        question="Is this household eligible?", understanding="Identity confirmed; income has no registry record.",
        uncertain_fields=[UncertainField(field="verified_income_pkr", value=None, confidence=0.0, why="missing_in_registry")],
        rule_fired="income_cap", hypotheses=[Hypothesis(label="eligible", probability=0.81), Hypothesis(label="income_above_cap", probability=0.19)],
        resolving_proof="income_proof", expected_costs={"approve": 19.0, "human": 3.2},
    )  # fmt: skip


def review_case(tenant_id: uuid.UUID, person_id: uuid.UUID, *, payment_pkr: int = 12_000, outcome: str = "needs_human") -> dict[str, uuid.UUID]:
    """An application under review with its decision and an open application_review case."""
    program_id, version_id = program(tenant_id, payment_pkr=payment_pkr)
    application_id = application(tenant_id, person_id, program_id)
    decision_id = decision(tenant_id, application_id, person_id, version_id, outcome=outcome)
    with system_session() as db:
        case = open_case(db, tenant_id=tenant_id, kind="application_review", opened_reason="income_unverified", application_id=application_id,
                         person_id=person_id, decision_id=decision_id, handoff=handoff(), confidence=0.81, priority=40)  # fmt: skip
        case_id = case.id
    return {"case_id": case_id, "application_id": application_id, "decision_id": decision_id, "program_id": program_id,
            "rule_version_id": version_id}  # fmt: skip


def set_consent(person_id: uuid.UUID, status: str) -> None:
    with system_session() as db:
        db.execute(update(models.Consent).where(models.Consent.person_id == person_id)
                   .values(status=status, withdrawn_at=datetime.now(UTC) if status == "withdrawn" else None))  # fmt: skip


def set_limit(tenant_id: uuid.UUID, limit_pkr: int) -> None:
    with system_session() as db:
        tenant = db.get(models.Tenant, tenant_id)
        assert tenant is not None
        tenant.config = {**(tenant.config or {}), "payment_four_eyes_limit_pkr": limit_pkr}


def get(model: Any, row_id: uuid.UUID) -> Any:
    with system_session() as db:
        row = db.get(model, row_id)
        if row is not None:
            db.expunge(row)
        return row


def rows(model: Any, *where: Any) -> list[Any]:
    with system_session() as db:
        found = list(db.scalars(select(model).where(*where)).all())
        for row in found:
            db.expunge(row)
        return found
