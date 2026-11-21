"""What a citizen is told about an uploaded document. Pure; no detection details ever reach this view."""

from __future__ import annotations

from typing import Final

from app.contracts.common import DocumentKind
from app.contracts.documents import DocumentCheck, DocumentCitizenView

# The consent scopes an upload of each kind needs, besides "documents".
KIND_SCOPES: Final[dict[str, frozenset[str]]] = {
    "rahat_id": frozenset({"documents", "identity"}),
    "income_proof": frozenset({"documents", "income"}),
    "other": frozenset({"documents"}),
}


def signed_qr_valid(check: DocumentCheck | None) -> bool:
    return bool(check and check.qr.found and check.qr.signature_valid is True and check.qr.payload)


def needs_retake(check: DocumentCheck) -> bool:
    """Poor quality asks for a retake; it is never a rejection. Glare with a valid signed QR is not blocked."""
    if check.quality == "ok":
        return False
    return not (check.quality == "glare" and signed_qr_valid(check))


def document_status(check: DocumentCheck | None, *, identity_mismatch: bool = False) -> str:
    """Value for `documents.status`: uploaded | checked | retake | suspect | mismatch."""
    if check is None:
        return "uploaded"
    if identity_mismatch:
        return "mismatch"
    if needs_retake(check):
        return "retake"
    if check.authenticity.abstained or check.authenticity.choice != "genuine" or check.authenticity.route != "auto":
        return "suspect"
    return "checked"


def citizen_view(document_id: str, kind: DocumentKind, check: DocumentCheck | None, *, identity_mismatch: bool = False) -> DocumentCitizenView:
    if check is None:
        # No checker in this build, or it failed: the upload is kept and a person looks at it.
        return DocumentCitizenView(document_id=document_id, kind=kind, accepted=True, quality="unchecked", message_key="doc_person_will_check")
    if not identity_mismatch and needs_retake(check):
        return DocumentCitizenView(
            document_id=document_id, kind=kind, accepted=False, quality=check.quality,
            retake_hint=check.retake_hint or f"retake_{check.quality}", message_key=f"doc_retake_{check.quality}",
        )  # fmt: skip
    status = document_status(check, identity_mismatch=identity_mismatch)
    key = "doc_ok" if status == "checked" else "doc_person_will_check"
    return DocumentCitizenView(document_id=document_id, kind=kind, accepted=True, quality=check.quality, message_key=key)
