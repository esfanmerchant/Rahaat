"""Demo data for the Scam Map: a few hundred synthetic reports over the last 14 days. Safe to run twice.

Each demo department gets five campaigns (one storyline each, bursting in two or three districts over a few
days) and scattered single reports, so some map cells pass the k-anonymity threshold and some are hidden.
Every message comes from the synthetic corpus generator and is classified by the real model. Reports carry
`classification.source = "seed"`; a department that already has them is skipped.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.logging import get_logger
from app.db import models
from app.demo_accounts import DEMO_TENANTS
from app.modules.scam import corpus, runtime
from app.modules.scam.aggregates import PKT
from app.modules.scam.districts import BY_REGION
from app.modules.scam.engine import CodeCheck
from app.modules.scam.service import store_report

ORDER = 150
SEED = 20261122
DAYS = 14
log = get_logger("rahat.scam.seed")

# (family, {district: weight}, first day ago, number of days, reports per day low, high)
CAMPAIGNS = {
    "PK-SD": [
        ("relief.roman.selected_fee", {"Karachi East": 0.5, "Korangi": 0.3, "Malir": 0.2}, 12, 7, 8, 14),
        ("relief.ur.pin_release", {"Hyderabad": 0.65, "Mirpurkhas": 0.35}, 10, 6, 6, 11),
        ("phish.en.relief_form", {"Karachi Central": 0.5, "Karachi East": 0.5}, 7, 6, 5, 10),
        ("imp.roman.rahat_office", {"Sukkur": 0.6, "Larkana": 0.4}, 5, 5, 5, 9),
        ("adv.roman.inaam", {"Karachi East": 1.0}, 3, 4, 3, 7),
    ],
    "PK-PB": [
        ("relief.roman.registration", {"Lahore": 0.6, "Kasur": 0.4}, 12, 7, 8, 13),
        ("phish.roman.check_name", {"Faisalabad": 0.6, "Lahore": 0.4}, 9, 6, 6, 11),
        ("relief.en.selected_fee", {"Multan": 0.7, "Khanewal": 0.3}, 7, 5, 5, 10),
        ("imp.ur.relief_officer", {"Rawalpindi": 0.6, "Attock": 0.4}, 5, 5, 4, 9),
        ("adv.ur.lucky_draw", {"Gujranwala": 1.0}, 3, 4, 3, 7),
    ],
}
BACKGROUND_FAMILIES = ("relief.en.pin_release", "phish.en.kyc_update", "adv.en.loan", "imp.en.family_new_number", "ben.en.bank_otp",
                       "ben.roman.family_money", "ben.ur.family", "phish.ur.verify_card", "relief.ur.call_officer", "ben.en.shop_offer")  # fmt: skip
BACKGROUND_REPORTS = 45
CHANNELS = (("text", 0.6), ("sms_forward", 0.3), ("screenshot", 0.05), ("voice", 0.05))


def _never_issued(_code: str) -> CodeCheck:
    return CodeCheck(genuine=False)  # the seed has no outbox: no code in a seeded message is ours


def _pick(rng: random.Random, weights: dict[str, float] | tuple[tuple[str, float], ...]) -> str:
    items = list(weights.items()) if isinstance(weights, dict) else list(weights)
    r, total = rng.random(), 0.0
    for value, share in items:
        total += share
        if r < total:
            return value
    return items[-1][0]


def _when(rng: random.Random, days_ago: int, now: datetime) -> datetime:
    day = now.astimezone(PKT).date() - timedelta(days=days_ago)
    moment = datetime.combine(day, time(rng.randint(8, 21), rng.randint(0, 59), rng.randint(0, 59)), tzinfo=PKT).astimezone(UTC)
    return min(moment, now - timedelta(minutes=rng.randint(1, 120)))


def _message(rng: random.Random, slots: corpus.Slots, family: corpus.Family) -> tuple[str, str | None]:
    text = corpus.vary(rng, slots.fill(rng.choice(family.phrasings)), family)
    return text, corpus.pick_sender(rng, slots, family.senders)


def seed_tenant(db: Session, tenant: models.Tenant, *, now: datetime | None = None) -> int:
    """Add the demo reports to one department, unless it already has them. Returns how many were added."""
    already = db.scalar(select(models.ScamReport.id).where(models.ScamReport.tenant_id == tenant.id,
                                                          models.ScamReport.classification["source"].astext == "seed").limit(1))  # fmt: skip
    if already is not None:
        return 0
    now = now or datetime.now(UTC)
    rng = random.Random(f"{SEED}:{tenant.slug}")
    slots = corpus.Slots(rng)
    families = {f.name: f for f in corpus.FAMILIES}
    region = tenant.region if tenant.region in CAMPAIGNS else "PK-SD"
    plan: list[tuple[datetime, str, str | None, str]] = []
    for name, districts, first_ago, length, low, high in CAMPAIGNS[region]:
        for offset in range(length):
            days_ago = first_ago - offset
            if days_ago < 0:
                break
            for _ in range(rng.randint(low, high)):
                text, sender = _message(rng, slots, families[name])
                plan.append((_when(rng, days_ago, now), text, sender, _pick(rng, districts)))
    region_districts = BY_REGION.get(region, BY_REGION["PK-SD"])[:10]
    for _ in range(BACKGROUND_REPORTS):
        text, sender = _message(rng, slots, families[rng.choice(BACKGROUND_FAMILIES)])
        plan.append((_when(rng, rng.randrange(DAYS), now), text, sender, rng.choice(region_districts)))
    official = str((tenant.config or {}).get("official_sender") or "RAHAT")
    added = 0
    for when, text, sender, district in sorted(plan, key=lambda item: item[0]):
        result = runtime.classify(text, sender, official_sender=official, verify=_never_issued)
        store_report(db, tenant_id=tenant.id, text=text, channel=_pick(rng, CHANNELS), district=district, result=result,
                     reporter_user_id=None, reporter_person_id=None, created_at=when, source="seed")  # fmt: skip
        added += 1
    biggest = db.scalar(select(models.ScamCluster).where(models.ScamCluster.tenant_id == tenant.id)
                        .order_by(models.ScamCluster.size.desc(), models.ScamCluster.id).limit(1))  # fmt: skip
    if biggest is not None:
        admin = db.scalar(select(models.Membership.user_id).where(models.Membership.tenant_id == tenant.id, models.Membership.role == "admin")
                          .order_by(models.Membership.created_at).limit(1))  # fmt: skip
        db.add(models.PublicWarning(
            tenant_id=tenant.id, title="Fake Rahat fee messages", cluster_id=biggest.id, district=None, status="published",
            body_en="Rahat never asks for a fee, a PIN or a code. A message that asks you to pay to receive relief money is fake. "
                    "Do not reply and do not send money.",
            body_ur="راحت کبھی فیس، پن یا کوڈ نہیں مانگتا۔ جو پیغام امدادی رقم کے بدلے پیسے مانگے وہ جعلی ہے۔ جواب نہ دیں اور پیسے نہ بھیجیں۔",
            published_by=admin, published_at=now,
        ))  # fmt: skip
    db.flush()
    campaigns = len(db.scalars(select(models.ScamCluster.id).where(models.ScamCluster.tenant_id == tenant.id)).all())
    audit.write(db, tenant_id=tenant.id, action="scam.seeded", actor_type="system", object_type="tenant", object_id=tenant.id,
                details={"reports": added, "campaigns": campaigns, "days": DAYS, "source": "seed"})  # fmt: skip
    return added


def seed(db: Session) -> None:
    for spec in DEMO_TENANTS:
        tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == spec["slug"]))
        if tenant is None:
            continue
        try:
            added = seed_tenant(db, tenant)
        except runtime.ModelUnavailable:
            log.warning("scam demo reports skipped: the scam model is unavailable")
            return
        if added:
            log.info("seeded %d scam reports for %s", added, tenant.slug)
