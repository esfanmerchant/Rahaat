from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session

from app.contracts.api import DocumentOut
from app.contracts.common import DocumentKind
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.documents import service
from app.modules.people.context import PersonContext, acting_person

router = APIRouter(prefix="/v1", tags=["documents"])

_upload = acting_person("documents:upload-own", "upload", description="Add a photo of an ID or proof to an application")
_view = Policy("documents:read-content", ["officer"], description="Officers view an uploaded document; needs the person's consent")


@router.post("/applications/{application_id}/documents", response_model=DocumentOut, status_code=201,
             summary="Upload a photo of an ID or proof (JPEG, PNG or WebP, at most 5 MB)")  # fmt: skip
def upload_document(
    application_id: UUID,
    file: UploadFile = File(..., description="The photo. Its name and declared type are ignored."),
    kind: DocumentKind = Form("rahat_id"),
    ctx: PersonContext = Depends(_upload),
    db: Session = Depends(get_db),
) -> DocumentOut:
    return service.upload(db, ctx, application_id, file.file, kind)


@router.get("/documents/{document_id}/content", summary="The stored, re-encoded image (officers only)",
            responses={200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}}})  # fmt: skip
def document_content(document_id: UUID, principal: Principal = Depends(_view), db: Session = Depends(get_db)) -> Response:
    data, mime = service.content_for_officer(db, principal, document_id)
    return Response(content=data, media_type=mime, headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})
