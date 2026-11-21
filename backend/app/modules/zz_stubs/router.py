"""Contract stubs for the spine API. Dev and test only; never loaded on a deployed instance.

Each stub answers with a fixed example of the agreed response shape (app/contracts/api.py), so the
frontend tracks can build against final paths before Track A's real endpoints land. This package sorts
last, so as soon as a real route with the same method and path exists it wins and the stub is dead code.
Delete a stub when its real endpoint is merged. Every stub response carries `X-Rahat-Stub: 1`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.contracts.api import (
    ApplicationCreate,
    ApplicationList,
    ApplicationOut,
    ApplicationPatch,
    ApplicationSummary,
    ConsentCreate,
    ConsentOut,
    DocumentOut,
    PersonOut,
    ProgramOut,
    RuleVersionBrief,
    SubmitOut,
    TimelineItem,
)
from app.contracts.application import ApplicationFormV1, FieldValue
from app.contracts.common import DocumentKind
from app.contracts.decision import (
    CostMatrix,
    DecisionTrace,
    DecisionUserView,
    Explanation,
    HandoffPackage,
    Hypothesis,
    RuleTraceItem,
    TypedDecision,
    UncertainField,
)
from app.contracts.documents import DocumentCheck, DocumentCitizenView, DocumentSignal, OcrResult, QrResult
from app.core.deps import ALL_ROLES, Principal
from app.core.mockdata import make_mock_id, mask_identifier
from app.core.policy import Policy


def _mark_stub(response: Response) -> None:
    response.headers["X-Rahat-Stub"] = "1"


router = APIRouter(prefix="/v1", tags=["stubs (dev only)"], dependencies=[Depends(_mark_stub)])

_T = "2026-11-21T09:00:00+00:00"
_PERSON = UUID("10000000-0000-4000-8000-000000000001")
_PROGRAM = UUID("20000000-0000-4000-8000-000000000001")
_RULES = UUID("20000000-0000-4000-8000-000000000002")
_APPLICATION = UUID("30000000-0000-4000-8000-000000000001")
_DOCUMENT = UUID("40000000-0000-4000-8000-000000000001")
_DECISION = UUID("50000000-0000-4000-8000-000000000001")
_CONSENT = UUID("70000000-0000-4000-8000-000000000001")
_TENANT = UUID("80000000-0000-4000-8000-000000000001")
_MOCK_ID = make_mock_id(1_000_201)

_citizen_side = Policy("stub:citizen", ["citizen", "helper"])
_review = Policy("stub:decision-read", ["officer", "auditor"])
_anyone = Policy("stub:any", ALL_ROLES)


def _form() -> ApplicationFormV1:
    return ApplicationFormV1(
        full_name=FieldValue[str](value="Zainab Bibi", confidence=0.99, provenance="qr_signed", verified=True),
        national_id=FieldValue[str](value=_MOCK_ID, confidence=0.99, provenance="qr_signed", verified=True),
        dob=FieldValue[str](value="1978-03-14", confidence=0.99, provenance="qr_signed", verified=True),
        gender=FieldValue[str](value="female", confidence=0.99, provenance="qr_signed", verified=True),
        district=FieldValue[str](value="Karachi East", confidence=0.95, provenance="tapped"),
        phone=FieldValue[str](value="0999-0000201", confidence=1.0, provenance="typed"),
        household_size=FieldValue[int](value=5, confidence=0.82, provenance="spoken"),
        income_band=FieldValue(value="15k_30k", confidence=0.9, provenance="tapped"),
        is_widow=FieldValue[bool](value=True, confidence=1.0, provenance="tapped"),
        has_disability=FieldValue[bool](value=False, confidence=1.0, provenance="tapped"),
        receives_other_aid=FieldValue[bool](value=False, confidence=0.97, provenance="registry", verified=True),
        language="ur",
    )


def _explanation() -> Explanation:
    return Explanation(
        reason_codes=["NEEDS_HUMAN_INCOME_UNVERIFIED"], lang="ur",
        sentences=["ہم آپ کی آمدنی کی تصدیق خود نہیں کر سکے۔", "اب ایک افسر آپ کی درخواست دیکھے گا۔"],
        next_step="آپ کو ابھی کچھ نہیں کرنا۔ دو دن میں پیغام آئے گا۔", ask_a_person=True,
        audio_keys=["reason.needs_human_income_unverified", "next.wait_two_days"], pictogram="person-will-help",
    )  # fmt: skip


def _user_view() -> DecisionUserView:
    return DecisionUserView(decision_id=str(_DECISION), outcome="needs_human", route="human", explanation=_explanation(),
                            rule_version_no=1, decided_at=_T)  # fmt: skip


def _handoff() -> HandoffPackage:
    return HandoffPackage(
        question="Is this household eligible for the Rahat payment?",
        understanding="Identity is confirmed by the signed card. Income is declared as Rs 15,000 to 30,000 and the "
                      "registry has no income record, so the income rule cannot be checked.",
        uncertain_fields=[
            UncertainField(field="verified_income_pkr", value=None, confidence=0.0, why="missing_in_registry"),
            UncertainField(field="household_size", value=5, confidence=0.82, why="spoken_not_verified"),
        ],
        rule_fired="income_cap",
        hypotheses=[Hypothesis(label="eligible", probability=0.81), Hypothesis(label="income_above_cap", probability=0.19)],
        resolving_proof="income_proof", suggested_question="Do you have a salary slip or a letter that shows your monthly income?",
        evidence={"document_ids": [str(_DOCUMENT)], "ocr_text": "RAHAT CARD SPECIMEN ZAINAB BIBI"},
        expected_costs={"approve": 19.0, "ask_proof": 2.6, "human": 3.2}, guards=[],
    )  # fmt: skip


def _document_check() -> DocumentCheck:
    return DocumentCheck(
        document_id=str(_DOCUMENT), kind="rahat_id", quality="ok",
        qr=QrResult(found=True, signature_valid=True, issuer_key_id="mock-issuer-1", payload={"name": "Zainab Bibi"}),
        ocr=OcrResult(fields={"name": "ZAINAB BIBI", "id": _MOCK_ID}, field_confidence={"name": 0.93, "id": 0.96},
                      mean_confidence=0.94, raw_text="RAHAT CARD SPECIMEN ZAINAB BIBI"),
        authenticity=TypedDecision(choice="genuine", probabilities={"genuine": 0.98, "suspect": 0.02}, confidence=0.98,
                                   route="auto", reasons=["qr_signature_valid", "ocr_matches_qr"], model_version="docs-ai-stub"),
        signals=[DocumentSignal(code="qr_signature_valid", weight=-2.0, staff_detail="Signed by mock-issuer-1")],
        model_version="docs-ai-stub",
    )  # fmt: skip


def _trace() -> DecisionTrace:
    costs = CostMatrix()
    return DecisionTrace(
        decision_id=str(_DECISION), application_id=str(_APPLICATION), route="human", outcome="needs_human",
        rule_version_id=str(_RULES), rule_version_no=1, model_version="evidence-lr-stub", engine_version="decide-1",
        input_hash="0" * 64, result_hash="1" * 64,
        input_snapshot={"national_id": mask_identifier(_MOCK_ID), "income_band": "15k_30k", "household_size": 5},
        rule_trace=[
            RuleTraceItem(rule_id="identity_verified", hard=True, result="pass", values_used={"identity_verified": True}, verified_inputs=True),
            RuleTraceItem(rule_id="income_cap", hard=True, result="unknown", values_used={"verified_income_pkr": None}),
            RuleTraceItem(rule_id="priority_group", hard=False, result="pass", values_used={"is_widow": True}),
        ],
        probabilities={"p_eligible": 0.83, "p_genuine": 0.98}, p_ok=0.8134, cost_matrix=costs,
        expected_costs={"approve": 18.66, "ask_proof": 2.6, "human": 3.2},
        thresholds={"approve": round(costs.approve_threshold(), 4), "reject": round(costs.reject_threshold(), 4)},
        reasons=["NEEDS_HUMAN_INCOME_UNVERIFIED"], guards=[], handoff=_handoff(), latency_ms=41, request_id="stub", decided_at=_T,
    )  # fmt: skip


def _application(status: str = "in_review") -> ApplicationOut:
    return ApplicationOut(
        id=_APPLICATION, person_id=_PERSON, program_id=_PROGRAM, program_name="Rahat (Prototype Relief Program)",
        status=status, tracking_code="R-48213", tracking_symbols=["moon", "star", "fish"], version=3, updated_at=_T,  # type: ignore[arg-type]
        form=_form(), missing_fields=["payout_account"],
        documents=[DocumentCitizenView(document_id=str(_DOCUMENT), kind="rahat_id", accepted=True, quality="ok", message_key="doc_ok")],
        decision=_user_view() if status != "draft" else None,
        timeline=[TimelineItem(at=_T, status="submitted", label_key="timeline.submitted"),
                  TimelineItem(at=_T, status="in_review", label_key="timeline.person_checking")],
    )  # fmt: skip


@router.get("/me/person", response_model=PersonOut, summary="[stub] My person record")
def my_person(_: Principal = Depends(_citizen_side)) -> PersonOut:
    return PersonOut(id=_PERSON, full_name="Zainab Bibi", full_name_ur="زینب بی بی", district="Karachi East",
                     national_id_masked=mask_identifier(_MOCK_ID), phone_masked=mask_identifier("0999-0000201"))  # fmt: skip


@router.get("/programs", response_model=list[ProgramOut], summary="[stub] Programs in this department")
def programs(_: Principal = Depends(_anyone)) -> list[ProgramOut]:
    brief = RuleVersionBrief(id=_RULES, version_no=1, description_en="Relief payment of Rs 12,000 for verified low-income households.",
                             description_ur="تصدیق شدہ کم آمدنی والے گھرانوں کے لیے 12,000 روپے کی امداد۔",
                             required_docs=["rahat_id"], payment_pkr=12000)  # fmt: skip
    name_ur = "راحت (آزمائشی امدادی پروگرام)"
    return [ProgramOut(id=_PROGRAM, slug="rahat", name="Rahat (Prototype Relief Program)", name_ur=name_ur, rule_version=brief)]


@router.get("/consents", response_model=list[ConsentOut], summary="[stub] Who has my data")
def consents(_: Principal = Depends(_citizen_side)) -> list[ConsentOut]:
    return [_consent("active")]


def _consent(status: str) -> ConsentOut:
    return ConsentOut(id=_CONSENT, person_id=_PERSON, grantee_type="tenant", grantee_id=_TENANT,
                      grantee_name="Sindh Social Protection Department (mock)", purpose="relief_application",
                      field_scopes=["identity", "contact", "household", "income", "documents"], status=status, version=1,
                      granted_at=_T, expires_at="2027-05-20T09:00:00+00:00", withdrawn_at=_T if status == "withdrawn" else None)  # fmt: skip


@router.post("/consents", response_model=ConsentOut, status_code=201, summary="[stub] Share my data for a purpose")
def grant_consent(body: ConsentCreate, _: Principal = Depends(_citizen_side)) -> ConsentOut:
    return _consent("active")


@router.post("/consents/{consent_id}/withdraw", response_model=ConsentOut, summary="[stub] Take my data back")
def withdraw_consent(consent_id: UUID, _: Principal = Depends(_citizen_side)) -> ConsentOut:
    return _consent("withdrawn")


@router.get("/applications", response_model=ApplicationList, summary="[stub] My applications")
def applications(_: Principal = Depends(_citizen_side)) -> ApplicationList:
    return ApplicationList(items=[ApplicationSummary(**_application().model_dump(include=set(ApplicationSummary.model_fields)))])


@router.post("/applications", response_model=ApplicationOut, status_code=201, summary="[stub] Start an application")
def create_application(body: ApplicationCreate, _: Principal = Depends(_citizen_side)) -> ApplicationOut:
    return _application("draft")


@router.get("/applications/{application_id}", response_model=ApplicationOut, summary="[stub] One application with its timeline")
def get_application(application_id: UUID, _: Principal = Depends(_citizen_side)) -> ApplicationOut:
    return _application()


@router.patch("/applications/{application_id}", response_model=ApplicationOut, summary="[stub] Save answers")
def patch_application(application_id: UUID, body: ApplicationPatch, _: Principal = Depends(_citizen_side)) -> ApplicationOut:
    return _application("draft")


@router.post("/applications/{application_id}/submit", response_model=SubmitOut, summary="[stub] Submit and get the decision")
def submit_application(application_id: UUID, _: Principal = Depends(_citizen_side)) -> SubmitOut:
    return SubmitOut(application=_application(), decision=_user_view())


@router.post("/applications/{application_id}/documents", response_model=DocumentOut, status_code=201, summary="[stub] Upload an ID or proof")
def upload_document(application_id: UUID, file: UploadFile = File(...), kind: DocumentKind = Form("rahat_id"),
                    _: Principal = Depends(_citizen_side)) -> DocumentOut:  # fmt: skip
    return DocumentOut(document=DocumentCitizenView(document_id=str(_DOCUMENT), kind=kind, accepted=True, quality="ok", message_key="doc_ok"),
                       application_version=4)  # fmt: skip


@router.get("/decisions/{decision_id}", summary="[stub] A decision: the citizen's reason and the auditor's trace")
def get_decision(decision_id: UUID, _: Principal = Depends(_review)) -> dict[str, DecisionUserView | DecisionTrace]:
    return {"user_view": _user_view(), "trace": _trace()}
