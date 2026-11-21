"""DB-free tests: status machine, the client trust rule, required fields, signed-card merge, tracking codes, timeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.contracts.application import ApplicationFormV1, FieldValue
from app.core.errors import Conflict, Unprocessable
from app.core.mockdata import make_mock_id
from app.modules.applications import forms, status, timeline
from app.seed import RULES_V1

MOCK_ID = make_mock_id(1_000_201)


# --- status machine ----------------------------------------------------------------------------------


def test_status_machine_allows_the_happy_paths() -> None:
    for a, b in [("draft", "submitted"), ("submitted", "approved"), ("approved", "paid"), ("submitted", "needs_proof"),
                 ("needs_proof", "submitted"), ("submitted", "in_review"), ("in_review", "rejected"), ("rejected", "in_review"),
                 ("in_review", "on_hold_consent"), ("on_hold_consent", "in_review")]:  # fmt: skip
        assert status.can_move(a, b), f"{a} -> {b} should be allowed"


@pytest.mark.parametrize(("a", "b"), [("draft", "paid"), ("draft", "approved"), ("paid", "draft"), ("withdrawn", "draft"),
                                      ("rejected", "approved"), ("submitted", "draft"), ("paid", "on_hold_consent")])  # fmt: skip
def test_status_machine_refuses_illegal_jumps(a: str, b: str) -> None:
    class App:
        status = a

    app = App()
    with pytest.raises(Conflict) as err:
        status.move(app, b)
    assert err.value.code == "invalid_transition" and app.status == a


def test_every_status_is_in_the_machine() -> None:
    from typing import get_args

    from app.contracts.common import ApplicationStatus

    assert set(status.TRANSITIONS) == set(get_args(ApplicationStatus))
    assert all(target in status.TRANSITIONS for targets in status.TRANSITIONS.values() for target in targets)


def test_resume_after_hold_goes_back_or_to_a_person() -> None:
    assert status.resume_status("needs_proof", submitted=True) == "needs_proof"
    assert status.resume_status(None, submitted=True) == "in_review"
    assert status.resume_status(None, submitted=False) == "draft"
    assert status.resume_status("paid", submitted=True) == "in_review", "a hold never resumes into a state it could not come from"


# --- trust rule ----------------------------------------------------------------------------------------


def _codes(errors: list[forms.FieldError]) -> set[str]:
    return {e.code for e in errors}


@pytest.mark.parametrize("provenance", ["qr_signed", "registry", "ocr", "made_up"])
def test_client_cannot_send_server_provenance(provenance: str) -> None:
    errors = forms.check_client_patch({"full_name": {"value": "Zainab Bibi", "provenance": provenance}}, ApplicationFormV1())
    assert "provenance_not_allowed" in _codes(errors)


def test_client_cannot_mark_a_value_verified() -> None:
    errors = forms.check_client_patch({"household_size": {"value": 5, "provenance": "tapped", "verified": True}}, ApplicationFormV1())
    assert "verified_not_allowed" in _codes(errors)
    with pytest.raises(Unprocessable) as err:
        forms.merge_client_patch(ApplicationFormV1(), {"household_size": {"value": 5, "provenance": "tapped", "verified": True}})
    assert err.value.status == 422 and err.value.extra["errors"][0]["field"].startswith("form_patch.household_size")


def test_whole_form_at_creation_follows_the_same_rule() -> None:
    form = ApplicationFormV1(full_name=FieldValue[str](value="Zainab Bibi", confidence=1.0, provenance="qr_signed", verified=True))
    assert _codes(forms.check_client_form(form)) == {"provenance_not_allowed", "verified_not_allowed"}
    assert forms.check_client_form(ApplicationFormV1(household_size=FieldValue[int](value=4, confidence=1.0, provenance="spoken"))) == []


def test_a_verified_field_is_locked_against_client_edits() -> None:
    form = forms.merge_signed(ApplicationFormV1(), {"full_name": "Zainab Bibi"})
    errors = forms.check_client_patch({"full_name": {"value": "Someone Else", "provenance": "typed"}}, form)
    assert "field_locked" in _codes(errors)


def test_unknown_fields_and_shapes_are_repairable_errors() -> None:
    errors = forms.check_client_patch({"salary": {"value": 1}, "district": "Karachi", "gender": {"value": "f", "is_admin": True}},
                                      ApplicationFormV1())  # fmt: skip
    assert {e.field for e in errors} == {"form_patch.salary", "form_patch.district", "form_patch.gender"}
    assert _codes(errors) == {"unknown_field", "field_value_shape"}


def test_only_mock_identifier_formats_are_accepted() -> None:
    real_looking = forms.check_client_patch({"national_id": {"value": "42101-1234567-1", "provenance": "typed"}}, ApplicationFormV1())  # mock-lint: allow
    assert "mock_id_format" in _codes(real_looking)
    bad_digit = MOCK_ID[:-1] + str((int(MOCK_ID[-1]) + 1) % 10)
    assert "mock_id_check_digit" in _codes(forms.check_client_patch({"national_id": {"value": bad_digit}}, ApplicationFormV1()))
    assert "mock_phone_format" in _codes(forms.check_client_patch({"phone": {"value": "0300-1234567"}}, ApplicationFormV1()))  # mock-lint: allow
    assert forms.check_client_patch({"national_id": {"value": MOCK_ID}, "phone": {"value": "0999-0000201"}}, ApplicationFormV1()) == []


def test_merge_validates_types_and_defaults_tapped_confidence() -> None:
    form = forms.merge_client_patch(ApplicationFormV1(), {"household_size": {"value": 6, "provenance": "tapped"},
                                                          "phone": {"value": "09990000201", "provenance": "typed"}, "language": "en"})  # fmt: skip
    assert form.household_size.value == 6 and form.household_size.confidence == 1.0 and not form.household_size.verified
    assert form.phone.value == "0999-0000201" and form.language == "en"
    spoken = forms.merge_client_patch(ApplicationFormV1(), {"household_size": {"value": 6, "provenance": "spoken"}})
    assert spoken.household_size.confidence == 0.0, "a spoken answer keeps the recogniser's score; none was sent"
    with pytest.raises(Unprocessable):
        forms.merge_client_patch(ApplicationFormV1(), {"household_size": {"value": "many", "provenance": "tapped"}})
    with pytest.raises(Unprocessable):
        forms.merge_client_patch(ApplicationFormV1(), {"dob": {"value": "31/01/1980"}})


# --- required fields from the rule DSL ----------------------------------------------------------------


def test_required_fields_walk_the_dsl() -> None:
    assert forms.required_fields(RULES_V1) == ["income_band", "receives_other_aid", "is_widow", "has_disability", "household_size"]
    nested: dict[str, Any] = {"any": [{"and": [{"var": ["district", "x"]}, {"!": {"var": "identity_verified"}}]}], "params": {"var": "no"}}
    assert forms.required_fields(nested) == ["district"]
    assert forms.required_fields(None) == []


def test_missing_fields_are_only_the_unknown_ones() -> None:
    form = forms.merge_client_patch(ApplicationFormV1(), {"is_widow": {"value": True}, "income_band": {"value": "under_15k"}})
    assert forms.missing_fields(form, RULES_V1) == ["receives_other_aid", "has_disability", "household_size"]


def test_consent_scope_for_every_field() -> None:
    assert forms.scopes_needed(["full_name", "income_band", "household_size"]) == {"identity", "income", "household"}
    assert forms.scopes_needed([]) == set()


# --- signed card --------------------------------------------------------------------------------------


def test_signed_fields_accept_aliases_and_drop_bad_values() -> None:
    values = forms.signed_fields({"name": "Zainab Bibi", "id": MOCK_ID, "date_of_birth": "1978-03-14", "sex": "female",
                                  "district": "Karachi East", "income": "high", "dob_extra": 1})  # fmt: skip
    assert values == {"full_name": "Zainab Bibi", "national_id": MOCK_ID, "dob": "1978-03-14", "gender": "female", "district": "Karachi East"}
    assert "national_id" not in forms.signed_fields({"national_id": "12345-1234567-1"})  # mock-lint: allow
    assert forms.signed_fields(None) == {}


def test_merge_signed_marks_values_verified() -> None:
    form = forms.merge_signed(ApplicationFormV1(), {"full_name": "Zainab Bibi", "national_id": MOCK_ID})
    assert form.full_name.verified and form.full_name.provenance == "qr_signed" and form.national_id.value == MOCK_ID
    assert not form.household_size.verified


# --- tracking codes and timeline ---------------------------------------------------------------------


def test_tracking_codes() -> None:
    for _ in range(200):
        number = timeline.new_tracking_number()
        code = timeline.format_tracking(number)
        assert len(code) == 7 and code.startswith("R-") and timeline.tracking_number(code) == number
        assert len(timeline.symbols_for(code)) == 3
    assert timeline.symbols_for(None) == [] and timeline.tracking_number("R-1234") is None


def test_timeline_is_ordered_even_when_timestamps_tie() -> None:
    t0 = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
    items = timeline.build_timeline(
        created_at=t0, submitted_at=t0 + timedelta(minutes=5), status="paid", updated_at=t0 + timedelta(minutes=9),
        decisions=[timeline.DecisionEvent(at=t0 + timedelta(minutes=5), outcome="approved")],
        payments=[timeline.PaymentEvent(at=t0 + timedelta(minutes=8), status="settled")],
    )  # fmt: skip
    assert [i.status for i in items] == ["draft", "submitted", "approved", "paid"]
    held = timeline.build_timeline(created_at=t0, submitted_at=None, status="on_hold_consent", updated_at=t0, decisions=[], payments=[])
    assert [i.label_key for i in held] == ["timeline.started", "timeline.on_hold_consent"]
