"""Gate 1: the anchor flow, end to end through the HTTP API, with every track's real code.

1. Aslam (shopkeeper) has a signed Rahat card and a recent registry income under the cap. The system acts
   alone: approved, Rs 12,000 paid at once, and a message whose verify code checks out.
2. Zainab (widow) has no income record. The system does not guess: it asks for one paper. She sends a photo
   of a paper it cannot verify, so it hands the case to a person with notes. An officer approves with a
   reason, the payment goes out, and she is told.
3. The auditor sees both decisions (the simple reason and the full trace) and the audit chain verifies.

The specimen cards come from track C's generator (`data/demo_cards`). Every person and card is invented.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.core.db import system_session

REPO_ROOT = Path(__file__).resolve().parents[3]
CARDS = REPO_ROOT / "data" / "demo_cards"
PIN = "4826"
STAFF_PASSWORD = "Rahat-Demo-2026!"


@pytest.fixture()
def demo(client: TestClient) -> Iterator[TestClient]:
    if not (CARDS / "aslam-khan" / "card.png").is_file():
        pytest.skip("specimen cards are not generated yet (track C)")
    from app import seed
    from app.modules.integrations.testing import fresh_mocks

    with system_session() as db:
        seed.seed(db)
    with fresh_mocks():
        yield client


def _login(client: TestClient, identifier: str, secret: str) -> dict[str, str]:
    response = client.post("/v1/auth/login", json={"identifier": identifier, "secret": secret})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _answer(value: Any) -> dict[str, Any]:
    return {"value": value, "confidence": 1.0, "provenance": "tapped"}


def _apply(client: TestClient, headers: dict[str, str], *, card: Path, answers: dict[str, Any]) -> dict[str, Any]:
    """Start an application, upload the card, answer the questions. Returns the application as it stands."""
    programs = client.get("/v1/programs", headers=headers).json()
    rahat = next(p for p in programs if p["slug"] == "rahat")
    created = client.post("/v1/applications", headers=headers, json={"program_id": rahat["id"], "client_op_id": f"op-{uuid.uuid4().hex}"})
    assert created.status_code == 201, created.text
    application_id = created.json()["id"]

    upload = client.post(f"/v1/applications/{application_id}/documents", headers=headers,
                         files={"file": (card.name, card.read_bytes(), "image/png")}, data={"kind": "rahat_id"})  # fmt: skip
    assert upload.status_code == 201, upload.text
    document = upload.json()["document"]
    assert document["accepted"] and document["quality"] == "ok", document
    assert "signals" not in document, "detection details never reach the citizen"

    current = client.get(f"/v1/applications/{application_id}", headers=headers).json()
    assert current["form"]["national_id"]["provenance"] == "qr_signed" and current["form"]["national_id"]["verified"]
    patched = client.patch(f"/v1/applications/{application_id}", headers=headers,
                           json={"base_version": current["version"], "form_patch": {k: _answer(v) for k, v in answers.items()}})  # fmt: skip
    assert patched.status_code == 200, patched.text
    return patched.json()


def _paper_photo() -> bytes:
    """A photo of an ordinary paper with no signature: something the system cannot verify on its own."""
    image = Image.new("RGB", (1200, 900), (245, 243, 236))
    draw = ImageDraw.Draw(image)
    for row in range(12):
        draw.text((80, 80 + row * 60), "Monthly wage slip (specimen) - shop helper - Rs 18,000", fill=(40, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _run_jobs() -> None:
    from app.modules.jobs.service import run_pending

    run_pending()


def test_the_anchor_flow_end_to_end(demo: TestClient) -> None:
    client = demo

    # --- 1. Aslam: verified identity and income, the system acts alone --------------------------------------
    aslam = _login(client, "0999-0000202", PIN)
    application = _apply(client, aslam, card=CARDS / "aslam-khan" / "card.png", answers={
        "household_size": 6, "income_band": "15k_30k", "is_widow": False, "has_disability": False, "receives_other_aid": False,
    })  # fmt: skip
    assert application["missing_fields"] == []
    submitted = client.post(f"/v1/applications/{application['id']}/submit", headers=aslam)
    assert submitted.status_code == 200, submitted.text
    decision = submitted.json()["decision"]
    assert decision["outcome"] == "approved" and decision["route"] == "auto", decision
    explanation = decision["explanation"]
    assert 1 <= len(explanation["sentences"]) <= 3 and explanation["ask_a_person"]
    assert "probabilities" not in decision and "expected_costs" not in decision, "no scores for citizens"

    again = client.post(f"/v1/applications/{application['id']}/submit", headers=aslam)
    assert again.json()["decision"]["decision_id"] == decision["decision_id"], "a second tap returns the first result"

    final = client.get(f"/v1/applications/{application['id']}", headers=aslam).json()
    assert final["status"] == "paid", final["status"]
    officer = _login(client, "officer@sindh.rahat.example", STAFF_PASSWORD)
    payments = client.get("/v1/payments", headers=officer).json()["items"]
    mine = [p for p in payments if p["application_id"] == application["id"]]
    assert len(mine) == 1 and mine[0]["amount_pkr"] == 12000 and mine[0]["status"] == "settled", mine

    _run_jobs()
    messages = client.get("/v1/notifications", headers=aslam).json()["items"]
    templates = {m["template"] for m in messages}
    assert {"approved", "payment_sent"} <= templates, templates
    code = next(m["verify_code"] for m in messages if m["template"] == "payment_sent")
    check = client.post("/v1/notifications/verify", json={"code": code}).json()
    assert check["genuine"] is True, check
    assert client.post("/v1/notifications/verify", json={"code": "ABCDEF"}).json()["genuine"] is False

    # --- 2. Zainab: no income record, the system does not guess -------------------------------------------------
    zainab = _login(client, "0999-0000201", PIN)
    application = _apply(client, zainab, card=CARDS / "zainab-bibi" / "card.png", answers={
        "household_size": 5, "income_band": "15k_30k", "is_widow": True, "has_disability": False, "receives_other_aid": False,
    })  # fmt: skip
    first = client.post(f"/v1/applications/{application['id']}/submit", headers=zainab).json()
    assert first["decision"]["outcome"] in ("needs_proof", "needs_human"), first["decision"]
    assert first["decision"]["route"] != "auto", "missing income must never be decided alone"

    if first["decision"]["outcome"] == "needs_proof":
        proof = client.post(f"/v1/applications/{application['id']}/documents", headers=zainab,
                            files={"file": ("slip.jpg", _paper_photo(), "image/jpeg")}, data={"kind": "income_proof"})  # fmt: skip
        assert proof.status_code == 201, proof.text
        second = client.post(f"/v1/applications/{application['id']}/submit", headers=zainab).json()
        assert second["decision"]["outcome"] == "needs_human", second["decision"]
        assert second["decision"]["explanation"]["pictogram"] == "person-will-help"
    status = client.get(f"/v1/applications/{application['id']}", headers=zainab).json()["status"]
    assert status == "in_review", status

    queue = client.get("/v1/cases", headers=officer).json()["items"]
    case = next(c for c in queue if c["application_id"] == application["id"])
    detail = client.get(f"/v1/cases/{case['id']}", headers=officer).json()
    handoff = detail["handoff"]
    assert handoff["question"] and handoff["understanding"] and handoff["uncertain_fields"], handoff
    assert detail["decision"]["route"] == "human" and detail["decision"]["rule_trace"], "the officer sees the full trace"
    assert "approve" in detail["allowed_actions"]

    no_reason = client.post(f"/v1/cases/{case['id']}/actions", headers=officer, json={"action": "approve", "reason": ""})
    assert no_reason.status_code == 422, "every action needs a reason"
    approved = client.post(f"/v1/cases/{case['id']}/actions", headers=officer,
                           json={"action": "approve", "reason": "Wage slip checked by phone with the employer (demo)."})  # fmt: skip
    assert approved.status_code == 200, approved.text

    final = client.get(f"/v1/applications/{application['id']}", headers=zainab).json()
    assert final["status"] == "paid", final["status"]
    _run_jobs()
    told = {m["template"] for m in client.get("/v1/notifications", headers=zainab).json()["items"]}
    assert "payment_sent" in told, told

    # --- 3. The auditor: two views of each decision and an intact chain ------------------------------------------
    auditor = _login(client, "auditor@rahat.example", STAFF_PASSWORD)
    shown = client.get(f"/v1/decisions/{decision['decision_id']}", headers=auditor).json()
    assert shown["user_view"]["outcome"] == "approved"
    trace = shown["trace"]
    assert trace["rule_version_no"] >= 1 and trace["input_hash"] and trace["result_hash"] and trace["model_version"]
    assert len(trace["thresholds"]) >= 1 and trace["expected_costs"]
    chain = client.get("/v1/audit/verify", headers=auditor).json()
    assert chain["ok"] is True and chain["checked"] > 10, chain
