"""Scam checks, reports, campaigns, the Scam Map and public warnings.

    classify_message(text, sender)          the contract other tracks call: TypedDecision[ScamLabel], no storage
    check(db, principal, body, lang=..., ip=..., idempotency_key=...)   classify, store redacted, cluster, audit

A report keeps the text redacted (ids, phones, emails, long numbers masked; links defanged), a keyed hash of
the text, the sender masked, and the district only. Citizens see their own reports; staff see the tenant's.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, literal_column, or_, select, tuple_
from sqlalchemy.orm import Session

from app.contracts.common import ScamLabel
from app.contracts.decision import HandoffPackage, Hypothesis, TypedDecision, UncertainField
from app.core import audit
from app.core.crypto import blind_index
from app.core.deps import STAFF_ROLES, Principal
from app.core.errors import NotFound, ServiceUnavailable, Unprocessable
from app.core.logging import get_logger, redact
from app.db import models
from app.modules.cases import paging
from app.modules.scam import aggregates, clustering, explain, ratelimit, runtime
from app.modules.scam.districts import normalise_district
from app.modules.scam.engine import CodeCheck, ScamResult
from app.modules.scam.model import CLASSES, SCAM_CLASSES
from app.modules.scam.schemas import (
    CampaignList,
    CampaignOut,
    DisputeOut,
    DistrictCount,
    DistrictLabelCount,
    MapCell,
    MapOut,
    MyReportList,
    MyReportOut,
    ReasonOut,
    ReviewOut,
    ScamCheckIn,
    ScamCheckOut,
    ScamReportList,
    ScamReportOut,
    SignalWeightOut,
    StaffDetailOut,
    TrendPoint,
    TrendSeries,
    TrendsOut,
    UrlOut,
    VerifiedOut,
    WarningIn,
    WarningList,
    WarningOut,
)  # fmt: skip
from app.modules.scam.signals import DEFAULT_OFFICIAL_SENDER, PHONE_IN_TEXT, URL_PATTERN, UrlFinding, defang
from app.modules.scam.text import normalise

log = get_logger("rahat.scam")
SCAM = frozenset(SCAM_CLASSES)
CLUSTER_LOOKBACK_DAYS = 30
MAX_DAYS = 90
_LONG_NUMBER = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_DISPUTE_MESSAGE = {
    "en": "Thank you. A person will check this message, and you can see the answer here.",
    "ur": "شکریہ۔ ایک افسر اس پیغام کو دیکھے گا، اور آپ جواب یہیں دیکھ سکیں گے۔",
}


# --- the contract other tracks call ---------------------------------------------------------------------


def _lookup(code: str) -> CodeCheck:
    from app.modules.notifications.service import lookup_verify_code

    found = lookup_verify_code(code)
    return CodeCheck(genuine=found.genuine, template=found.template, channel=found.channel, department=found.department,
                     sent_at=found.sent_at)  # fmt: skip


def classify_message(text: str, sender: str | None = None, *, official_sender: str = DEFAULT_OFFICIAL_SENDER) -> TypedDecision[ScamLabel]:
    """Is this message a scam? Abstains (route human) when unsure or when the model is unavailable. Stores nothing."""
    try:
        return runtime.classify(text, sender, official_sender=official_sender, verify=_lookup).decision
    except runtime.ModelUnavailable:
        return TypedDecision[ScamLabel](choice=None, probabilities={}, confidence=0.0, route="human", reasons=["model_unavailable"],
                                        model_version="unavailable", abstained=True)  # fmt: skip


def provider_status() -> dict[str, Any]:
    """For /v1/system/health."""
    return runtime.status()


# --- storing a check ------------------------------------------------------------------------------------


def redact_text(text: str) -> str:
    """Mask identifiers, phones (all spellings), emails and long numbers; defang links; drop control characters."""
    lines = []
    for line in _CONTROL.sub(" ", text).split("\n"):
        line = URL_PATTERN.sub(lambda m: defang(m.group(1)), line)
        line = PHONE_IN_TEXT.sub("[phone]", redact(line))
        lines.append(_LONG_NUMBER.sub("[number]", line))
    return "\n".join(lines)[:2000]


def _text_hash(text: str, tenant_id: uuid.UUID) -> str:
    # Keyed, so a stored hash cannot confirm a guessed message.
    return blind_index(" ".join(normalise(text).lower().split()), scope=f"scam:{tenant_id}")


def _url_dict(finding: UrlFinding) -> dict[str, Any]:
    return {"url": finding.defanged, "host": finding.host, "flags": list(finding.flags), "risk": finding.risk}


def _tenant_settings(db: Session, tenant_id: uuid.UUID) -> tuple[str, frozenset[str]]:
    tenant = db.get(models.Tenant, tenant_id)
    config = (tenant.config or {}) if tenant else {}
    sender = str(config.get("official_sender") or DEFAULT_OFFICIAL_SENDER)[:32]
    domains = frozenset(str(d).lower() for d in config.get("official_domains") or [] if isinstance(d, str))
    return sender, domains


def _classification(result: ScamResult, *, reporter_user_id: uuid.UUID | None, source: str, idem: str | None) -> dict[str, Any]:
    decision = result.decision
    return {
        "certainty": result.certainty, "reasons": result.reasons, "choice": decision.choice, "abstained": decision.abstained,
        "route": decision.route, "probabilities": decision.probabilities, "confidence": decision.confidence,
        "model_version": decision.model_version, "decision_reasons": decision.reasons, "p_scam": result.p_scam,
        "p_scam_text": result.p_scam_text, "text_probabilities": result.text_probabilities, "contributions": result.contributions,
        "text_weight": result.text_weight, "compared_with": result.compared_with, "abstain_reason": result.abstain_reason,
        "verify": result.verify, "costs": result.costs, "thresholds": result.thresholds, "fired": result.signals.fired(),
        "script": result.signals.script, "sender_kind": result.signals.sender.kind,
        "reporter_user_id": str(reporter_user_id) if reporter_user_id else None, "source": source, "idem": idem,
    }  # fmt: skip


def _assign_cluster(db: Session, report: models.ScamReport, text: str, when: datetime) -> None:
    values = clustering.minhash(text)
    candidates = db.scalars(
        select(models.ScamCluster)
        .where(models.ScamCluster.tenant_id == report.tenant_id, models.ScamCluster.last_seen >= when - timedelta(days=CLUSTER_LOOKBACK_DAYS))
        .order_by(models.ScamCluster.last_seen.desc(), models.ScamCluster.id).limit(500)
    ).all()  # fmt: skip
    match = clustering.best_match(values, [(c, list((c.data or {}).get("minhash") or [])) for c in candidates])
    if match is None:
        cluster = models.ScamCluster(
            id=uuid.uuid4(), tenant_id=report.tenant_id, label=report.label, signature=clustering.signature(values),
            sample_text=report.text_redacted[:300], size=1, first_seen=when, last_seen=when, created_at=when,
            data={"minhash": values, "labels": {report.label: 1}, "template_hash": clustering.template_hash(text)},
        )  # fmt: skip
        db.add(cluster)
        db.flush()
    else:
        cluster = match[0]
        db.refresh(cluster, with_for_update=True)  # one writer at a time per campaign
        labels = dict((cluster.data or {}).get("labels") or {})
        labels[report.label] = int(labels.get(report.label, 0)) + 1
        cluster.size = (cluster.size or 0) + 1
        cluster.label = max(sorted(labels), key=lambda k: labels[k])
        cluster.first_seen = min(filter(None, (cluster.first_seen, when)))
        cluster.last_seen = max(filter(None, (cluster.last_seen, when)))
        cluster.data = {**(cluster.data or {}), "labels": labels}
    report.cluster_id = cluster.id


def store_report(
    db: Session, *, tenant_id: uuid.UUID, text: str, channel: str, district: str | None, result: ScamResult,
    reporter_user_id: uuid.UUID | None, reporter_person_id: uuid.UUID | None, created_at: datetime | None = None,
    source: str = "api", idem: str | None = None,
) -> models.ScamReport:  # fmt: skip
    when = created_at or datetime.now(UTC)
    decision = result.decision
    report = models.ScamReport(
        id=uuid.uuid4(), tenant_id=tenant_id, reporter_person_id=reporter_person_id, channel=channel, text_redacted=redact_text(text),
        text_hash=_text_hash(text, tenant_id), sender=result.signals.sender.shown, urls=[_url_dict(u) for u in result.signals.urls],
        label=decision.choice or "unknown", confidence=decision.confidence, route=decision.route,
        classification=_classification(result, reporter_user_id=reporter_user_id, source=source, idem=idem), district=district,
        created_at=when, disputed=False,
    )  # fmt: skip
    db.add(report)
    db.flush()
    if report.label in SCAM:
        _assign_cluster(db, report, text, when)
        db.flush()
    return report


def _person_district(db: Session, principal: Principal) -> str | None:
    if principal.person_id is None:
        return None
    person = db.get(models.Person, principal.person_id)  # RLS: only a person the caller may read
    return normalise_district(person.district) if person is not None else None


def check(db: Session, principal: Principal, body: ScamCheckIn, *, lang: str, ip: str, idempotency_key: str | None) -> ScamCheckOut:
    ratelimit.check(str(principal.user_id), ip)
    idem = hashlib.sha256(f"{principal.user_id}:{idempotency_key}".encode()).hexdigest()[:32] if idempotency_key else None
    if idem:
        existing = db.scalar(select(models.ScamReport).where(models.ScamReport.tenant_id == principal.tenant_id,
                                                             models.ScamReport.classification["idem"].astext == idem).limit(1))  # fmt: skip
        if existing is not None:
            return view(existing, principal, lang)
    official, domains = _tenant_settings(db, principal.tenant_id)
    try:
        result = runtime.classify(body.text, body.sender, official_sender=official, official_domains=domains, verify=_lookup)
    except runtime.ModelUnavailable as exc:
        raise ServiceUnavailable("The scam checker is not available right now. Try again soon.", code="scam_checker_unavailable") from exc
    district = normalise_district(body.district) or _person_district(db, principal)
    report = store_report(db, tenant_id=principal.tenant_id, text=body.text, channel=body.channel, district=district, result=result,
                          reporter_user_id=principal.user_id, reporter_person_id=principal.person_id, idem=idem)  # fmt: skip
    audit.write(
        db, tenant_id=principal.tenant_id, action="scam.checked", actor_id=principal.user_id, actor_role=principal.role,
        object_type="scam_report", object_id=report.id, input_hash=report.text_hash, model_version=result.decision.model_version,
        details={"label": report.label, "certainty": result.certainty, "route": report.route, "channel": body.channel,
                 "cluster_id": str(report.cluster_id) if report.cluster_id else None, "urls": len(report.urls or [])},
    )  # fmt: skip
    return view(report, principal, lang)


# --- reading a report -----------------------------------------------------------------------------------


def _owner(report: models.ScamReport, principal: Principal) -> bool:
    return (report.classification or {}).get("reporter_user_id") == str(principal.user_id)


def _url_out(item: dict[str, Any], lang: str) -> UrlOut:
    flags = [str(f) for f in item.get("flags") or []]
    risk = item.get("risk") if item.get("risk") in ("high", "medium", "low") else "low"
    return UrlOut(url=str(item.get("url", "")), host=str(item.get("host", "")), risk=risk, flags=flags,
                  flag_texts=explain.url_flag_texts(flags, lang))  # fmt: skip


def _review(report: models.ScamReport) -> ReviewOut:
    case_id = (report.classification or {}).get("case_id")
    status = "done" if report.confirmed_label else "waiting" if report.disputed else "none"
    return ReviewOut(status=status, confirmed_label=report.confirmed_label, case_id=uuid.UUID(case_id) if case_id else None)


def view(report: models.ScamReport, principal: Principal, lang: str) -> ScamCheckOut:
    c = report.classification or {}
    certainty = str(c.get("certainty") or "not_sure")
    label = c.get("choice")
    words = explain.citizen_text(certainty, label, [str(r) for r in c.get("reasons") or []], lang)
    verify = c.get("verify")
    detail = None
    if principal.role in STAFF_ROLES:
        detail = StaffDetailOut(
            probabilities=c.get("probabilities") or {}, confidence=float(c.get("confidence") or report.confidence),
            abstained=bool(c.get("abstained")), model_version=str(c.get("model_version") or ""), p_scam=float(c.get("p_scam") or 0.0),
            p_scam_text=c.get("p_scam_text"), text_probabilities=c.get("text_probabilities") or {}, text_model_weight=c.get("text_weight"),
            compared_with=c.get("compared_with"), signals=[SignalWeightOut(**s) for s in c.get("contributions") or []],
            fired=[str(s) for s in c.get("fired") or []], abstain_reason=c.get("abstain_reason"), route_costs=c.get("costs") or {},
            thresholds=c.get("thresholds") or {}, script=str(c.get("script") or ""), sender_kind=str(c.get("sender_kind") or "none"),
            sender=report.sender, decision_reasons=[str(r) for r in c.get("decision_reasons") or []],
        )  # fmt: skip
    return ScamCheckOut(
        report_id=report.id, label=label, label_text=words["label_text"], certainty=certainty,
        route=report.route, lang=lang if lang in ("ur", "en") else "ur", headline=words["headline"],
        reasons=[ReasonOut(**r) for r in words["reasons"]], what_to_do=words["what_to_do"],
        urls=[_url_out(u, lang) for u in report.urls or []],
        verified=VerifiedOut(genuine=bool(verify.get("genuine")), department=verify.get("department"), sent_at=verify.get("sent_at"),
                             template=verify.get("template")) if verify else None,
        audio_keys=words["audio_keys"], can_dispute=_owner(report, principal) and not report.disputed, review=_review(report),
        checked_at=paging.iso(report.created_at) or "", detail=detail,
    )  # fmt: skip


def _load(db: Session, report_id: uuid.UUID, *, lock: bool = False) -> models.ScamReport:
    query = select(models.ScamReport).where(models.ScamReport.id == report_id)
    report = db.scalar(query.with_for_update() if lock else query)
    if report is None:  # another tenant's report is invisible under RLS
        raise NotFound("No such report.")
    return report


def get_report(db: Session, principal: Principal, report_id: uuid.UUID, lang: str) -> ScamCheckOut:
    report = _load(db, report_id)
    if principal.role not in STAFF_ROLES and not _owner(report, principal):
        raise NotFound("No such report.")  # someone else's check: not even its existence is shown
    return view(report, principal, lang)


def my_reports(db: Session, principal: Principal, *, limit: int, cursor: str | None) -> MyReportList:
    query = select(models.ScamReport).where(models.ScamReport.tenant_id == principal.tenant_id,
                                            models.ScamReport.classification["reporter_user_id"].astext == str(principal.user_id))  # fmt: skip
    rows = _page(db, query, limit, cursor)
    items = [MyReportOut(id=r.id, checked_at=paging.iso(r.created_at) or "", label=(r.classification or {}).get("choice"),
                         certainty=str((r.classification or {}).get("certainty") or "not_sure"), disputed=r.disputed, review=_review(r))
             for r in rows[:limit]]  # fmt: skip
    return MyReportList(items=items, next_cursor=_next(rows, limit))


def _page(db: Session, query: Any, limit: int, cursor: str | None) -> list[models.ScamReport]:
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        query = query.where(tuple_(models.ScamReport.created_at, models.ScamReport.id) < tuple_(paging.as_datetime(created), paging.as_uuid(row_id)))
    return list(db.scalars(query.order_by(models.ScamReport.created_at.desc(), models.ScamReport.id.desc()).limit(limit + 1)).all())


def _next(rows: list[models.ScamReport], limit: int) -> str | None:
    return paging.encode(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None


def _report_out(report: models.ScamReport) -> ScamReportOut:
    c = report.classification or {}
    return ScamReportOut(
        id=report.id, created_at=paging.iso(report.created_at) or "", channel=report.channel, label=report.label,
        certainty=c.get("certainty"), route=report.route, confidence=report.confidence, district=report.district, sender=report.sender,
        text_redacted=report.text_redacted, urls=[_url_out(u, "en") for u in report.urls or []], cluster_id=report.cluster_id,
        disputed=report.disputed, confirmed_label=report.confirmed_label, model_version=c.get("model_version"),
    )  # fmt: skip


def list_reports(db: Session, principal: Principal, *, label: str | None, disputed: bool | None, route: str | None, district: str | None,
                 cluster_id: uuid.UUID | None, limit: int, cursor: str | None) -> ScamReportList:  # fmt: skip
    query = select(models.ScamReport).where(models.ScamReport.tenant_id == principal.tenant_id)
    if label:
        query = query.where(models.ScamReport.label == label)
    if disputed is not None:
        query = query.where(models.ScamReport.disputed.is_(disputed))
    if route:
        query = query.where(models.ScamReport.route == route)
    if district:
        query = query.where(models.ScamReport.district == (normalise_district(district) or district))
    if cluster_id:
        query = query.where(models.ScamReport.cluster_id == cluster_id)
    rows = _page(db, query, limit, cursor)
    return ScamReportList(items=[_report_out(r) for r in rows[:limit]], next_cursor=_next(rows, limit))


# --- "this is real, ask a person" and the officer's answer ---------------------------------------------


def _handoff(report: models.ScamReport, note: str | None) -> HandoffPackage:
    c = report.classification or {}
    probs = {k: float(v) for k, v in (c.get("probabilities") or {}).items()}
    top = sorted(probs.items(), key=lambda kv: -kv[1])[:2]
    said = c.get("certainty") or "not_sure"
    has_code = bool(c.get("verify"))
    return HandoffPackage(
        question="Is this message a scam, or a real message the checker got wrong?",
        understanding=f"The checker answered '{said}' ({c.get('choice') or 'no label'}). The person asked for a person to check it.",
        uncertain_fields=[UncertainField(field="scam_label", value=c.get("choice"), confidence=float(c.get("confidence") or 0.0),
                                         why=str(c.get("abstain_reason") or "disputed_by_person"))],
        hypotheses=[Hypothesis(label=label, probability=round(p, 4)) for label, p in top],
        resolving_proof=None if has_code else "verify_code",
        suggested_question=None if has_code else "Ask for the whole message with the code at its end, and who sent it.",
        evidence={"scam_report_id": str(report.id), "text_redacted": report.text_redacted, "urls": report.urls or [], "sender": report.sender,
                  "channel": report.channel, "signals": c.get("fired") or [], "model_version": c.get("model_version"),
                  "note": redact_text(note)[:500] if note else None},
        expected_costs={k: float(v) for k, v in (c.get("costs") or {}).items()},
        guards=["disputed_by_person"],
    )  # fmt: skip


def dispute(db: Session, principal: Principal, report_id: uuid.UUID, *, note: str | None, lang: str) -> DisputeOut:
    from app.modules.cases.service import open_case

    report = _load(db, report_id, lock=True)
    if not _owner(report, principal):
        raise NotFound("No such report.")
    c = dict(report.classification or {})
    message = _DISPUTE_MESSAGE.get(lang, _DISPUTE_MESSAGE["ur"])
    if report.disputed and c.get("case_id"):  # asking twice is one request
        return DisputeOut(report_id=report.id, disputed=True, case_id=uuid.UUID(str(c["case_id"])), message=message)
    case = open_case(db, tenant_id=report.tenant_id, kind="scam_review", opened_reason="scam_disputed", handoff=_handoff(report, note),
                     confidence=report.confidence, priority=40)  # fmt: skip
    report.disputed = True
    report.classification = {**c, "case_id": str(case.id), "disputed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                             "dispute_note": redact_text(note)[:500] if note else None}  # fmt: skip
    audit.write(db, tenant_id=report.tenant_id, action="scam.disputed", actor_id=principal.user_id, actor_role=principal.role,
                object_type="scam_report", object_id=report.id, details={"case_id": str(case.id), "label": report.label,
                                                                         "certainty": c.get("certainty")})  # fmt: skip
    db.flush()
    return DisputeOut(report_id=report.id, disputed=True, case_id=case.id, message=message)


def set_label(db: Session, principal: Principal, report_id: uuid.UUID, *, label: str, reason: str) -> ScamReportOut:
    """An officer's answer. A real message the checker called a scam (or the reverse) lands in the mistakes ledger."""
    report = _load(db, report_id, lock=True)
    previous = report.confirmed_label
    report.confirmed_label = label
    mistake = (label in SCAM) != (report.label in SCAM) if report.label in CLASSES and not (report.classification or {}).get("abstained") else False
    review = {"by": str(principal.user_id), "reason": redact_text(reason)[:500], "at": datetime.now(UTC).isoformat(timespec="seconds"),
              "mistake": mistake}  # fmt: skip
    report.classification = {**(report.classification or {}), "review": review}
    audit.write(db, tenant_id=report.tenant_id, action="scam.label_confirmed", actor_id=principal.user_id, actor_role=principal.role,
                object_type="scam_report", object_id=report.id, reason=reason[:300],
                details={"label": label, "model_label": report.label, "previous": previous, "mistake": mistake})  # fmt: skip
    db.flush()
    return _report_out(report)


