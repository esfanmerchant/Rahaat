"""Shared integration-test setup for the people, consent, applications and documents modules.

`world` builds an isolated department with the Rahat program (rule version 1), a citizen with a full consent,
a helper with a delegation for that citizen, a second citizen and an officer.

`fakes` stands in for the other tracks' functions by putting modules into `sys.modules` at the exact
import paths from `app/contracts/engine.py`. Each fake returns the contract types and records its calls.
"""

from __future__ import annotations

import io
import sys
import types
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select

from app.contracts.decision import DecisionUserView, Explanation, HandoffPackage, TypedDecision
from app.contracts.documents import DocumentCheck, QrResult
from app.contracts.engine import DecisionInput, IdentityCheck, RegistryRecord
from app.core.config import get_settings
from app.core.db import system_session
from app.db import models
from app.seed import RULES_V1

ALL_SCOPES = ["identity", "contact", "household", "income", "documents"]


@dataclass
class World:
    tenant: Any
    program_id: uuid.UUID
    rule_version_id: uuid.UUID
    citizen: Any
    other_citizen: Any
    helper: Any
    officer: Any
    headers: dict[str, dict[str, str]] = field(default_factory=dict)

    def h(self, who: str, acting_for: uuid.UUID | None = None) -> dict[str, str]:
        headers = dict(self.headers[who])
        if acting_for is not None:
            headers["X-Acting-For"] = str(acting_for)
        return headers


def build_world(factory: Any, client: Any, *, helper_scopes: tuple[str, ...] = ("apply", "track", "upload")) -> World:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    other = factory.account(tenant, "citizen")
    helper = factory.account(tenant, "helper")
    officer = factory.account(tenant, "officer")
    with system_session() as db:
        program = models.Program(tenant_id=tenant.id, slug="rahat", name="Rahat (Prototype Relief Program)", name_ur="راحت")
        db.add(program)
        db.flush()
        rule_set = models.RuleSet(tenant_id=tenant.id, program_id=program.id, name="Rahat eligibility")
        db.add(rule_set)
        db.flush()
        version = models.RuleVersion(tenant_id=tenant.id, rule_set_id=rule_set.id, version_no=1, status="published", dsl=RULES_V1,
                                     description_en="Relief payment of Rs 12,000.", published_at=datetime.now(UTC))  # fmt: skip
        db.add(version)
        db.flush()
        rule_set.active_version_id = version.id
        for consent in db.scalars(select(models.Consent).where(models.Consent.tenant_id == tenant.id)).all():
            consent.field_scopes = list(ALL_SCOPES)
        db.add(models.HelperDelegation(tenant_id=tenant.id, helper_user_id=helper.user_id, person_id=citizen.person_id,
                                       scopes=list(helper_scopes), expires_at=datetime.now(UTC) + timedelta(days=30)))  # fmt: skip
        program_id, version_id = program.id, version.id
    world = World(tenant=tenant, program_id=program_id, rule_version_id=version_id, citizen=citizen, other_citizen=other,
                  helper=helper, officer=officer)  # fmt: skip
    for name in ("citizen", "other_citizen", "helper", "officer"):
        world.headers[name] = factory.headers(client, getattr(world, name))
    return world


def new_app(client: Any, world: World, who: str = "citizen", *, acting_for: uuid.UUID | None = None, form: dict[str, Any] | None = None,
            client_op_id: str | None = None) -> Any:  # fmt: skip
    body: dict[str, Any] = {"program_id": str(world.program_id), "client_op_id": client_op_id or uuid.uuid4().hex}
    if form is not None:
        body["form"] = form
    return client.post("/v1/applications", json=body, headers=world.h(who, acting_for))


def eligible_patch() -> dict[str, Any]:
    return {
        "household_size": {"value": 5, "provenance": "tapped"},
        "income_band": {"value": "under_15k", "provenance": "tapped"},
        "is_widow": {"value": True, "provenance": "tapped"},
        "has_disability": {"value": False, "provenance": "tapped"},
        "receives_other_aid": {"value": False, "provenance": "tapped"},
    }


