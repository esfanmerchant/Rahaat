"""Document upload through the API: abuse cases, the stored copy, signed-card merge and the citizen view."""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.core.db import system_session
from app.core.mockdata import make_mock_id
from app.db import models
from app.modules.applications.tests.support import Fakes, World, jpeg_bytes, new_app
from app.modules.documents.tests.test_imaging_unit import png, png_header_only


def _upload(client: TestClient, world: World, app_id: str, content: bytes, *, name: str = "card.jpg", ctype: str = "image/jpeg",
            kind: str = "rahat_id") -> Any:  # fmt: skip
    return client.post(f"/v1/applications/{app_id}/documents", headers=world.h("citizen"), files={"file": (name, content, ctype)},
                       data={"kind": kind})  # fmt: skip


def _registered_id(world: World) -> str:
    from app.core.crypto import decrypt_field

    with system_session() as db:
        person = db.get(models.Person, world.citizen.person_id)
        tenant = db.get(models.Tenant, world.tenant.id)
        return decrypt_field(tenant.wrapped_dek, person.national_id_enc)


def test_upload_abuse_is_refused(client: TestClient, world: World, fakes: Fakes, uploads: Path) -> None:
    app = new_app(client, world).json()["id"]
    cases = [
        (b"<?php system($_GET['c']); ?>", "shell.jpg", "image/jpeg", 415, "unsupported_file_type"),
        (b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024), "big.jpg", "image/jpeg", 413, "file_too_large"),
        (png_header_only(60_000, 60_000), "bomb.png", "image/png", 413, "image_too_many_pixels"),
        (png((6000, 6000), mode="1"), "wide.png", "image/png", 413, "image_too_many_pixels"),
        (png((32, 32)), "fake.jpg", "image/jpeg", None, None),  # a PNG named .jpg is judged by its bytes and accepted as PNG
    ]
    for content, name, ctype, status, code in cases:
        response = _upload(client, world, app, content, name=name, ctype=ctype)
        if status is None:
            assert response.status_code == 201, response.text
            continue
        assert response.status_code == status, (name, response.text)
        assert response.json()["code"] == code and "Traceback" not in response.text
    assert fakes.n("check_document") == 1, "rejected uploads never reach the document checker"
    with system_session() as db:
        events = db.scalars(select(models.SecurityEvent).where(models.SecurityEvent.tenant_id == world.tenant.id)).all()
        assert sorted(e.details["code"] for e in events) == sorted(c[4] for c in cases if c[4])
        stored = db.scalars(select(models.Document).where(models.Document.application_id == uuid.UUID(app))).one()
        assert stored.mime == "image/png"


def test_traversal_filename_is_ignored_and_the_stored_copy_is_clean(client: TestClient, world: World, fakes: Fakes, uploads: Path) -> None:
    app = new_app(client, world).json()["id"]
    original = jpeg_bytes()
    response = _upload(client, world, app, original, name="../../../../etc/passwd.jpg", ctype="text/html")
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body["document"]) == {"document_id", "kind", "accepted", "quality", "retake_hint", "message_key"}, "no signals for citizens"
    assert body["document"]["message_key"] == "doc_ok" and body["application_version"] == 2
    assert fakes.calls["check_document"][0]["image_bytes"] == original, "the check runs on the original bytes"

    with system_session() as db:
        document = db.get(models.Document, uuid.UUID(body["document"]["document_id"]))
        check = db.scalars(select(models.DocumentCheck).where(models.DocumentCheck.document_id == document.id)).one()
    assert ".." not in document.storage_key and "passwd" not in document.storage_key
    assert document.storage_key.startswith(f"{world.tenant.id}/") and document.storage_key.endswith(".jpg")
    files = [p for p in uploads.rglob("*") if p.is_file()]
    assert len(files) == 1 and files[0].resolve().is_relative_to(uploads.resolve())
    stored = files[0].read_bytes()
    assert b"SpyCam" not in stored and not Image.open(io.BytesIO(stored)).getexif()
    import hashlib

    assert document.sha256 == hashlib.sha256(original).hexdigest()
    assert check.result["model_version"] == "fake-docs" and "signals" in check.result, "staff keep the full check"

    officer = client.get(f"/v1/documents/{document.id}/content", headers=world.h("officer"))
    assert officer.status_code == 200 and officer.headers["content-type"] == "image/jpeg" and officer.content == stored
    assert client.get(f"/v1/documents/{document.id}/content", headers=world.h("citizen")).status_code == 403
    assert client.get(f"/v1/documents/{uuid.uuid4()}/content", headers=world.h("officer")).status_code == 404

    consent_id = client.get("/v1/consents", headers=world.h("citizen")).json()[0]["id"]
    narrowed = client.patch(f"/v1/consents/{consent_id}", json={"field_scopes": ["identity", "household"]}, headers=world.h("citizen"))
    assert narrowed.status_code == 200
    blocked = client.get(f"/v1/documents/{document.id}/content", headers=world.h("officer"))
    assert blocked.status_code == 403 and blocked.json()["code"] == "consent_scope_missing"


