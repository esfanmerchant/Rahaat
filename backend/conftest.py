"""Shared test setup.

Tests that touch Postgres ask for the `database` fixture (directly or through `client`/`factory`) and are
marked `db` automatically. `pytest -m "not db"` runs the DB-free tests in seconds.

Locally the tests use a throwaway database on the embedded dev server. In CI, set
TEST_DATABASE_URL_OWNER to an empty Postgres with pgvector.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

os.environ["APP_ENV"] = "test"
os.environ["LOGIN_IP_ATTEMPTS_PER_MINUTE"] = "1000000"
os.environ.pop("DATABASE_URL", None)

import pytest  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent
STAFF_PASSWORD = "Tested-Horse-Battery-9!"
CITIZEN_PIN = "4826"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "database" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    from alembic import command
    from alembic.config import Config

    from app.core.config import reset_settings_cache
    from app.core.db import dispose_engines

    explicit = os.environ.get("TEST_DATABASE_URL_OWNER")
    if explicit:
        os.environ["DATABASE_URL_OWNER"] = explicit
    else:
        from app import devdb

        os.environ["DATABASE_URL_OWNER"] = devdb.database_uri("rahat_test", recreate=True)
    reset_settings_cache()
    dispose_engines()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")

    from app.bootstrap import ensure_platform_rows

    ensure_platform_rows()
    yield
    dispose_engines()


@pytest.fixture(scope="session")
def app(database: None) -> Any:
    from app.main import create_app

    return create_app()


@pytest.fixture()
def client(app: Any) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@dataclass
class Account:
    user_id: uuid.UUID
    identifier: str
    secret: str
    role: str
    tenant_id: uuid.UUID
    tenant_slug: str
    person_id: uuid.UUID | None = None


class Factory:
    """Creates isolated test data. Every test makes its own tenants, so tests never see each other's rows."""

    def __init__(self) -> None:
        self._serial = int(uuid.uuid4().int % 8_000_000) + 1_000_000

    def _next(self) -> int:
        self._serial += 1
        return self._serial

    def tenant(self, name: str = "Test Department") -> Any:
        from app.contracts.decision import CostMatrix
        from app.core.crypto import new_wrapped_dek
        from app.core.db import system_session
        from app.db import models

        with system_session() as db:
            tenant = models.Tenant(
                slug=f"t-{uuid.uuid4().hex[:12]}", name=name, kind="department", region="PK-SD",
                wrapped_dek=new_wrapped_dek(), cost_matrix=CostMatrix().model_dump(), config={},
            )  # fmt: skip
            db.add(tenant)
            db.flush()
            db.expunge(tenant)
        return tenant

    def account(self, tenant: Any, role: str, *, extra_tenants: tuple[Any, ...] = ()) -> Account:
        """A user with a membership. Citizens also get a person record and an active consent."""
        from app.core.crypto import blind_index, encrypt_field, encrypt_platform
        from app.core.db import system_session
        from app.core.mockdata import make_mock_id, make_mock_phone
        from app.core.security import hash_secret
        from app.db import models

        staff = role in ("officer", "admin", "auditor")
        serial = self._next()
        identifier = f"{role}-{uuid.uuid4().hex[:10]}@test.rahat.example" if staff else make_mock_phone(serial)
        secret = STAFF_PASSWORD if staff else CITIZEN_PIN
        with system_session() as db:
            user = models.User(
                email=identifier if staff else None,
                phone_hash=None if staff else blind_index(identifier),
                phone_enc=None if staff else encrypt_platform(identifier),
                display_name=f"Test {role.title()}", lang="en" if staff else "ur", password_hash=hash_secret(secret),
            )  # fmt: skip
            db.add(user)
            db.flush()
            person_id = None
            if role == "citizen":
                national_id = make_mock_id(serial)
                person = models.Person(
                    tenant_id=tenant.id, user_id=user.id, full_name="Test Citizen", dob=date(1980, 1, 1), district="Karachi East",
                    phone_enc=encrypt_field(tenant.wrapped_dek, identifier), phone_hash=blind_index(identifier, scope=str(tenant.id)),
                    national_id_enc=encrypt_field(tenant.wrapped_dek, national_id),
                    national_id_hash=blind_index(national_id, scope=str(tenant.id)),
                )  # fmt: skip
                db.add(person)
                db.flush()
                person_id = person.id
                db.add(models.Consent(
                    tenant_id=tenant.id, person_id=person.id, grantee_type="tenant", grantee_id=tenant.id,
                    purpose="relief_application", field_scopes=["identity"], granted_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                ))  # fmt: skip
            for member_of in (tenant, *extra_tenants):
                db.add(models.Membership(tenant_id=member_of.id, user_id=user.id, role=role,
                                         person_id=person_id if member_of.id == tenant.id else None))  # fmt: skip
            user_id = user.id
        return Account(user_id=user_id, identifier=identifier, secret=secret, role=role, tenant_id=tenant.id,
                       tenant_slug=tenant.slug, person_id=person_id)  # fmt: skip

    @staticmethod
    def login(client: Any, account: Account, *, tenant_slug: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"identifier": account.identifier, "secret": account.secret}
        if tenant_slug:
            body["tenant_slug"] = tenant_slug
        response = client.post("/v1/auth/login", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def headers(self, client: Any, account: Account) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.login(client, account)['access_token']}"}


@pytest.fixture()
def factory(database: None) -> Factory:
    return Factory()
