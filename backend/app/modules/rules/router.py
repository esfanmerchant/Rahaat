"""Rule versions API (`/v1/rules`). Admins write; admins and auditors read. Publishing needs a second admin."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.rules import dsl as rule_dsl
from app.modules.rules import service
from app.modules.rules.schemas import (
    DiffChange,
    DiffOut,
    DraftCreate,
    DraftUpdate,
    DryRunIn,
    DryRunOut,
    DslIn,
    ReasonIn,
    RuleSetOut,
    RuleVersionList,
    RuleVersionOut,
    ValidationIssue,
    ValidationOut,
)

router = APIRouter(prefix="/v1/rules", tags=["rules"])
_read = Policy("rules:read", ["admin", "auditor"], description="Read rule sets and versions")
_write = Policy("rules:write", ["admin"], description="Draft, validate, dry-run and request approval of rule versions")
_publish = Policy("rules:publish", ["admin"], description="Publish or send back a rule version (a second admin, never the author)")


@router.get("/sets", response_model=list[RuleSetOut], summary="Rule sets of this department and their active version")
def list_sets(principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> list[RuleSetOut]:
    return service.list_sets(db, principal)


@router.get("/versions", response_model=RuleVersionList, summary="Versions of a rule set, newest first")
def list_versions(
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    rule_set_id: UUID | None = Query(None, description="Defaults to the department's first rule set"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: int | None = Query(None, ge=1, description="Return versions numbered below this"),
) -> RuleVersionList:
    items, next_cursor = service.list_versions(db, principal, rule_set_id, limit=limit, before_version_no=cursor)
    return RuleVersionList(items=items, next_cursor=next_cursor)


@router.get("/versions/{version_id}", response_model=RuleVersionOut, summary="One rule version with its validation result")
def get_version(version_id: UUID, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> RuleVersionOut:
    return service.get_version(db, principal, version_id)


@router.post("/versions", response_model=RuleVersionOut, status_code=201, summary="Create a draft from a parent version")
def create_draft(body: DraftCreate, principal: Principal = Depends(_write), db: Session = Depends(get_db)) -> RuleVersionOut:
    out = service.create_draft(db, principal, parent_version_id=body.parent_version_id, dsl=body.dsl,
                               description_en=body.description_en, description_ur=body.description_ur)  # fmt: skip
    db.commit()
    return out


@router.patch("/versions/{version_id}", response_model=RuleVersionOut, summary="Edit a draft (published versions never change)")
def update_draft(version_id: UUID, body: DraftUpdate, principal: Principal = Depends(_write), db: Session = Depends(get_db)) -> RuleVersionOut:
    out = service.update_draft(db, principal, version_id, dsl=body.dsl, description_en=body.description_en, description_ur=body.description_ur)
    db.commit()
    return out


@router.post("/validate", response_model=ValidationOut, summary="Check rules without saving them")
def validate_dsl(body: DslIn, principal: Principal = Depends(_write)) -> ValidationOut:
    errors = rule_dsl.validate(body.dsl)
    return ValidationOut(valid=not errors, errors=[ValidationIssue(**e.as_dict()) for e in errors])


@router.post("/versions/{version_id}/validate", response_model=ValidationOut, summary="Check a stored version")
def validate_version(version_id: UUID, principal: Principal = Depends(_write), db: Session = Depends(get_db)) -> ValidationOut:
    errors = service.validate_version(db, principal, version_id)
    db.commit()
    return ValidationOut(valid=not errors, errors=[ValidationIssue(**e.as_dict()) for e in errors])


@router.post("/versions/{version_id}/dry-run", response_model=DryRunOut, summary="Decide one supplied case with this version; stores nothing")
def dry_run(version_id: UUID, body: DryRunIn, principal: Principal = Depends(_write), db: Session = Depends(get_db)) -> DryRunOut:
    result = service.dry_run(db, principal, version_id, body.input)
    db.commit()
    return DryRunOut(rule_version_id=version_id, result=result)


@router.get("/versions/{version_id}/diff", response_model=DiffOut, summary="What changed against the active version (or another one)")
def diff(
    version_id: UUID,
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    against: UUID | None = Query(None, description="Defaults to the active version"),
) -> DiffOut:
    against_id, changes = service.diff_version(db, principal, version_id, against)
    return DiffOut(version_id=version_id, against_version_id=against_id, changes=[DiffChange(**c) for c in changes])


@router.post("/versions/{version_id}/request-approval", response_model=RuleVersionOut, summary="Freeze a valid draft and ask a second admin")
def request_approval(version_id: UUID, body: ReasonIn, principal: Principal = Depends(_write), db: Session = Depends(get_db)) -> RuleVersionOut:
    out = service.request_approval(db, principal, version_id, body.reason)
    db.commit()
    return out


@router.post("/versions/{version_id}/publish", response_model=RuleVersionOut, summary="Publish (second admin only); applies to the next decision")
def publish(version_id: UUID, body: ReasonIn, principal: Principal = Depends(_publish), db: Session = Depends(get_db)) -> RuleVersionOut:
    out = service.publish(db, principal, version_id, body.reason)
    db.commit()
    return out


@router.post("/versions/{version_id}/reject", response_model=RuleVersionOut, summary="Send a pending version back to draft (second admin only)")
def reject(version_id: UUID, body: ReasonIn, principal: Principal = Depends(_publish), db: Session = Depends(get_db)) -> RuleVersionOut:
    out = service.reject(db, principal, version_id, body.reason)
    db.commit()
    return out


@router.post("/versions/{version_id}/rollback", response_model=RuleVersionOut, status_code=201,
             summary="New version copying an earlier published one; needs a second admin to publish")  # fmt: skip
def rollback(version_id: UUID, body: ReasonIn, principal: Principal = Depends(_write), db: Session = Depends(get_db)) -> RuleVersionOut:
    out = service.rollback(db, principal, version_id, body.reason)
    db.commit()
    return out
