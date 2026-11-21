"""Shared contracts between tracks. See PLAN section 6 and docs/CONTRACTS.md.

Anything imported by more than one track lives here. Change a contract only with the lead's agreement.
"""

from app.contracts.application import FORM_FIELDS, ApplicationFormV1, FieldValue, apply_patch
from app.contracts.common import Route, Strict
from app.contracts.decision import (
    CostMatrix,
    DecisionTrace,
    DecisionUserView,
    Explanation,
    HandoffPackage,
    Hypothesis,
    ReplayResult,
    RuleTraceItem,
    TypedDecision,
    UncertainField,
)
from app.contracts.documents import DocumentCheck, DocumentCitizenView, DocumentSignal, OcrResult, QrResult

__all__ = [
    "FORM_FIELDS",
    "ApplicationFormV1",
    "CostMatrix",
    "DecisionTrace",
    "DecisionUserView",
    "DocumentCheck",
    "DocumentCitizenView",
    "DocumentSignal",
    "Explanation",
    "FieldValue",
    "HandoffPackage",
    "Hypothesis",
    "OcrResult",
    "QrResult",
    "ReplayResult",
    "Route",
    "RuleTraceItem",
    "Strict",
    "TypedDecision",
    "UncertainField",
    "apply_patch",
]
