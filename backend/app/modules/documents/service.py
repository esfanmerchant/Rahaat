"""Document upload and officer viewing.

Order of work for an upload: ownership, consent, editable status, size, magic bytes and pixel caps, then
Track C's `check_document()` on the original bytes, then a re-encoded copy without metadata is written under
a random name. The uploaded filename is never used. The full check (with its signals) is stored for staff;
the citizen gets only `DocumentCitizenView`.
"""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.api import DocumentOut
from app.contracts.common import DocumentKind
from app.contracts.documents import DocumentCheck
from app.core import audit, metrics
from app.core.config import get_settings
from app.core.crypto import blind_index, sha256_hex
from app.core.db import system_session
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.logging import get_logger
from app.db import models
from app.modules.applications import hooks
from app.modules.applications.forms import merge_signed, signed_fields
from app.modules.applications.service import form_of, load_owned
from app.modules.applications.status import EDITABLE
from app.modules.consent.access_log import record_view
from app.modules.consent.rules import active_consent, require_consent
from app.modules.documents import imaging
from app.modules.documents.views import KIND_SCOPES, citizen_view, document_status, signed_qr_valid
from app.modules.people.context import PersonContext
from app.modules.people.service import get_person

log = get_logger("rahat.documents")
MAX_DOCUMENTS_PER_APPLICATION = 12
PROOF_RECEIVED = ("app.modules.cases.service", "proof_received")
BACKEND_DIR = Path(__file__).resolve().parents[3]


def upload_root() -> Path:
    configured = Path(get_settings().upload_dir)
    root = configured if configured.is_absolute() else BACKEND_DIR / configured
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _path_for(storage_key: str) -> Path:
    root = upload_root()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise NotFound("That document does not exist.")
    return path


def _stored_bytes(db: Session, document: models.Document) -> bytes | None:
    """The upload's bytes: from the database when they were stored there, else from the upload folder.

    Both places are read whatever DOCUMENT_STORE says now, so changing the setting never hides an earlier upload.
    """
    blob = db.get(models.DocumentBlob, document.id)
    if blob is not None and blob.tenant_id == document.tenant_id:
        return bytes(blob.data)
    path = _path_for(document.storage_key)
    return path.read_bytes() if path.is_file() else None


def read_capped(stream: BinaryIO, limit: int = imaging.MAX_BYTES) -> bytes:
    """Read at most limit + 1 bytes, so an oversized upload is refused without reading all of it."""
    data = stream.read(limit + 1)
    imaging.check_size(len(data))
    return data


def _run_check(data: bytes, kind: str, document_id: UUID) -> DocumentCheck | None:
    check_document = hooks.optional(hooks.CHECK_DOCUMENT)
    if check_document is None:
        return None
    try:
        result = check_document(data, kind, document_id=str(document_id))
        return result if isinstance(result, DocumentCheck) else DocumentCheck.model_validate(result)
    except Exception:  # noqa: BLE001
        log.exception("check_document failed; a person will check the upload")
        return None