# --- the Scam Map ---------------------------------------------------------------------------------------


def _day() -> Any:
    # Calendar day in Pakistan time, whatever the database session's time zone is. Built from constants only,
    # so the SELECT and GROUP BY copies render as the same SQL (bound parameters would differ).
    return func.date(func.timezone(literal_column("'UTC'"), models.ScamReport.created_at) + literal_column("interval '5 hours'"))


def _labels(kind: str) -> list[str]:
    return list(SCAM_CLASSES) if kind == "scam" else list(CLASSES)


def map_data(db: Session, principal: Principal, *, days: int, kind: str) -> MapOut:
    first, last, since = aggregates.window(days)
    labels = _labels(kind)
    rows = db.execute(
        select(models.ScamReport.district, models.ScamReport.label, _day(), func.count())
        .where(models.ScamReport.tenant_id == principal.tenant_id, models.ScamReport.created_at >= since,
               models.ScamReport.district.is_not(None), models.ScamReport.label.in_(labels))
        .group_by(models.ScamReport.district, models.ScamReport.label, _day())
    ).all()  # fmt: skip
    fine = [((str(d), str(lb), str(day)), int(n)) for d, lb, day, n in rows]
    cells, hidden_cells = aggregates.suppress(sorted(fine))
    by_district_label, hidden_dl = aggregates.suppress(sorted(aggregates.rollup(fine, (0, 1)).items()))
    by_district, hidden_d = aggregates.suppress(sorted(aggregates.rollup(fine, (0,)).items()))
    return MapOut(
        days=days, k=aggregates.K, first_day=first.isoformat(), last_day=last.isoformat(), labels=labels,
        cells=[MapCell(district=str(k[0]), label=str(k[1]), day=str(k[2]), count=n) for k, n in cells],
        districts=[DistrictLabelCount(district=str(k[0]), label=str(k[1]), count=n) for k, n in by_district_label],
        district_totals=[DistrictCount(district=str(k[0]), count=n) for k, n in sorted(by_district, key=lambda kv: -kv[1])],
        hidden={"cells": hidden_cells, "districts": hidden_dl, "district_totals": hidden_d}, note=aggregates.NOTE,
    )  # fmt: skip


