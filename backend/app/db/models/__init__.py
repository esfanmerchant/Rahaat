"""All tables. Import models from here: `from app.db import models`."""

from app.db.base import Base
from app.db.models.casework import Appeal, Application, Case, CaseEvent, CaseNote, Document, DocumentCheck, Program
from app.db.models.identity import AuthSession, Membership, Plan, Tenant, User
from app.db.models.intelligence import (
    AgentRun,
    AgentStep,
    EvalRun,
    FeedbackLabel,
    KbChunk,
    KbDocument,
    MemoryItem,
    ModelRegistry,
    PublicWarning,
    ScamCluster,
    ScamReport,
    TakedownRequest,
    TwinRun,
)
from app.db.models.people import (
    Consent,
    ConsentEvent,
    CorrectionRequest,
    DuplicateCandidate,
    HelperDelegation,
    HouseholdLink,
    NameVariant,
    Person,
    PersonIdentifier,
)
from app.db.models.platform import (
    ApiKey,
    Job,
    Notification,
    Payment,
    ReconciliationItem,
    SyncOp,
    UsageCounter,
    UssdSession,
    Webhook,
    WebhookDelivery,
)
from app.db.models.rules import Approval, Decision, HumanReview, PolicyDocument, RuleSet, RuleVersion
from app.db.models.trail import AuditAnchor, AuditLog, SecurityEvent

# Tables without tenant_id. Everything else is tenant-scoped and gets the generic RLS policy.
GLOBAL_TABLES = ("plans", "tenants", "users", "sessions")

# Tables holding a person's data. They get an extra restrictive policy that checks consent.
PERSON_TABLES = {
    "persons": "id",
    "applications": "person_id",
    "documents": "person_id",
    "document_checks": "person_id",
    "memory_items": "person_id",
}

# Tables the app role may only INSERT into and SELECT from.
APPEND_ONLY_TABLES = ("audit_log", "audit_anchors", "consent_events")

__all__ = [
    "APPEND_ONLY_TABLES",
    "GLOBAL_TABLES",
    "PERSON_TABLES",
    "AgentRun",
    "AgentStep",
    "ApiKey",
    "Appeal",
    "Application",
    "Approval",
    "AuditAnchor",
    "AuditLog",
    "AuthSession",
    "Base",
    "Case",
    "CaseEvent",
    "CaseNote",
    "Consent",
    "ConsentEvent",
    "CorrectionRequest",
    "Decision",
    "Document",
    "DocumentCheck",
    "DuplicateCandidate",
    "EvalRun",
    "FeedbackLabel",
    "HelperDelegation",
    "HouseholdLink",
    "HumanReview",
    "Job",
    "KbChunk",
    "KbDocument",
    "Membership",
    "MemoryItem",
    "ModelRegistry",
    "NameVariant",
    "Notification",
    "Payment",
    "Person",
    "PersonIdentifier",
    "Plan",
    "PolicyDocument",
    "Program",
    "PublicWarning",
    "ReconciliationItem",
    "RuleSet",
    "RuleVersion",
    "ScamCluster",
    "ScamReport",
    "SecurityEvent",
    "SyncOp",
    "TakedownRequest",
    "Tenant",
    "TwinRun",
    "UsageCounter",
    "UssdSession",
    "User",
    "Webhook",
    "WebhookDelivery",
]
