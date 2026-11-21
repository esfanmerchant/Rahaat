"""Scam checker for everyone signed in, the Scam Map for staff, and public warnings.

The checker analyses the text as data: it never opens a link or contacts a sender. Citizens get a plain
answer with reasons in their language and no scores; officers, admins and auditors also get the
probabilities and the weight of each signal.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Route, ScamLabel
from app.core.context import current_client_ip
from app.core.deps import ALL_ROLES, STAFF_ROLES, Principal, get_db
from app.core.policy import Policy
from app.modules.scam import service
from app.modules.scam.explain import lang_from_header
from app.modules.scam.schemas import (
    CampaignList,
    DisputeIn,
    DisputeOut,
    LabelIn,
    MapOut,
    MyReportList,
    ScamCheckIn,
    ScamCheckOut,
    ScamReportList,
    ScamReportOut,
    TrendsOut,
    WarningIn,
    WarningList,
    WarningOut,
)  # fmt: skip

router = APIRouter(prefix="/v1/scam", tags=["scam"])
_check = Policy("scam:check", ALL_ROLES, description="Check a message; stored redacted with the district only")
_own = Policy("scam:read-own", ALL_ROLES, description="Your own checks; staff may read any report of the department")
_dispute = Policy("scam:dispute", ALL_ROLES, description="'This is real, ask a person' on your own check: opens a scam_review case")
_reports = Policy("scam:reports", list(STAFF_ROLES), description="The department's reports, redacted")
_label = Policy("scam:label", ["officer"], description="Confirm what a reported message really was (feeds the mistakes ledger)")
_map = Policy("scam:map", list(STAFF_ROLES), description="Scam Map counts with k-anonymity, campaigns and trends")
_warn = Policy("scam:warn", ["officer", "admin"], description="Publish or withdraw a public scam warning")
_warnings = Policy("scam:warnings", ALL_ROLES, description="Public scam warnings of your department")
_status = Policy("scam:status", list(STAFF_ROLES), description="Which scam classifier is running")

Days = Query(14, ge=1, le=service.MAX_DAYS, description="The last N calendar days, Pakistan time")
Kind = Query("scam", description="'scam': the four scam kinds (default); 'all': every label")


def _lang(accept_language: str | None) -> str:
    return lang_from_header(accept_language)


@router.post("/check", response_model=ScamCheckOut, summary="Is this message a scam? Never opens links; may answer 'not sure'")
def check_message(
    body: ScamCheckIn,
    principal: Principal = Depends(_check),
    db: Session = Depends(get_db),
    accept_language: str | None = Header(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=80),
) -> ScamCheckOut:
    out = service.check(db, principal, body, lang=_lang(accept_language), ip=current_client_ip(), idempotency_key=idempotency_key)
    db.commit()
    return out


@router.get("/reports/mine", response_model=MyReportList, summary="My checks, newest first")
def my_reports(
    principal: Principal = Depends(_own),
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=300),
) -> MyReportList:
    return service.my_reports(db, principal, limit=limit, cursor=cursor)


@router.get("/reports/{report_id}", response_model=ScamCheckOut, summary="One check: your own, or any of the department's for staff")
def get_report(
    report_id: uuid.UUID, principal: Principal = Depends(_own), db: Session = Depends(get_db), accept_language: str | None = Header(None)
) -> ScamCheckOut:
    return service.get_report(db, principal, report_id, _lang(accept_language))


@router.post("/reports/{report_id}/dispute", response_model=DisputeOut, summary="This is real, ask a person (opens a scam_review case)")
def dispute_report(
    report_id: uuid.UUID,
    body: DisputeIn | None = None,
    principal: Principal = Depends(_dispute),
    db: Session = Depends(get_db),
    accept_language: str | None = Header(None),
) -> DisputeOut:
    out = service.dispute(db, principal, report_id, note=body.note if body else None, lang=_lang(accept_language))
    db.commit()
    return out


@router.get("/reports", response_model=ScamReportList, summary="The department's reports, redacted, newest first")
def list_reports(
    principal: Principal = Depends(_reports),
    db: Session = Depends(get_db),
    label: ScamLabel | None = Query(None),
    disputed: bool | None = Query(None),
    route: Route | None = Query(None),
    district: str | None = Query(None, max_length=64),
    cluster_id: uuid.UUID | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=300),
) -> ScamReportList:
    return service.list_reports(db, principal, label=label, disputed=disputed, route=route, district=district, cluster_id=cluster_id,
                                limit=limit, cursor=cursor)  # fmt: skip


@router.post("/reports/{report_id}/label", response_model=ScamReportOut, summary="Confirm what the message really was")
def label_report(report_id: uuid.UUID, body: LabelIn, principal: Principal = Depends(_label), db: Session = Depends(get_db)) -> ScamReportOut:
    out = service.set_label(db, principal, report_id, label=body.label, reason=body.reason)
    db.commit()
    return out


@router.get("/map", response_model=MapOut, summary="Reports by district, kind and day; groups under 5 are hidden")
def scam_map(principal: Principal = Depends(_map), db: Session = Depends(get_db), days: int = Days,
             kind: Literal["scam", "all"] = Kind) -> MapOut:  # fmt: skip
    return service.map_data(db, principal, days=days, kind=kind)


@router.get("/trends", response_model=TrendsOut, summary="Reports per day and kind; days with 1 to 4 reports are hidden")
def scam_trends(principal: Principal = Depends(_map), db: Session = Depends(get_db), days: int = Days,
                kind: Literal["scam", "all"] = Kind) -> TrendsOut:  # fmt: skip
    return service.trends(db, principal, days=days, kind=kind)


@router.get("/campaigns", response_model=CampaignList, summary="The largest campaigns (same message, many reports)")
def scam_campaigns(principal: Principal = Depends(_map), db: Session = Depends(get_db), days: int = Days,
                   limit: int = Query(10, ge=1, le=50)) -> CampaignList:  # fmt: skip
    return service.campaigns(db, principal, days=days, limit=limit)


@router.post("/warnings", response_model=WarningOut, status_code=201, summary="Publish a public warning for a campaign or district")
def publish_warning(
    body: WarningIn,
    principal: Principal = Depends(_warn),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=80),
) -> WarningOut:
    out = service.publish_warning(db, principal, body, idempotency_key=idempotency_key)
    db.commit()
    return out


@router.post("/warnings/{warning_id}/withdraw", response_model=WarningOut, summary="Withdraw a public warning")
def withdraw_warning(warning_id: uuid.UUID, principal: Principal = Depends(_warn), db: Session = Depends(get_db)) -> WarningOut:
    out = service.withdraw_warning(db, principal, warning_id)
    db.commit()
    return out


@router.get("/warnings", response_model=WarningList, summary="Public scam warnings of your department, newest first")
def list_warnings(
    principal: Principal = Depends(_warnings),
    db: Session = Depends(get_db),
    district: str | None = Query(None, max_length=64, description="Also include warnings for this district"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=300),
) -> WarningList:
    return service.list_warnings(db, principal, district=district, limit=limit, cursor=cursor)


@router.get("/status", summary="Which scam classifier is running (for the system health screen)")
def classifier_status(_: Principal = Depends(_status)) -> dict[str, object]:
    return service.provider_status()
