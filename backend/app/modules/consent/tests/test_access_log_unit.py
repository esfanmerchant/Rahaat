"""DB-free tests of how one audit row reads in the person's access log."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.consent.access_log import VIEW_ACTION, AuditFacts, entry_for

AT = datetime(2026, 11, 21, 18, 30, tzinfo=UTC)


def _row(action: str, *, role: str | None, result: str = "ok", reason: str | None = None, details: dict | None = None,
         actor_type: str = "user", actor_id: str | None = "u-1") -> AuditFacts:  # fmt: skip
    return AuditFacts(seq=7, ts=AT, action=action, actor_type=actor_type, actor_id=actor_id, actor_role=role, result=result,
                      reason=reason, details=details or {})  # fmt: skip


def test_an_officer_read_shows_role_and_department_never_a_name() -> None:
    entry = entry_for(_row(VIEW_ACTION, role="officer", reason="case_review", details={"what": "case_detail"}),
                      department="Sindh Social Protection Department (mock)", helper_names={"u-1": "Should not appear"})  # fmt: skip
    assert entry.event == "viewed" and entry.allowed is True and entry.what == "case_detail" and entry.reason == "case_review"
    assert entry.actor_kind == "staff" and entry.actor_role == "officer" and entry.actor_name is None
    assert entry.department == "Sindh Social Protection Department (mock)" and entry.at == "2026-11-21T18:30:00+00:00"


def test_a_refused_attempt_is_shown_as_denied_with_its_reason() -> None:
    entry = entry_for(_row("access.denied", role="officer", result="denied", reason="consent_required", details={"attempted": "document_content"}),
                      department="D", helper_names={})  # fmt: skip
    assert entry.event == "denied" and entry.allowed is False and entry.reason == "consent_required" and entry.what == "document_content"


def test_helpers_are_named_and_partner_systems_are_labelled() -> None:
    helper = entry_for(_row("helper.switched", role="helper"), department="D", helper_names={"u-1": "Rubina Shaikh"})
    assert helper.event == "helper_opened" and helper.actor_kind == "helper" and helper.actor_name == "Rubina Shaikh"
    acted = entry_for(_row("application.updated", role="helper"), department="D", helper_names={"u-1": "Rubina Shaikh"})
    assert acted.event == "helper_acted" and acted.what == "application.updated"
    wrong_pin = entry_for(_row("helper.switch_denied", role="helper", result="denied", reason="wrong_pin"), department="D",
                          helper_names={"u-1": "Rubina Shaikh"})  # fmt: skip
    assert wrong_pin.event == "denied" and wrong_pin.reason == "wrong_pin" and wrong_pin.actor_name == "Rubina Shaikh"
    partner = entry_for(_row(VIEW_ACTION, role="api_client", actor_type="api_key", details={"what": "person_record"}), department="D",
                        helper_names={})  # fmt: skip
    assert partner.actor_kind == "partner" and partner.actor_name is None
    system = entry_for(_row(VIEW_ACTION, role=None, actor_type="system", actor_id=None), department="D", helper_names={})
    assert system.actor_kind == "system" and system.actor_role is None