def trends(db: Session, principal: Principal, *, days: int, kind: str) -> TrendsOut:
    first, last, since = aggregates.window(days)
    labels = _labels(kind)
    rows = db.execute(
        select(models.ScamReport.label, _day(), func.count())
        .where(models.ScamReport.tenant_id == principal.tenant_id, models.ScamReport.created_at >= since, models.ScamReport.label.in_(labels))
        .group_by(models.ScamReport.label, _day())
    ).all()  # fmt: skip
    per_label: dict[str, dict[str, int]] = {label: {} for label in labels}
    total: dict[str, int] = {}
    for label, day, n in rows:
        per_label[str(label)][str(day)] = int(n)
        total[str(day)] = total.get(str(day), 0) + int(n)
    series = [TrendSeries(label=label, points=[TrendPoint(day=d, count=c) for d, c in aggregates.day_series(counts, first, last)])
              for label, counts in per_label.items()]  # fmt: skip
    return TrendsOut(days=days, k=aggregates.K, series=series, note=aggregates.NOTE,
                     total=[TrendPoint(day=d, count=c) for d, c in aggregates.day_series(total, first, last)])  # fmt: skip


def campaigns(db: Session, principal: Principal, *, days: int, limit: int) -> CampaignList:
    first, last, since = aggregates.window(days)
    in_window = (models.ScamReport.tenant_id == principal.tenant_id, models.ScamReport.created_at >= since)
    counts = db.execute(select(models.ScamReport.cluster_id, func.count()).where(*in_window, models.ScamReport.cluster_id.is_not(None))
                        .group_by(models.ScamReport.cluster_id)).all()  # fmt: skip
    shown, hidden = aggregates.suppress(sorted(((cid, int(n)) for cid, n in counts if cid is not None), key=lambda kv: (-kv[1], str(kv[0]))))
    top = shown[:limit]
    clusters = {c.id: c for c in db.scalars(select(models.ScamCluster).where(models.ScamCluster.id.in_([cid for cid, _ in top]))).all()}
    items: list[CampaignOut] = []
    for cluster_id, size in top:
        cluster = clusters.get(cluster_id)
        if cluster is None:
            continue
        of_cluster = (*in_window, models.ScamReport.cluster_id == cluster_id)
        districts = db.execute(select(models.ScamReport.district, func.count()).where(*of_cluster, models.ScamReport.district.is_not(None))
                               .group_by(models.ScamReport.district)).all()  # fmt: skip
        district_shown, _ = aggregates.suppress(sorted(((str(d), int(n)) for d, n in districts), key=lambda kv: -kv[1]))
        per_day = {str(day): int(n) for day, n in db.execute(select(_day(), func.count()).where(*of_cluster).group_by(_day())).all()}
        series = aggregates.day_series(per_day, first, last)
        senders = db.scalar(select(func.count(func.distinct(models.ScamReport.sender))).where(*of_cluster, models.ScamReport.sender.is_not(None)))
        hosts: list[str] = []
        for urls in db.scalars(select(models.ScamReport.urls).where(*of_cluster).limit(200)).all():
            for item in urls or []:
                host = str(item.get("host", ""))
                if host and host not in hosts and len(hosts) < 5:
                    hosts.append(host)
        items.append(CampaignOut(
            id=cluster.id, label=cluster.label, signature=cluster.signature, size=cluster.size, size_in_window=size,
            sample_text=cluster.sample_text, first_seen=paging.iso(cluster.first_seen), last_seen=paging.iso(cluster.last_seen),
            districts=[DistrictCount(district=d, count=n) for d, n in district_shown],
            trend=[TrendPoint(day=d, count=c) for d, c in series], hosts=hosts, senders=int(senders or 0),
        ))  # fmt: skip
    return CampaignList(days=days, k=aggregates.K, items=items, hidden=hidden, note=aggregates.NOTE)


