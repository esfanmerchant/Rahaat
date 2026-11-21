"""Demo seed: two departments, the Rahat program with rule version 1, and the demo accounts.

    uv run python -m app.seed             create whatever is missing (safe to run again)
    uv run python -m app.seed --if-empty  do nothing when the demo departments already exist
    uv run python -m app.seed --reset     wipe every table, then seed again

Everything here is invented. Other tracks add their own seed steps to `EXTRA_STEPS`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.bootstrap import ensure_platform_rows
from app.contracts.decision import CostMatrix
from app.core import audit
from app.core.crypto import blind_index, encrypt_field, encrypt_platform, new_wrapped_dek
from app.core.db import get_owner_engine, system_session
from app.core.mockdata import make_mock_id
from app.core.security import hash_secret
from app.db import models
from app.db.base import Base
from app.demo_accounts import DEMO_ACCOUNTS, DEMO_PIN, DEMO_TENANTS, DemoAccount, secret_for

PROGRAM_SLUG = "rahat"

# PLAN 6.8. Track B owns the interpreter and may refine variable names in its own seed step.
RULES_V1 = {
    "params": {"income_cap": 30000},
    "required_docs": ["rahat_id"],
    "payment_pkr": 12000,
    "all": [
        {
            "id": "identity_verified", "hard": True,
            "label_en": "Identity confirmed by the signed card or the registry",
            "label_ur": "شناخت کی تصدیق کارڈ یا ریکارڈ سے ہو گئی",
            "expr": {"==": [{"var": "identity_verified"}, True]},
        },
        {
            "id": "income_cap", "hard": True,
            "label_en": "Monthly income at or below Rs 30,000",
            "label_ur": "ماہانہ آمدنی 30,000 روپے یا کم",
            "expr": {"<=": [{"var": "verified_income_pkr"}, {"param": "income_cap"}]},
        },
        {
            "id": "not_already_receiving", "hard": True,
            "label_en": "Not already receiving this payment",
            "label_ur": "یہ امداد پہلے سے نہیں مل رہی",
            "expr": {"!=": [{"var": "receives_other_aid"}, True]},
        },
        {
            "id": "priority_group", "hard": False,
            "label_en": "Widow, person with a disability, or a household of five or more",
            "label_ur": "بیوہ، معذور فرد، یا پانچ یا زیادہ افراد کا گھرانہ",
            "expr": {"or": [{"var": "is_widow"}, {"var": "has_disability"}, {">=": [{"var": "household_size"}, 5]}]},
        },
    ],
}  # fmt: skip

EXTRA_STEPS: list[Callable[[Session], None]] = []


def _reset() -> None:
    """Empty every table through the owner connection (the app role cannot truncate the audit log)."""
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with get_owner_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))  # noqa: S608  (names come from our own metadata)


def _tenant(db: Session, spec: dict[str, str]) -> models.Tenant:
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == spec["slug"]))
    if tenant is None:
        plan = db.scalar(select(models.Plan).where(models.Plan.code == "standard"))
        tenant = models.Tenant(
            slug=spec["slug"], name=spec["name"], name_ur=spec["name_ur"], region=spec["region"],
            kind="department", plan_id=plan.id if plan else None, wrapped_dek=new_wrapped_dek(),
            cost_matrix=CostMatrix().model_dump(),
            config={"payment_four_eyes_limit_pkr": 10000, "languages": ["ur", "en", "sd"], "official_sender": "RAHAT"},
        )  # fmt: skip
        db.add(tenant)
        db.flush()
    return tenant


def _program_and_rules(db: Session, tenant: models.Tenant, published_by: models.User | None) -> None:
    program = db.scalar(select(models.Program).where(models.Program.tenant_id == tenant.id, models.Program.slug == PROGRAM_SLUG))
    if program is None:
        program = models.Program(
            tenant_id=tenant.id, slug=PROGRAM_SLUG, name="Rahat (Prototype Relief Program)",
            name_ur="راحت (آزمائشی امدادی پروگرام)", kind="relief_payment", config={"currency": "PKR"},
        )  # fmt: skip
        db.add(program)
        db.flush()
    rule_set = db.scalar(select(models.RuleSet).where(models.RuleSet.program_id == program.id))
    if rule_set is None:
        rule_set = models.RuleSet(tenant_id=tenant.id, program_id=program.id, name="Rahat eligibility")
        db.add(rule_set)
        db.flush()
    if rule_set.active_version_id is None:
        now = datetime.now(UTC)
        version = models.RuleVersion(
            tenant_id=tenant.id, rule_set_id=rule_set.id, version_no=1, status="published", dsl=RULES_V1,
            description_en="Relief payment of Rs 12,000 for verified low-income households. Priority to widows, "
                           "people with disabilities and large households.",
            description_ur="تصدیق شدہ کم آمدنی والے گھرانوں کے لیے 12,000 روپے کی امداد۔ بیواؤں، معذور افراد اور بڑے گھرانوں کو ترجیح۔",
            effective_from=now, published_at=now, content_hash=audit.hash_payload(RULES_V1),
            created_by=published_by.id if published_by else None, approved_by=None, high_impact=True,
        )  # fmt: skip
        db.add(version)
        db.flush()
        rule_set.active_version_id = version.id
        audit.write(db, tenant_id=tenant.id, action="rules.version_published", actor_type="system",
                    object_type="rule_version", object_id=version.id, rule_version_id=version.id,
                    details={"version_no": 1, "content_hash": version.content_hash, "source": "seed"})  # fmt: skip


def _user(db: Session, account: DemoAccount) -> models.User:
    identifier = account["identifier"]
    is_staff = account["kind"] == "staff"
    query = (
        select(models.User).where(func.lower(models.User.email) == identifier.lower())
        if is_staff
        else select(models.User).where(models.User.phone_hash == blind_index(identifier))
    )
    user = db.scalar(query)
    if user is None:
        user = models.User(
            email=identifier if is_staff else None,
            phone_hash=None if is_staff else blind_index(identifier),
            phone_enc=None if is_staff else encrypt_platform(identifier),
            display_name=account["name"], lang=account.get("lang", "en"), password_hash=hash_secret(secret_for(account)),
        )  # fmt: skip
        db.add(user)
        db.flush()
    return user


def _person(db: Session, tenant: models.Tenant, user: models.User, account: DemoAccount, serial: int) -> models.Person:
    person = db.scalar(select(models.Person).where(models.Person.tenant_id == tenant.id, models.Person.user_id == user.id))
    if person is None:
        national_id = make_mock_id(serial)
        scope = str(tenant.id)
        person = models.Person(
            tenant_id=tenant.id, user_id=user.id, full_name=account["name"], full_name_ur=account.get("name_ur"),
            dob=date(1974 + serial % 20, 1 + serial % 12, 1 + serial % 27), gender="female" if serial % 2 else "male",
            district=account.get("district"), lang=account.get("lang", "ur"),
            phone_enc=encrypt_field(tenant.wrapped_dek, account["identifier"]),
            phone_hash=blind_index(account["identifier"], scope=scope),
            national_id_enc=encrypt_field(tenant.wrapped_dek, national_id),
            national_id_hash=blind_index(national_id, scope=scope), created_by=user.id,
        )  # fmt: skip
        db.add(person)
        db.flush()
        now = datetime.now(UTC)
        consent = models.Consent(
            tenant_id=tenant.id, person_id=person.id, grantee_type="tenant", grantee_id=tenant.id,
            purpose="relief_application", field_scopes=["identity", "contact", "household", "income", "documents"],
            granted_at=now, expires_at=now + timedelta(days=180),
        )  # fmt: skip
        db.add(consent)
        db.flush()
        db.add(models.ConsentEvent(tenant_id=tenant.id, consent_id=consent.id, person_id=person.id, event="granted",
                                   actor_user_id=user.id, details={"source": "seed"}))  # fmt: skip
        audit.write(db, tenant_id=tenant.id, action="consent.granted", actor_id=user.id, actor_role="citizen",
                    object_type="consent", object_id=consent.id, details={"purpose": consent.purpose, "source": "seed"})  # fmt: skip
    return person


def _membership(db: Session, tenant: models.Tenant, user: models.User, role: str, person: models.Person | None,
                order: int = 0) -> None:
    exists = db.scalar(
        select(models.Membership).where(
            models.Membership.tenant_id == tenant.id, models.Membership.user_id == user.id, models.Membership.role == role
        )
    )
    if exists is None:
        # Sign-in defaults to the oldest membership, so the first department listed for an account wins.
        db.add(models.Membership(tenant_id=tenant.id, user_id=user.id, role=role, person_id=person.id if person else None,
                                 created_at=datetime.now(UTC) + timedelta(seconds=order)))


def seed(db: Session) -> None:
    tenants = {spec["slug"]: _tenant(db, dict(spec)) for spec in DEMO_TENANTS}
    citizens: dict[str, list[models.Person]] = {slug: [] for slug in tenants}
    helpers: dict[str, list[models.User]] = {slug: [] for slug in tenants}
    admins: dict[str, models.User] = {}

    for index, account in enumerate(DEMO_ACCOUNTS):
        user = _user(db, account)
        for order, slug in enumerate(account["tenants"]):
            tenant = tenants[slug]
            person = None
            if account["role"] == "citizen":
                person = _person(db, tenant, user, account, serial=1_000_200 + index)
                citizens[slug].append(person)
            elif account["role"] == "helper":
                helpers[slug].append(user)
            elif account["role"] == "admin":
                admins.setdefault(slug, user)
            _membership(db, tenant, user, account["role"], person, order)

    for slug, tenant in tenants.items():
        _program_and_rules(db, tenant, admins.get(slug))
        # The first citizen has asked the community helper to act for them. More families come with Track B.
        for helper in helpers[slug]:
            for person in citizens[slug][:1]:
                already = db.scalar(
                    select(models.HelperDelegation).where(
                        models.HelperDelegation.helper_user_id == helper.id, models.HelperDelegation.person_id == person.id
                    )
                )
                if already is None:
                    db.add(models.HelperDelegation(
                        tenant_id=tenant.id, helper_user_id=helper.id, person_id=person.id,
                        scopes=["apply", "track", "upload"], pin_hash=hash_secret(DEMO_PIN),
                        expires_at=datetime.now(UTC) + timedelta(days=90),
                    ))  # fmt: skip
    db.flush()
    for step in EXTRA_STEPS:
        step(db)


def main(argv: list[str]) -> int:
    flags = set(argv[1:])
    unknown = flags - {"--if-empty", "--reset"}
    if unknown:
        print(__doc__)
        return 2
    if "--reset" in flags:
        _reset()
        print("all tables emptied")
    ensure_platform_rows()
    with system_session() as db:
        if "--if-empty" in flags:
            slugs = [t["slug"] for t in DEMO_TENANTS]
            if db.scalar(select(func.count()).select_from(models.Tenant).where(models.Tenant.slug.in_(slugs))):
                print("demo data already present; nothing to do")
                return 0
        seed(db)
    print(f"seeded {len(DEMO_TENANTS)} departments and {len(DEMO_ACCOUNTS)} demo accounts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
