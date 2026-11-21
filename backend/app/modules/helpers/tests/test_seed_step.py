"""The demo helper's 40 families: seeded once, safe to run again, and usable through the API."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.crypto import blind_index
from app.core.db import system_session
from app.db import models
from app.demo_accounts import DEMO_PIN
from app.modules.helpers import seed_step


def _counts() -> dict[str, int]:
    with system_session() as db:
        helper = db.scalar(select(models.User).where(models.User.phone_hash == blind_index(seed_step.HELPER_PHONE)))
        assert helper is not None
        people = select(models.HelperDelegation.person_id).where(models.HelperDelegation.helper_user_id == helper.id)
        return {
            "delegations": int(db.scalar(select(func.count()).select_from(models.HelperDelegation)
                                         .where(models.HelperDelegation.helper_user_id == helper.id)) or 0),  # fmt: skip
            "persons": int(db.scalar(select(func.count(func.distinct(models.HelperDelegation.person_id)))
                                     .where(models.HelperDelegation.helper_user_id == helper.id)) or 0),  # fmt: skip
            "consents": int(db.scalar(select(func.count()).select_from(models.Consent).where(models.Consent.person_id.in_(people))) or 0),
            "applications": int(db.scalar(select(func.count()).select_from(models.Application)
                                          .where(models.Application.person_id.in_(people))) or 0),  # fmt: skip
        }


def test_rubina_serves_forty_families_and_the_seed_is_repeatable(client: TestClient, database: None) -> None:
    from app import seed

    with system_session() as db:
        seed.seed(db)
    first = _counts()
    with system_session() as db:
        seed.seed(db)
    assert _counts() == first, "running the seed twice adds nothing"
    assert first["persons"] == 40 and first["delegations"] == 40 and first["consents"] >= 40 and first["applications"] >= 6

    with system_session() as db:
        seeded = db.scalars(select(models.Person).where(models.Person.data["seed"].astext == "helper_families")).all()
        names = {p.data.get("family_key"): p.full_name for p in seeded}
        khadija = str(next(p.id for p in seeded if p.data.get("family_key") == "f04"))
        for a, b in seed_step.SPELLING_PAIRS:
            assert names[a] != names[b], "the same family, spelled two ways"
        statuses = set(db.scalars(select(models.Application.status).where(models.Application.client_op_id.like("seed-%"))).all())
        assert {"draft", "in_review", "on_hold_consent", "withdrawn"} <= statuses

    login = client.post("/v1/auth/login", json={"identifier": seed_step.HELPER_PHONE, "secret": DEMO_PIN})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    families = client.get("/v1/helper/families", headers=headers).json()
    assert len(families["items"]) == 40 and families["live_count"] == 40
    shown: dict[str, Any] = {f["display_name"]: f for f in families["items"] if f["display_name"]}
    assert "Zainab Bibi" in shown and "Shazia Memon" in shown
    assert sum(1 for f in families["items"] if f["display_name"]) == 39, "all but the family that withdrew are named"
    withdrawn = next(f for f in families["items"] if f["person_id"] == khadija)
    assert withdrawn["consent_active"] is False and withdrawn["display_name"] is None, "one family took its consent back"
    target = shown["Shazia Memon"]
    assert target["application"]["status"] == "draft"
    switched = client.post("/v1/helper/switch", json={"person_id": target["person_id"], "pin": DEMO_PIN}, headers=headers)
    assert switched.status_code == 200 and switched.json()["display_name"] == "Shazia Memon"
    family_headers = {**headers, "X-Acting-For": target["person_id"], "X-Helper-Ticket": switched.json()["ticket"]}
    assert client.get("/v1/applications", headers=family_headers).json()["items"][0]["status"] == "draft"