def jpeg_bytes(size: tuple[int, int] = (320, 200), *, exif: bool = True) -> bytes:
    image = Image.new("RGB", size, (90, 140, 200))
    out = io.BytesIO()
    if exif:
        tags = Image.Exif()
        tags[0x010F] = "SpyCam Inc"
        tags[0x8825] = {2: (24.0, 51.0, 36.0)}
        image.save(out, format="JPEG", exif=tags.tobytes())
    else:
        image.save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture()
def uploads(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


# --- fakes for the other tracks ------------------------------------------------------------------------


class Fakes:
    """Configurable stand-ins. Set `outcome`, `doc_check` or `registry` before the call under test."""

    def __init__(self) -> None:
        self.calls: dict[str, list[dict[str, Any]]] = {}
        self.outcome = "needs_human"  # approved | rejected | needs_proof | needs_human
        self.engine_raises = False
        self.registry: tuple[str, RegistryRecord | None] = ("unavailable", None)
        self.identity = IdentityCheck(status="match", name_score=0.97)
        self.doc_quality = "ok"
        self.doc_qr_payload: dict[str, Any] | None = None
        self.doc_genuine = True

    def record(self, name: str, **kwargs: Any) -> None:
        self.calls.setdefault(name, []).append(kwargs)

    def n(self, name: str) -> int:
        return len(self.calls.get(name, []))

    # Track B
    def decide_and_record(self, db: Any, *, tenant_id: uuid.UUID, application_id: uuid.UUID, person_id: uuid.UUID,
                          inp: DecisionInput, actor_user_id: uuid.UUID | None = None) -> models.Decision:  # fmt: skip
        assert isinstance(inp, DecisionInput)
        self.record("decide_and_record", inp=inp, application_id=application_id, person_id=person_id)
        if self.engine_raises:
            db.add(models.Case(tenant_id=tenant_id, kind="application_review"))  # a partial write that must roll back
            db.flush()
            raise RuntimeError("engine exploded")
        route = {"approved": "auto", "rejected": "auto", "needs_proof": "ask_more"}.get(self.outcome, "human")
        application = db.get(models.Application, application_id)
        version_id = db.scalar(select(models.RuleSet.active_version_id).where(models.RuleSet.program_id == application.program_id))
        handoff = HandoffPackage(question="q", understanding="u", resolving_proof="income_proof").model_dump(mode="json")
        decision = models.Decision(
            tenant_id=tenant_id, application_id=application_id, person_id=person_id, rule_version_id=version_id,
            model_version="fake-1", input_snapshot=inp.model_dump(mode="json"), input_hash="0" * 64, route=route,
            outcome=self.outcome, reasons=[f"FAKE_{self.outcome.upper()}"], guards=["identity_mismatch"] if inp.identity and
            inp.identity.status == "mismatch" else [], p_ok=0.5, handoff=handoff if route != "auto" else None,
            explanation=Explanation(reason_codes=[f"FAKE_{self.outcome.upper()}"], lang="en", sentences=["Fake."]).model_dump(),
        )  # fmt: skip
        db.add(decision)
        db.flush()
        return decision

    def user_view(self, decision: models.Decision) -> DecisionUserView:
        return DecisionUserView(decision_id=str(decision.id), outcome=decision.outcome, route=decision.route,  # type: ignore[arg-type]
                                explanation=Explanation.model_validate(decision.explanation), rule_version_no=1,
                                decided_at=decision.created_at.isoformat())  # fmt: skip

    # Track C
    def check_document(self, image_bytes: bytes, kind: str, *, document_id: str) -> DocumentCheck:
        self.record("check_document", image_bytes=image_bytes, kind=kind, document_id=document_id)
        qr = QrResult(found=self.doc_qr_payload is not None, signature_valid=True if self.doc_qr_payload else None,
                      issuer_key_id="mock-issuer-1" if self.doc_qr_payload else None, payload=self.doc_qr_payload)  # fmt: skip
        return DocumentCheck(
            document_id=document_id, kind=kind, quality=self.doc_quality, qr=qr,  # type: ignore[arg-type]
            authenticity=TypedDecision(choice="genuine" if self.doc_genuine else "suspect", confidence=0.95,
                                       route="auto" if self.doc_genuine else "human", model_version="fake-docs"),  # fmt: skip
            signals=[], model_version="fake-docs",
        )

    # Track A (other agents)
    def verify_identity(self, national_id: str, full_name: str, dob: str) -> IdentityCheck:
        self.record("verify_identity", national_id=national_id)
        return self.identity

    def lookup_registry(self, national_id: str) -> tuple[str, RegistryRecord | None]:
        self.record("lookup_registry", national_id=national_id)
        return self.registry

    def open_case(self, db: Any, *, tenant_id: uuid.UUID, kind: str, opened_reason: str, application_id: uuid.UUID | None = None,
                  person_id: uuid.UUID | None = None, decision_id: uuid.UUID | None = None, handoff: HandoffPackage | None = None,
                  confidence: float | None = None, priority: int = 50) -> models.Case:  # fmt: skip
        self.record("open_case", kind=kind, opened_reason=opened_reason, application_id=application_id, decision_id=decision_id,
                    handoff=handoff)  # fmt: skip
        case = models.Case(tenant_id=tenant_id, kind=kind, opened_reason=opened_reason, application_id=application_id,
                           subject_person_id=person_id, decision_id=decision_id, priority=priority)  # fmt: skip
        db.add(case)
        db.flush()
        return case

    def request_payment(self, db: Any, *, tenant_id: uuid.UUID, application_id: uuid.UUID, person_id: uuid.UUID,
                        decision_id: uuid.UUID, amount_pkr: int, requested_by: uuid.UUID | None = None) -> models.Payment:  # fmt: skip
        self.record("request_payment", application_id=application_id, decision_id=decision_id, amount_pkr=amount_pkr)
        payment = models.Payment(tenant_id=tenant_id, application_id=application_id, person_id=person_id, decision_id=decision_id,
                                 amount_pkr=amount_pkr, idempotency_key=f"decision:{decision_id}")  # fmt: skip
        db.add(payment)
        db.flush()
        return payment

    def notify(self, db: Any, *, tenant_id: uuid.UUID, person_id: uuid.UUID | None, template: str, payload: dict[str, Any],
               lang: str | None = None, channels: tuple[str, ...] = ("in_app", "sms")) -> list[models.Notification]:  # fmt: skip
        self.record("notify", template=template, payload=payload)
        return []


_MODULES = {
    "app.modules.decision.service": ("decide_and_record", "user_view"),
    "app.modules.docs_ai.service": ("check_document",),
    "app.modules.integrations.service": ("verify_identity", "lookup_registry"),
    "app.modules.cases.service": ("open_case",),
    "app.modules.payments.service": ("request_payment",),
    "app.modules.notifications.service": ("notify",),
}


def install(monkeypatch: pytest.MonkeyPatch, fakes: Fakes, *, only: tuple[str, ...] | None = None) -> None:
    """Put fake modules at the real import paths. `only` limits which modules exist (the rest stay missing)."""
    for path, names in _MODULES.items():
        if only is not None and path not in only:
            monkeypatch.setitem(sys.modules, path, None)  # makes `import` raise ImportError, even after a merge
            continue
        parent = path.rsplit(".", 1)[0]
        monkeypatch.setitem(sys.modules, parent, types.ModuleType(parent))
        module = types.ModuleType(path)
        for name in names:
            setattr(module, name, getattr(fakes, name))
        monkeypatch.setitem(sys.modules, path, module)


@pytest.fixture()
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fakes]:
    f = Fakes()
    install(monkeypatch, f)
    yield f


@pytest.fixture()
def no_hooks(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    """Every other track missing, as in this worktree before integration."""
    f = Fakes()
    install(monkeypatch, f, only=())
    return f


@pytest.fixture()
def world(factory: Any, client: Any) -> World:
    return build_world(factory, client)