def upload(db: Session, ctx: PersonContext, application_id: UUID, stream: BinaryIO, kind: DocumentKind) -> DocumentOut:
    application = load_owned(db, ctx, application_id, lock=True)
    consent = require_consent(db, ctx, action="document.upload", scopes=KIND_SCOPES[kind])
    if application.status not in EDITABLE:
        raise Conflict("Documents can be added only before submitting or when proof is asked for.", code="not_editable",
                       extra={"status": application.status})  # fmt: skip
    count = db.scalar(select(func.count()).select_from(models.Document).where(models.Document.application_id == application.id))
    if (count or 0) >= MAX_DOCUMENTS_PER_APPLICATION:
        raise Conflict("This application already has the most photos it can hold. Ask a person for help.", code="too_many_documents")
    try:
        original = read_capped(stream)
        inspected = imaging.inspect(original)
    except (imaging.PayloadTooLarge, imaging.UnsupportedMediaType, imaging.UnreadableImage) as exc:
        metrics.ACCESS_DENIED.labels("upload").inc()
        db.add(models.SecurityEvent(tenant_id=ctx.tenant_id, kind="upload_rejected", severity="low", actor_user_id=ctx.user_id,
                                    details={"code": exc.code, "application_id": str(application.id)}))  # fmt: skip
        audit.write(db, tenant_id=ctx.tenant_id, action="document.rejected", object_type="application", object_id=application.id,
                    result="denied", reason=exc.code, **ctx.audit_fields())  # fmt: skip
        db.commit()
        raise

    document_id = uuid.uuid4()
    check = _run_check(original, kind, document_id)  # on the original bytes, before re-encoding
    clean, ext, mime, width, height = imaging.reencode(inspected)

    person = get_person(db, ctx)
    form = form_of(application)
    mismatch = unbound = False
    merged: list[str] = []
    # A valid signature is not enough: another person's QR stuck on a card is validly signed too.
    if signed_qr_valid(check) and check is not None and check.authenticity.choice == "genuine":
        values = signed_fields(check.qr.payload)
        signed_id = values.get("national_id")
        if not person.national_id_hash:
            unbound = True  # nothing ties this person to an ID yet, so the card cannot be shown to be theirs
        elif signed_id and blind_index(signed_id, scope=str(ctx.tenant_id)) != person.national_id_hash:
            mismatch = True  # someone else's card: nothing from it enters the form
        elif "identity" in (consent.field_scopes or []):
            form = merge_signed(form, values)
            merged = sorted(values)

    storage_key = f"{ctx.tenant_id}/{secrets.token_hex(16)}{ext}"
    in_db = get_settings().document_store == "db"
    path = _path_for(storage_key)
    if not in_db:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(clean)
    try:
        document = models.Document(
            id=document_id, tenant_id=ctx.tenant_id, application_id=application.id, person_id=ctx.person_id, kind=kind,
            storage_key=storage_key, sha256=sha256_hex(original), mime=mime, size_bytes=len(clean), width=width, height=height,
            status="unbound" if unbound else document_status(check, identity_mismatch=mismatch), created_by=ctx.user_id,
        )  # fmt: skip
        db.add(document)
        db.flush()
        if in_db:  # the bytes commit or roll back together with the document row
            db.add(models.DocumentBlob(document_id=document_id, tenant_id=ctx.tenant_id, person_id=ctx.person_id, data=clean))
        if check is not None:
            db.add(models.DocumentCheck(
                tenant_id=ctx.tenant_id, document_id=document_id, person_id=ctx.person_id, quality=check.quality,
                authenticity=None if check.authenticity.abstained else check.authenticity.choice,
                confidence=check.authenticity.confidence, result=check.model_dump(mode="json"), model_version=check.model_version,
            ))  # fmt: skip
        if merged:
            application.form = form.model_dump(mode="json")
        application.version += 1
        details: dict[str, Any] = {"kind": kind, "sha256": document.sha256, "checked": check is not None, "merged_fields": merged}
        audit.write(db, tenant_id=ctx.tenant_id, action="document.uploaded", object_type="document", object_id=document_id,
                    model_version=check.model_version if check else None, details=details, **ctx.audit_fields())  # fmt: skip
        if merged:
            # The form changed: offline sync reads these rows to know which fields changed after a given version.
            audit.write(db, tenant_id=ctx.tenant_id, action="application.fields_verified", object_type="application",
                        object_id=application.id, details={"fields": merged, "version": application.version, "source": "qr_signed",
                                                           "document_id": str(document_id)}, **ctx.audit_fields())  # fmt: skip
        if mismatch:
            audit.write(db, tenant_id=ctx.tenant_id, action="document.identity_mismatch", actor_type="system", object_type="document",
                        object_id=document_id, result="flagged", reason="signed_id_differs_from_registered_id",
                        acting_for_person_id=ctx.person_id if ctx.via_helper else None)  # fmt: skip
        if application.status == "needs_proof":
            _proof_received(db, ctx, application.id)
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    view = citizen_view(str(document_id), kind, check, identity_mismatch=mismatch or unbound)
    return DocumentOut(document=view, application_version=application.version)


def _proof_received(db: Session, ctx: PersonContext, application_id: UUID) -> None:
    """New proof for an application waiting on it: its case goes back to an officer (Track A2), when present."""
    proof_received = hooks.optional(PROOF_RECEIVED)
    if proof_received is None:
        return
    try:
        with db.begin_nested():
            proof_received(db, tenant_id=ctx.tenant_id, application_id=application_id)
    except Exception:  # noqa: BLE001
        log.exception("proof_received failed; the case stays where it is")


def _owner_in_tenant(document_id: UUID, tenant_id: UUID) -> UUID | None:
    """Narrow system lookup: whose document is this, if it exists at all? Lets an officer see "consent withdrawn"
    instead of a bare 404, and lets the refused attempt appear in that person's access log."""
    with system_session() as sdb:
        return sdb.scalar(
            select(models.Document.person_id).where(models.Document.id == document_id, models.Document.tenant_id == tenant_id)
        )


def content_for_officer(db: Session, principal: Principal, document_id: UUID) -> tuple[bytes, str]:
    document = db.get(models.Document, document_id)  # RLS: same tenant and an active consent for the person
    if document is None or document.tenant_id != principal.tenant_id:
        owner = _owner_in_tenant(document_id, principal.tenant_id)
        if owner is not None:
            metrics.ACCESS_DENIED.labels("consent").inc()
            audit.write_independent(
                tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=owner, object_type="document", object_id=document_id, result="denied", reason="consent_required",
                details={"attempted": "document_content"},
            )  # fmt: skip
            raise Forbidden("This person has not agreed to share their information.", code="consent_required")
        raise NotFound("That document does not exist.")
    consent = active_consent(db, tenant_id=principal.tenant_id, person_id=document.person_id)
    if consent is None or "documents" not in (consent.field_scopes or []):
        # The database allows the read while any consent is active; a consent narrowed to exclude documents still stops it.
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            acting_for_person_id=document.person_id, object_type="document", object_id=document_id, result="denied",
            reason="consent_scope_missing", details={"attempted": "document_content"},
        )  # fmt: skip
        raise Forbidden("This person has not agreed to share their documents.", code="consent_scope_missing")
    data = _stored_bytes(db, document)
    if data is None:
        raise NotFound("The stored file is missing.", code="file_missing")
    audit.write(db, tenant_id=principal.tenant_id, action="document.viewed", actor_id=principal.user_id, actor_role=principal.role,
                object_type="document", object_id=document.id, details={"kind": document.kind})  # fmt: skip
    record_view(db, principal, document.person_id, what="document_content", ref_id=document.id, details={"kind": document.kind})
    db.commit()
    return data, document.mime