# --- public warnings ------------------------------------------------------------------------------------


def _public_text(text: str) -> str:
    return redact_text(text.strip())


def _warning_out(row: models.PublicWarning) -> WarningOut:
    return WarningOut(id=row.id, title=row.title, body_en=row.body_en, body_ur=row.body_ur, district=row.district, cluster_id=row.cluster_id,
                      status=row.status, published_at=paging.iso(row.published_at))  # fmt: skip


def publish_warning(db: Session, principal: Principal, body: WarningIn, *, idempotency_key: str | None) -> WarningOut:
    district = normalise_district(body.district) if body.district else None
    if body.district and district is None:
        raise Unprocessable("That is not a district we know.", code="unknown_district")
    if body.cluster_id is not None and db.get(models.ScamCluster, body.cluster_id) is None:
        raise NotFound("No such campaign.")
    title, body_en = _public_text(body.title)[:200], _public_text(body.body_en)
    body_ur = _public_text(body.body_ur) if body.body_ur else None
    now = datetime.now(UTC)
    if idempotency_key:  # the same warning sent twice by the same person within a day is one warning
        existing = db.scalar(select(models.PublicWarning).where(
            models.PublicWarning.tenant_id == principal.tenant_id, models.PublicWarning.published_by == principal.user_id,
            models.PublicWarning.title == title, models.PublicWarning.body_en == body_en, models.PublicWarning.created_at >= now - timedelta(days=1),
        ).limit(1))  # fmt: skip
        if existing is not None:
            return _warning_out(existing)
    row = models.PublicWarning(
        id=uuid.uuid4(), tenant_id=principal.tenant_id, title=title, body_en=body_en, body_ur=body_ur, district=district,
        cluster_id=body.cluster_id, status="published", published_by=principal.user_id, published_at=now, created_at=now,
    )  # fmt: skip
    db.add(row)
    db.flush()
    audit.write(db, tenant_id=principal.tenant_id, action="scam.warning_published", actor_id=principal.user_id, actor_role=principal.role,
                object_type="public_warning", object_id=row.id,
                details={"district": district, "cluster_id": str(body.cluster_id) if body.cluster_id else None})  # fmt: skip
    return _warning_out(row)


