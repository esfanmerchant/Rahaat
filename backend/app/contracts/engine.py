"""The decision pipeline's cross-track interface (PLAN 6.1).

Track A gathers evidence and builds a `DecisionInput`. Track B's engine turns it into a `DecisionResult`.
Track C produces the `DocumentCheck` objects inside the input. Nothing else crosses these boundaries, so
each track can be built and tested on its own.

The functions that go with these shapes (exact import paths, so integration is one import):

    app.modules.decision.engine.decide(inp, rules, costs, model) -> DecisionResult            (B, pure)
    app.modules.decision.service.decide_and_record(db, *, tenant_id, application_id,
            person_id, inp, actor_user_id=None) -> models.Decision                            (B)
    app.modules.decision.service.user_view(decision) -> DecisionUserView                      (B)
    app.modules.decision.service.trace_view(db, decision, *, redact) -> DecisionTrace         (B)
    app.modules.rules.service.get_active(db, program_id) -> RuleSetSnapshot                   (B)
    app.modules.docs_ai.service.check_document(image_bytes, kind, *, document_id)
            -> DocumentCheck                                                                  (C)
    app.modules.integrations.service.verify_identity(national_id, full_name, dob)
            -> IdentityCheck                                                                  (A)
    app.modules.integrations.service.lookup_registry(national_id)
            -> tuple[RegistryStatus, RegistryRecord | None]                                   (A)
    app.modules.cases.service.open_case(db, *, tenant_id, kind, opened_reason,
            application_id=None, person_id=None, decision_id=None, handoff=None,
            confidence=None, priority=50) -> models.Case                                      (A)
    app.modules.payments.service.request_payment(db, *, tenant_id, application_id, person_id,
            decision_id, amount_pkr, requested_by=None) -> models.Payment                     (A)
    app.modules.notifications.service.notify(db, *, tenant_id, person_id, template, payload,
            lang=None, channels=("in_app", "sms")) -> list[models.Notification]               (A)
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.contracts.application import ApplicationFormV1
from app.contracts.common import DecisionOutcome, Lang, Route
from app.contracts.decision import Explanation, HandoffPackage, RuleTraceItem
from app.contracts.documents import DocumentCheck

IdentityStatus = Literal["match", "partial", "mismatch", "not_found", "unavailable"]
RegistryStatus = Literal["found", "not_found", "unavailable"]


class IdentityCheck(BaseModel):
    """The (mock) identity service's answer to: do this ID, name and date of birth belong to one record?"""

    status: IdentityStatus
    name_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Name similarity reported by the service")
    checked_at: str | None = None


class RegistryRecord(BaseModel):
    """What the (mock) data-exchange registry holds about a person. Verified, but possibly missing or stale."""

    national_id: str
    full_name: str | None = None
    dob: str | None = None
    gender: str | None = None
    district: str | None = None
    household_size: int | None = None
    verified_income_pkr: int | None = Field(default=None, description="None when the registry has no income record")
    income_as_of: str | None = Field(default=None, description="ISO date of the income record; old records are less certain")
    receives_other_aid: bool | None = None
    is_widow: bool | None = None
    has_disability: bool | None = None
    record_version: str = "1"


class DuplicateEvidence(BaseModel):
    """Result of dedupe (Phase 2). `possible` is a guard: the case goes to a human, never to a merge."""

    band: Literal["same", "possible", "distinct"]
    score: float
    other_person_ref: str | None = None


class AnomalyEvidence(BaseModel):
    """Result of anomaly detection (Phase 3). A flagged case is a guard."""

    score: float
    flagged: bool
    reasons: list[str] = Field(default_factory=list)


class DecisionInput(BaseModel):
    """Everything the engine may look at. Stored with the decision, hashed, and replayed bit for bit."""

    schema_version: str = "1"
    application_id: str
    program_slug: str
    lang: Lang = "ur"
    form: ApplicationFormV1
    documents: list[DocumentCheck] = Field(default_factory=list)
    identity: IdentityCheck | None = Field(default=None, description="None when no identity check was attempted")
    registry_status: RegistryStatus = "unavailable"
    registry: RegistryRecord | None = None
    duplicate: DuplicateEvidence | None = None
    anomaly: AnomalyEvidence | None = None
    consent_ok: bool = True
    queue_days: float = Field(default=1.0, ge=0, description="Expected wait for a human, from the live queue")
    decided_at: str = Field(description="Supplied by the caller. The engine never reads the clock.")


class RuleSetSnapshot(BaseModel):
    """One immutable rule version, as the engine receives it."""

    rule_version_id: str
    version_no: int
    dsl: dict[str, Any]
    content_hash: str | None = None


class Fact(BaseModel):
    """One rule variable as the engine resolved it from the input."""

    value: Any | None = None
    known: bool = False
    verified: bool = Field(default=False, description="True only when the value came from a signed QR or the registry")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["form", "registry", "document", "identity", "derived", "none"] = "none"


class EvidenceProbabilities(BaseModel):
    p_eligible: float = Field(ge=0.0, le=1.0)
    p_genuine: float = Field(ge=0.0, le=1.0)


class EvidenceModel(Protocol):
    """A calibrated model. Deterministic for a given version, so a replay gives the same numbers."""

    @property
    def version(self) -> str: ...

    def predict(self, features: dict[str, float]) -> EvidenceProbabilities: ...


class DecisionResult(BaseModel):
    route: Route
    outcome: DecisionOutcome
    p_eligible: float
    p_genuine: float
    p_ok: float
    probabilities: dict[str, float]
    expected_costs: dict[str, float] = Field(description="Expected cost of each action that was allowed")
    thresholds: dict[str, float]
    facts: dict[str, Fact]
    rule_trace: list[RuleTraceItem]
    reasons: list[str] = Field(description="Reason codes. The first one is the main reason.")
    guards: list[str] = Field(default_factory=list, description="Hard guards that forced a human, e.g. identity_mismatch")
    ask_proof: str | None = Field(default=None, description="The one proof to ask for when route is ask_more")
    handoff: HandoffPackage | None = None
    explanation: Explanation
    payment_pkr: int | None = Field(default=None, description="Amount from the rule version, when approved")
    model_version: str
    engine_version: str
    rule_version_id: str
    rule_version_no: int
    input_hash: str
    result_hash: str = Field(description="Hash of everything above. A replay must reproduce it exactly.")
