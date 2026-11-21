"""Seed: the demo community helper (Rubina Shaikh, 0999-0000101) serves 40 families in Sindh.

Zainab Bibi already chose Rubina in the base seed; this step adds 39 more families, each with an active
consent for the department and a delegation to Rubina (scopes track, apply and upload; 90 days). Every
family PIN is the demo PIN (`app.demo_accounts.DEMO_PIN`) so the presenter can switch between families;
the server still stores one argon2 hash per delegation, as it would for PINs the families chose.

Everything here is invented: names, dates, mock IDs (`00000-31000NN-C`) and mock phones (`0999-31001NN`).
Some families appear twice with a different Latin spelling of the same name, the same date of birth and
district, and no ID card the second time, as when a helper registers a family again. The dedupe work uses
these pairs (`SPELLING_PAIRS`). A few families have an application: drafts, one under review because nobody
could tie the family to an ID yet, one paused because the family took back its consent, one withdrawn.

Safe to run twice: a family, its consent, its delegation and its application are each created only when
missing, so a delegation revoked during a demo is not brought back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.application import ApplicationFormV1
from app.contracts.decision import HandoffPackage, UncertainField
from app.core import audit
from app.core.crypto import blind_index, encrypt_field
from app.core.logging import get_logger
from app.core.mockdata import make_mock_id, make_mock_phone
from app.core.security import hash_secret
from app.db import models
from app.demo_accounts import DEMO_PIN
from app.modules.applications.timeline import format_tracking, new_tracking_number

log = get_logger("rahat.helpers.seed")

ORDER = 120  # after the base seed (which creates Rubina and Zainab) and the decision model
TENANT_SLUG: Final = "sindh-relief"
HELPER_PHONE: Final = "0999-0000101"
ID_SERIAL: Final = 3_100_000
PHONE_SERIAL: Final = 3_100_100
SCOPES: Final = ["track", "apply", "upload"]
ALL_CONSENT_SCOPES: Final = ["identity", "contact", "household", "income", "documents"]

# (key, full name, Urdu, gender, date of birth, district, has an ID card, application)
FAMILIES: Final[list[tuple[str, str, str, str, str, str, bool, str | None]]] = [
    ("f01", "Shazia Memon", "شازیہ میمن", "female", "1984-05-12", "Karachi East", True, "draft_partial"),
    ("f02", "Muhammad Hanif Odho", "محمد حنیف اوڈھو", "male", "1969-11-03", "Korangi", True, None),
    ("f03", "Mohammad Hanif Odhu", "محمد حنیف اوڈھو", "male", "1969-11-03", "Korangi", False, "in_review_unbound"),
    ("f04", "Khadija Bibi", "خدیجہ بی بی", "female", "1975-02-20", "Malir", True, "on_hold_consent"),
    ("f05", "Khadijah Bibi", "خدیجہ بی بی", "female", "1975-02-20", "Malir", False, None),
    ("f06", "Ghulam Rasool Chandio", "غلام رسول چانڈیو", "male", "1958-07-01", "Thatta", True, None),
    ("f07", "Gulam Rasul Chandio", "غلام رسول چانڈیو", "male", "1958-07-01", "Thatta", False, None),
    ("f08", "Naseem Akhtar", "نسیم اختر", "female", "1988-09-14", "Karachi East", True, "draft_ready"),
    ("f09", "Nasim Akhter", "نسیم اختر", "female", "1988-09-14", "Karachi East", False, None),
    ("f10", "Abdul Qadir Mallah", "عبدالقادر ملاح", "male", "1979-04-22", "Badin", True, None),
    ("f11", "Abdulqadir Malah", "عبدالقادر ملاح", "male", "1979-04-22", "Badin", False, None),
    ("f12", "Fatima Soomro", "فاطمہ سومرو", "female", "1990-01-15", "Hyderabad", True, None),
    ("f13", "Fatima Soomro", "فاطمہ سومرو", "female", "1962-08-30", "Larkana", True, None),  # same name, another person
    ("f14", "Parveen Lashari", "پروین لاشاری", "female", "1981-03-09", "Karachi East", True, "draft_empty"),
    ("f15", "Sakina Jamali", "سکینہ جمالی", "female", "1972-12-01", "Korangi", True, None),
    ("f16", "Rubab Brohi", "رباب بروہی", "female", "1993-06-18", "Malir", True, None),
    ("f17", "Allah Bachayo Khoso", "اللہ بچایو کھوسو", "male", "1966-10-25", "Thatta", True, None),
    ("f18", "Nazia Baloch", "نازیہ بلوچ", "female", "1986-02-11", "Karachi West", True, None),
    ("f19", "Rasheeda Begum", "رشیدہ بیگم", "female", "1960-05-30", "Karachi East", True, None),
    ("f20", "Mumtaz Ali Shar", "ممتاز علی شر", "male", "1977-08-08", "Sukkur", True, None),
    ("f21", "Saima Qureshi", "صائمہ قریشی", "female", "1989-11-21", "Hyderabad", True, "withdrawn"),
    ("f22", "Zubaida Khatoon", "زبیدہ خاتون", "female", "1955-01-04", "Karachi Central", True, None),
    ("f23", "Imtiaz Hussain Jatoi", "امتیاز حسین جتوئی", "male", "1971-07-16", "Dadu", True, None),
    ("f24", "Haleema Sadia", "حلیمہ سعدیہ", "female", "1995-04-02", "Karachi East", True, None),
    ("f25", "Bashir Ahmed Kalhoro", "بشیر احمد کلہوڑو", "male", "1963-09-27", "Jamshoro", True, None),
    ("f26", "Shabnam Rind", "شبنم رند", "female", "1983-12-19", "Malir", True, None),
    ("f27", "Waheed Bux Panhwar", "وحید بخش پنہور", "male", "1968-03-13", "Thatta", True, None),
    ("f28", "Gul Bano", "گل بانو", "female", "1974-06-06", "Tharparkar", False, None),
    ("f29", "Mai Jindo", "مائی جندو", "female", "1952-10-10", "Tharparkar", False, None),
    ("f30", "Sughran Bibi", "صغراں بی بی", "female", "1965-02-28", "Badin", True, None),
    ("f31", "Ameer Bux Laghari", "امیر بخش لغاری", "male", "1970-05-05", "Mirpurkhas", True, None),
    ("f32", "Rani Kolhi", "رانی کولہی", "female", "1991-08-24", "Tharparkar", True, None),
    ("f33", "Kavita Meghwar", "کویتا میگھواڑ", "female", "1987-01-30", "Umerkot", True, None),
    ("f34", "Sapna Bheel", "سپنا بھیل", "female", "1994-09-09", "Sanghar", True, None),
    ("f35", "Noor Jahan Solangi", "نور جہاں سولنگی", "female", "1959-11-11", "Karachi East", True, None),
    ("f36", "Akbar Ali Magsi", "اکبر علی مگسی", "male", "1976-04-14", "Larkana", True, None),
    ("f37", "Farzana Detho", "فرزانہ ڈیتھو", "female", "1985-07-07", "Hyderabad", True, None),
    ("f38", "Shahida Parveen", "شاہدہ پروین", "female", "1980-10-31", "Korangi", True, None),
    ("f39", "Yasmin Abro", "یاسمین ابڑو", "female", "1992-03-03", "Shikarpur", True, None),
]  # fmt: skip
assert len(FAMILIES) == 39 and len({f[0] for f in FAMILIES}) == 39

# Pairs that are one family registered twice with a different spelling (for the dedupe work).
SPELLING_PAIRS: Final = (("f02", "f03"), ("f04", "f05"), ("f06", "f07"), ("f08", "f09"), ("f10", "f11"))


def _number(key: str) -> int:
    return int(key[1:])


def _tracking_code(db: Session, tenant_id: uuid.UUID) -> str:
    for _ in range(50):
        code = format_tracking(new_tracking_number())
        taken = db.scalar(select(func.count()).select_from(models.Application)
                          .where(models.Application.tenant_id == tenant_id, models.Application.tracking_code == code))  # fmt: skip
        if not taken:
            return code
    raise RuntimeError("could not find a free tracking code for the seed")


def _form(plan: str, family: tuple[str, str, str, str, str, str, bool, str | None], phone: str, national_id: str | None) -> dict[str, Any]:
    _, name, _, gender, dob, district, _, _ = family
    typed = {"confidence": 1.0, "provenance": "typed", "verified": False}
    tapped = {"confidence": 1.0, "provenance": "tapped", "verified": False}
    values: dict[str, Any] = {"language": "ur"}
    if plan in ("draft_partial", "draft_ready", "in_review_unbound", "on_hold_consent", "withdrawn"):
        values.update(full_name={"value": name, **typed}, district={"value": district, **tapped}, household_size={"value": 6, **tapped})
    if plan in ("draft_ready", "in_review_unbound"):
        values.update(
            dob={"value": dob, **typed}, gender={"value": gender, **tapped}, phone={"value": phone, **typed},
            income_band={"value": "under_15k", **tapped}, is_widow={"value": gender == "female", **tapped},
            has_disability={"value": False, **tapped}, receives_other_aid={"value": False, **tapped},
            payout_account={"value": phone, **typed},
        )  # fmt: skip
        if national_id:
            values["national_id"] = {"value": national_id, **typed}
    return ApplicationFormV1.model_validate(values).model_dump(mode="json")


def _application(db: Session, tenant: models.Tenant, program: models.Program, person: models.Person, helper: models.User, plan: str,
                 form: dict[str, Any]) -> None:  # fmt: skip
    now = datetime.now(UTC)
    status = {"draft_partial": "draft", "draft_ready": "draft", "draft_empty": "draft", "in_review_unbound": "in_review",
              "on_hold_consent": "on_hold_consent", "withdrawn": "withdrawn"}[plan]  # fmt: skip
    submitted = plan == "in_review_unbound"
    application = models.Application(
        id=uuid.uuid4(), tenant_id=tenant.id, program_id=program.id, person_id=person.id, status=status, form=form, version=1,
        client_op_id=f"seed-{person.id.hex[:24]}", submitted_via="helper", tracking_code=_tracking_code(db, tenant.id),
        created_by=helper.id, submitted_at=now if submitted else None, created_at=now, updated_at=now,
    )  # fmt: skip
    db.add(application)
    db.flush()
    audit.write(db, tenant_id=tenant.id, action="application.created", actor_id=helper.id, actor_role="helper",
                acting_for_person_id=person.id, object_type="application", object_id=application.id,
                details={"program_id": str(program.id), "tracking_code": application.tracking_code, "source": "seed"})  # fmt: skip
    if plan == "in_review_unbound":
        from app.modules.cases.service import open_case

        handoff = HandoffPackage(
            question="Is this household eligible for the Rahat payment?",
            understanding="This person has no registered ID yet, so the ID on the form or card must be checked by a person.",
            uncertain_fields=[UncertainField(field="national_id", value=None, confidence=0.0, why="missing")],
            evidence={"document_ids": [], "registry_status": "unavailable", "identity": None, "source": "seed"},
        )
        open_case(db, tenant_id=tenant.id, kind="application_review", opened_reason="identity_unbound", application_id=application.id,
                  person_id=person.id, handoff=handoff, priority=50)  # fmt: skip
    if plan == "withdrawn":
        audit.write(db, tenant_id=tenant.id, action="application.withdrawn", actor_id=helper.id, actor_role="helper",
                    acting_for_person_id=person.id, object_type="application", object_id=application.id,
                    details={"from_status": "draft", "source": "seed"})  # fmt: skip
    if plan == "on_hold_consent":
        consent = db.scalars(select(models.Consent).where(models.Consent.person_id == person.id, models.Consent.status == "active")).first()
        if consent is not None:
            consent.status, consent.withdrawn_at, consent.version = "withdrawn", now, consent.version + 1
            db.add(models.ConsentEvent(tenant_id=tenant.id, consent_id=consent.id, person_id=person.id, event="withdrawn",
                                       actor_user_id=helper.id, details={"held": {str(application.id): "draft"}, "source": "seed"}))  # fmt: skip
            audit.write(db, tenant_id=tenant.id, action="consent.withdrawn", actor_id=helper.id, actor_role="helper",
                        acting_for_person_id=person.id, object_type="consent", object_id=consent.id,
                        details={"purpose": consent.purpose, "person_id": str(person.id), "source": "seed"})  # fmt: skip


def seed(db: Session) -> None:
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == TENANT_SLUG))
    helper = db.scalar(select(models.User).where(models.User.phone_hash == blind_index(HELPER_PHONE)))
    if tenant is None or helper is None:
        log.warning("demo department or helper missing; no helper families seeded")
        return
    program = db.scalar(select(models.Program).where(models.Program.tenant_id == tenant.id, models.Program.slug == "rahat"))
    scope = str(tenant.id)
    now = datetime.now(UTC)
    created = 0
    for family in FAMILIES:
        key, name, name_ur, gender, dob, district, has_id, plan = family
        n = _number(key)
        phone = make_mock_phone(PHONE_SERIAL + n)
        national_id = make_mock_id(ID_SERIAL + n) if has_id else None
        person = db.scalar(select(models.Person).where(models.Person.tenant_id == tenant.id,
                                                       models.Person.phone_hash == blind_index(phone, scope=scope)))  # fmt: skip
        if person is None:
            person = models.Person(
                id=uuid.uuid4(), tenant_id=tenant.id, user_id=None, full_name=name, full_name_ur=name_ur, dob=date.fromisoformat(dob),
                gender=gender, district=district, lang="ur", phone_enc=encrypt_field(tenant.wrapped_dek, phone),
                phone_hash=blind_index(phone, scope=scope),
                national_id_enc=encrypt_field(tenant.wrapped_dek, national_id) if national_id else None,
                national_id_hash=blind_index(national_id, scope=scope) if national_id else None,
                created_by=helper.id, data={"seed": "helper_families", "family_key": key, "registered_by": "helper"},
            )  # fmt: skip
            db.add(person)
            db.flush()
            created += 1
            audit.write(db, tenant_id=tenant.id, action="person.registered", actor_id=helper.id, actor_role="helper",
                        acting_for_person_id=person.id, object_type="person", object_id=person.id,
                        details={"channel": "helper", "source": "seed"})  # fmt: skip
        if db.scalar(select(models.Consent.id).where(models.Consent.person_id == person.id).limit(1)) is None:
            consent = models.Consent(
                id=uuid.uuid4(), tenant_id=tenant.id, person_id=person.id, grantee_type="tenant", grantee_id=tenant.id,
                purpose="relief_application", field_scopes=list(ALL_CONSENT_SCOPES), granted_at=now, expires_at=now + timedelta(days=180),
            )  # fmt: skip
            db.add(consent)
            db.flush()
            db.add(models.ConsentEvent(tenant_id=tenant.id, consent_id=consent.id, person_id=person.id, event="granted",
                                       actor_user_id=helper.id, details={"source": "seed", "via": "helper"}))  # fmt: skip
            audit.write(db, tenant_id=tenant.id, action="consent.granted", actor_id=helper.id, actor_role="helper",
                        acting_for_person_id=person.id, object_type="consent", object_id=consent.id,
                        details={"purpose": "relief_application", "source": "seed"})  # fmt: skip
        delegated = db.scalar(select(models.HelperDelegation.id).where(models.HelperDelegation.helper_user_id == helper.id,
                                                                       models.HelperDelegation.person_id == person.id).limit(1))  # fmt: skip
        if delegated is None:
            delegation = models.HelperDelegation(id=uuid.uuid4(), tenant_id=tenant.id, helper_user_id=helper.id, person_id=person.id,
                                                 scopes=list(SCOPES), pin_hash=hash_secret(DEMO_PIN),
                                                 expires_at=now + timedelta(days=90))  # fmt: skip
            db.add(delegation)
            db.flush()
            audit.write(db, tenant_id=tenant.id, action="helper.delegation_granted", actor_type="system", object_type="helper_delegation",
                        object_id=delegation.id, acting_for_person_id=person.id,
                        details={"helper_user_id": str(helper.id), "scopes": SCOPES, "source": "seed"})  # fmt: skip
        if plan and program is not None:
            has_application = db.scalar(select(models.Application.id).where(models.Application.person_id == person.id).limit(1))
            if has_application is None:
                _application(db, tenant, program, person, helper, plan, _form(plan, family, phone, national_id))
    db.flush()
    if created:
        log.info("seeded %d helper families", created)