def withdraw_warning(db: Session, principal: Principal, warning_id: uuid.UUID) -> WarningOut:
    row = db.scalar(select(models.PublicWarning).where(models.PublicWarning.id == warning_id).with_for_update())
    if row is None:
        raise NotFound("No such warning.")
    if row.status != "withdrawn":
        row.status = "withdrawn"
        audit.write(db, tenant_id=principal.tenant_id, action="scam.warning_withdrawn", actor_id=principal.user_id, actor_role=principal.role,
                    object_type="public_warning", object_id=row.id)  # fmt: skip
        db.flush()
    return _warning_out(row)


def list_warnings(db: Session, principal: Principal, *, district: str | None, limit: int, cursor: str | None) -> WarningList:
    query = select(models.PublicWarning).where(models.PublicWarning.tenant_id == principal.tenant_id, models.PublicWarning.status == "published")
    if district:
        known = normalise_district(district)
        query = query.where(or_(models.PublicWarning.district.is_(None), models.PublicWarning.district == known))
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        after = tuple_(paging.as_datetime(created), paging.as_uuid(row_id))
        query = query.where(tuple_(models.PublicWarning.created_at, models.PublicWarning.id) < after)
    rows = list(db.scalars(query.order_by(models.PublicWarning.created_at.desc(), models.PublicWarning.id.desc()).limit(limit + 1)).all())
    next_cursor = paging.encode(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return WarningList(items=[_warning_out(r) for r in rows[:limit]], next_cursor=next_cursor)
