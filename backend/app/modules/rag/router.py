"""The rules assistant (`POST /v1/ask`) and the versioned knowledge base it answers from."""

from __future__ import annotations

from collections.abc import Generator
from typing import cast

from fastapi import APIRouter, Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.context import current_client_ip
from app.core.deps import ALL_ROLES, Principal, get_claims, get_db, get_principal
from app.core.policy import Policy, Public
from app.modules.rag import service
from app.modules.rag.ingest import ingest
from app.modules.rag.schemas import AskIn, AskOut, KbDocumentOut, KbIngestOut

router = APIRouter(prefix="/v1", tags=["rules assistant"])

_ask = Public("anyone may ask about the published rules: strict per-address limits; a signed-in caller's token is fully checked")
_read = Policy("kb:read", ALL_ROLES, description="The versioned policy documents the assistant answers from")
_ingest = Policy("kb:ingest", ["admin"], description="Load new versions of the policy corpus for this department")
_optional_bearer = HTTPBearer(auto_error=False, description="Optional: sign in for higher limits and your own department")


def _optional_principal(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer)) -> Principal | None:
    """No token: anonymous. A token: checked exactly like every other route (expired or revoked is a 401, never anonymous)."""
    if credentials is None or not credentials.credentials:
        return None
    claims = get_claims(credentials)
    sessions = cast(Generator[Session, None, None], get_db(claims))
    db = next(sessions)
    try:
        return get_principal(request, claims, db)
    finally:
        sessions.close()


@router.post("/ask", response_model=AskOut, summary="Ask about the Rahat rules; answers cite the document, version and section",
             responses={429: {"description": "too_many_requests"}, 404: {"description": "department_not_found"}})  # fmt: skip
def ask(
    body: AskIn,
    _: None = Depends(_ask),
    principal: Principal | None = Depends(_optional_principal),
    accept_language: str | None = Header(default=None),
) -> AskOut:
    """Answers only with sentences copied from approved policy text, at most three, each with a citation.

    Below the retrieval threshold, or when a guard objects, it refuses: "I am not sure. Please ask a person."
    It never promises eligibility or a payment; answers about them carry a notice that only an officer decides.
    """
    return service.ask(body, principal=principal, accept_language=accept_language, client_ip=current_client_ip())


@router.get("/kb/documents", response_model=list[KbDocumentOut], summary="Policy documents, versions and sections")
def documents(principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> list[KbDocumentOut]:
    return service.list_documents(db, principal.tenant_id)


@router.post("/kb/ingest", response_model=KbIngestOut, summary="Load the policy corpus files (new versions only; edits need a new version)")
def ingest_corpus(principal: Principal = Depends(_ingest), db: Session = Depends(get_db)) -> KbIngestOut:
    report = ingest(db, principal.tenant_id, actor_type="user", actor_id=principal.user_id, actor_role=principal.role)
    db.commit()
    return KbIngestOut(added=report.added, unchanged=report.unchanged, retired=report.retired, refused=report.refused)
