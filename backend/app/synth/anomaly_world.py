"""A deterministic synthetic month of applications with injected anomalies, for measuring the anomaly detectors.

    world = build_anomaly_world(seed=20261201)
    world.records        every application as an `AppRecord` (fingerprinted payout accounts and IDs, as the service gives them)
    world.truth          the injected patterns, each with the application ids behind it, by detector
    world.hard_negatives benign look-alikes that a detector may wrongly flag (listed, so the false alarms can be explained)

Normal traffic: 12 districts with their own daily rate (weekends quieter), one person per application,
households of one to five people, a wallet each, helpers who register families over weeks. Injected: rings
(one wallet, several households), district spikes, helper bursts, one ID on two people or tried many times.
Hard negatives: relatives sharing a wallet, a shop wallet used by three unrelated customers, a helper's busy
hour, a person who applied twice. Nothing here is a real person; every identifier is a fingerprint of an
invented string.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from app.modules.anomaly.detectors import AppRecord
from app.synth import names

SEED: Final = 20261201
DAYS: Final = 30
START: Final = datetime(2026, 10, 20, tzinfo=UTC)
GENERATOR_VERSION: Final = "anomaly-world-1"


@dataclass(frozen=True, slots=True)
class Truth:
    detector: str
    kind: str
    app_ids: frozenset[str]


@dataclass(slots=True)
class AnomalyWorld:
    seed: int
    records: list[AppRecord]
    truth: list[Truth] = field(default_factory=list)
    hard_negatives: list[Truth] = field(default_factory=list)

    @property
    def today(self) -> datetime:
        return START + timedelta(days=DAYS - 1)


def fp(prefix: str, n: int | str) -> str:
    return hashlib.sha256(f"{prefix}:{n}".encode()).hexdigest()


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


class _Builder:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.records: list[AppRecord] = []
        self.n = 0
        self.households = 0

    def add(
        self,
        at: datetime,
        *,
        district: str,
        payout: str | None = None,
        national_id: str | None = None,
        helper: str | None = None,
        household: str | None = None,
        person: str | None = None,
        status: str = "submitted",
    ) -> AppRecord:
        self.n += 1
        person = person or f"p{self.n}"
        record = AppRecord(
            app_id=f"a{self.n:05d}",
            person_id=person,
            at=at,
            district=district,
            payout=payout or fp("acct", person),
            national_id=national_id or fp("nid", person),
            helper_id=helper,
            household=household or f"h-{person}",
            status=status,
        )
        self.records.append(record)
        return record

    def moment(self, day: int, *, hour_from: int = 8, hour_to: int = 20) -> datetime:
        seconds = self.rng.randrange(hour_from * 3600, hour_to * 3600)
        return START + timedelta(days=day, seconds=seconds)


def build_anomaly_world(seed: int = SEED) -> AnomalyWorld:
    b = _Builder(seed)
    rng = b.rng
    districts = list(names.DISTRICTS[:12])
    rates = {d: rng.uniform(2.0, 5.5) for d in districts}
    world = AnomalyWorld(seed=seed, records=b.records)

    # Normal traffic. A third of the applications come through one of eight helpers, spread across the month.
    helpers = [f"helper-{i:02d}" for i in range(8)]
    for day in range(DAYS):
        weekday = (START + timedelta(days=day)).weekday()
        factor = 0.55 if weekday >= 5 else 1.0
        for d in districts:
            for _ in range(_poisson(rng, rates[d] * factor)):
                helper = rng.choice(helpers) if rng.random() < 0.33 else None
                b.add(b.moment(day), district=d, helper=helper)

    # Hard negative 1: relatives in one household share one wallet (three or four people).
    for i in range(6):
        d, day = rng.choice(districts), rng.randrange(DAYS)
        hh, wallet = f"hh-shared-{i}", fp("acct", f"family-{i}")
        added = [b.add(b.moment(day), district=d, payout=wallet, household=hh) for _ in range(rng.choice((3, 4)))]
        world.hard_negatives.append(Truth("shared_payout", "relatives_share_wallet", frozenset(r.app_id for r in added)))
    # Hard negative 2: a shop wallet used by three unrelated customers (the detector cannot tell this from a ring; it must go to a person).
    for i in range(2):
        d, day = rng.choice(districts), rng.randrange(DAYS)
        wallet = fp("acct", f"shop-{i}")
        added = [b.add(b.moment(day + rng.randrange(0, 3) if day < DAYS - 3 else day), district=d, payout=wallet) for _ in range(3)]
        world.hard_negatives.append(Truth("shared_payout", "shop_wallet", frozenset(r.app_id for r in added)))
    # Hard negative 3: neighbours, two people on one wallet (below the three-person rule).
    for i in range(5):
        d, day = rng.choice(districts), rng.randrange(DAYS)
        wallet = fp("acct", f"neighbours-{i}")
        added = [b.add(b.moment(day), district=d, payout=wallet) for _ in range(2)]
        world.hard_negatives.append(Truth("shared_payout", "two_people_one_wallet", frozenset(r.app_id for r in added)))
    # Hard negative 4: a helper's busy hour, six families (a camp day), below the burst threshold.
    for i in range(4):
        d, day = rng.choice(districts), rng.randrange(DAYS)
        helper, start = helpers[i], b.moment(day, hour_from=9, hour_to=12)
        added = [b.add(start + timedelta(minutes=rng.randrange(0, 50)), district=d, helper=helper) for _ in range(6)]
        world.hard_negatives.append(Truth("helper_burst", "busy_hour", frozenset(r.app_id for r in added)))
    # Hard negative 5: one person who applied twice (a correction), same ID on the same person.
    for i in range(6):
        d, day = rng.choice(districts), rng.randrange(DAYS - 2)
        nid, person = fp("nid", f"retry-{i}"), f"retry-person-{i}"
        added = [
            b.add(b.moment(day), district=d, national_id=nid, person=person, status="withdrawn"),
            b.add(b.moment(day + 1), district=d, national_id=nid, person=person),
        ]
        world.hard_negatives.append(Truth("repeated_identity", "applied_twice", frozenset(r.app_id for r in added)))

    # Injected 1: rings. One wallet behind 3 to 8 households, over a few days in one or two districts.
    for i in range(6):
        size = rng.choice((3, 3, 4, 5, 6, 8))
        wallet = fp("acct", f"ring-{i}")
        base_day = rng.randrange(DAYS - 4)
        dists = rng.sample(districts, 2)
        added = [b.add(b.moment(base_day + rng.randrange(0, 4)), district=rng.choice(dists), payout=wallet) for _ in range(size)]
        world.truth.append(Truth("shared_payout", "ring", frozenset(r.app_id for r in added)))

    # Injected 2: spikes. A district's count jumps well above its own baseline on a day in the last three weeks.
    spike_days = rng.sample(range(9, DAYS), 5)
    for day, d in zip(spike_days, rng.sample(districts, 5), strict=True):
        extra = int(rates[d] * 4) + rng.randrange(10, 16)
        added = [b.add(b.moment(day), district=d) for _ in range(extra)]
        world.truth.append(Truth("application_spike", "spike", frozenset(r.app_id for r in added)))

    # Injected 3: helper bursts. A helper registers 12 to 25 families in under an hour.
    for _ in range(4):
        helper, d, day = f"helper-{rng.randrange(8):02d}", rng.choice(districts), rng.randrange(DAYS)
        start = b.moment(day, hour_from=8, hour_to=18)
        added = [b.add(start + timedelta(minutes=rng.randrange(0, 45)), district=d, helper=helper) for _ in range(rng.randrange(12, 26))]
        world.truth.append(Truth("helper_burst", "burst", frozenset(r.app_id for r in added)))

    # Injected 4: one mock ID on two or three people, and one ID tried four times by one person.
    for i in range(4):
        nid, d, day = fp("nid", f"stolen-{i}"), rng.choice(districts), rng.randrange(DAYS - 3)
        added = [b.add(b.moment(day + k), district=d, national_id=nid) for k in range(rng.choice((2, 2, 3)))]
        world.truth.append(Truth("repeated_identity", "id_on_several_people", frozenset(r.app_id for r in added)))
    for i in range(3):
        nid, d, day, person = fp("nid", f"hammer-{i}"), rng.choice(districts), rng.randrange(DAYS - 3), f"hammer-person-{i}"
        added = [b.add(b.moment(day + k), district=d, national_id=nid, person=person, status="rejected") for k in range(4)]
        world.truth.append(Truth("repeated_identity", "id_many_attempts", frozenset(r.app_id for r in added)))

    world.records.sort(key=lambda r: (r.at, r.app_id))
    return world