def test_signed_card_fills_the_form_as_verified(client: TestClient, world: World, fakes: Fakes, uploads: Path) -> None:
    app = new_app(client, world).json()["id"]
    fakes.doc_qr_payload = {"name": "Test Citizen", "national_id": _registered_id(world), "dob": "1980-01-01", "gender": "female"}
    response = _upload(client, world, app, jpeg_bytes())
    assert response.status_code == 201 and response.json()["document"]["message_key"] == "doc_ok"
    form = client.get(f"/v1/applications/{app}", headers=world.h("citizen")).json()["form"]
    assert form["full_name"] == {"value": "Test Citizen", "confidence": 1.0, "provenance": "qr_signed", "verified": True}
    assert form["national_id"]["verified"] and form["dob"]["value"] == "1980-01-01"
    # The verified value is locked against the client.
    locked = client.patch(f"/v1/applications/{app}", json={"base_version": 2, "form_patch": {"full_name": {"value": "Someone Else"}}},
                          headers=world.h("citizen"))  # fmt: skip
    assert locked.status_code == 422 and locked.json()["errors"][0]["code"] == "field_locked"


def test_someone_elses_signed_card_is_not_merged_and_is_flagged(client: TestClient, world: World, fakes: Fakes, uploads: Path) -> None:
    app = new_app(client, world).json()["id"]
    fakes.doc_qr_payload = {"name": "Another Person", "national_id": make_mock_id(9_300_003), "dob": "1990-05-05"}
    response = _upload(client, world, app, jpeg_bytes())
    assert response.status_code == 201
    assert response.json()["document"]["message_key"] == "doc_person_will_check", "the citizen is not told why"
    form = client.get(f"/v1/applications/{app}", headers=world.h("citizen")).json()["form"]
    assert form["full_name"]["value"] is None and form["national_id"]["value"] is None
    with system_session() as db:
        assert db.scalars(select(models.Document.status).where(models.Document.application_id == uuid.UUID(app))).one() == "mismatch"
        flagged = db.scalar(select(models.AuditLog.reason).where(models.AuditLog.action == "document.identity_mismatch",
                                                                 models.AuditLog.tenant_id == world.tenant.id))  # fmt: skip
        assert flagged == "signed_id_differs_from_registered_id"
    # The pipeline hands the mismatch to the engine as an identity mismatch.
    client.patch(f"/v1/applications/{app}", json={"base_version": 2, "form_patch": {"household_size": {"value": 3}}}, headers=world.h("citizen"))
    client.post(f"/v1/applications/{app}/submit", headers=world.h("citizen"))
    assert fakes.calls["decide_and_record"][0]["inp"].identity.status == "mismatch"


def test_poor_quality_asks_for_a_retake_and_uploads_close_after_submit(client: TestClient, world: World, fakes: Fakes, uploads: Path) -> None:
    app = new_app(client, world).json()["id"]
    fakes.doc_quality = "blurry"
    retake = _upload(client, world, app, jpeg_bytes()).json()["document"]
    assert retake == {"document_id": retake["document_id"], "kind": "rahat_id", "accepted": False, "quality": "blurry",
                      "retake_hint": "retake_blurry", "message_key": "doc_retake_blurry"}  # fmt: skip
    client.post(f"/v1/applications/{app}/submit", headers=world.h("citizen"))
    closed = _upload(client, world, app, jpeg_bytes())
    assert closed.status_code == 409 and closed.json()["code"] == "not_editable"
