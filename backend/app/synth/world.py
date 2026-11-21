"""A deterministic synthetic world: people with a known truth and a realistic, imperfect observation process.

    world = build_world(seed=SEED)        # same seed, same world, on every machine
    world.persons     1,200+ invented people in households, with messy name variants
    world.registry    what the mock registry knows (often incomplete, sometimes old)
    world.cases       labelled applications: DecisionInput + truth (eligible, genuine) + tags

What the engine sees is never the truth. Registry incomes are missing or old, declared values disagree,
cards are blurry, forged or borrowed, names are spelled five ways, services go down. Each case belongs to a
family (the identity it uses), so train and test can be split by family: an impostor using someone's ID
lands in the same split as that person's own applications.

Everything is invented: mock IDs are 00000-NNNNNNN-C and mock phones 0999-NNNNNNN.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any, Final

from rapidfuzz import fuzz

from app.contracts.application import ApplicationFormV1, FieldValue
from app.contracts.common import INCOME_BAND_BOUNDS, IncomeBand
from app.contracts.decision import TypedDecision
from app.contracts.documents import Authenticity, DocumentCheck, DocumentSignal, OcrResult, QrResult
from app.contracts.engine import AnomalyEvidence, DecisionInput, DuplicateEvidence, IdentityCheck, RegistryRecord
from app.core.mockdata import make_mock_id, make_mock_phone
from app.synth import names

SEED: Final = 20261121
BASE_TIME: Final = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
CAP_CHOICES: Final = ((20_000, 1), (25_000, 2), (30_000, 4), (35_000, 2), (40_000, 1))
FRAUD_KINDS: Final = ("forged_card", "impersonation", "double_dip", "ring")
GENERATOR_VERSION: Final = "synth-1"


@dataclass(frozen=True, slots=True)
class SynthPerson:
    ref: str
    household_ref: str
    full_name: str
    full_name_ur: str
    name_variants: tuple[str, ...]
    gender: str
    dob: str
    district: str
    national_id: str
    phone: str
    household_size: int
    true_income_pkr: int
    receives_other_aid: bool
    is_widow: bool
    has_disability: bool
    misreporter: bool
    in_registry: bool


@dataclass(frozen=True, slots=True)
class Truth:
    eligible: bool
    genuine: bool
    fraud: str | None = None

    @property
    def ok(self) -> bool:
        return self.eligible and self.genuine


@dataclass(frozen=True, slots=True)
class SynthCase:
    case_id: str
    family_id: str
    person_ref: str
    truth: Truth
    income_cap: int
    tags: tuple[str, ...]
    inp: DecisionInput


@dataclass(frozen=True, slots=True)
class World:
    seed: int
    persons: tuple[SynthPerson, ...]
    registry: dict[str, RegistryRecord]
    cases: tuple[SynthCase, ...]


def _band_of(income: int) -> IncomeBand:
    for band, (low, high) in INCOME_BAND_BOUNDS.items():
        if income >= low and (high is None or income < high):
            return band  # type: ignore[return-value]
    return "over_50k"


_BANDS: Final[tuple[IncomeBand, ...]] = ("under_15k", "15k_30k", "30k_50k", "over_50k")


def _shift_band(band: IncomeBand, step: int) -> IncomeBand:
    return _BANDS[max(0, min(len(_BANDS) - 1, _BANDS.index(band) + step))]


def _weighted(rng: random.Random, pairs: tuple[tuple[Any, float], ...]) -> Any:
    total = sum(weight for _, weight in pairs)
    roll = rng.random() * total
    for value, weight in pairs:
        roll -= weight
        if roll <= 0:
            return value
    return pairs[-1][0]


def _norm(text: str) -> str:
    return " ".join(text.lower().replace(".", " ").split())


def name_similarity(a: str, b: str) -> float:
    return fuzz.token_set_ratio(_norm(a), _norm(b)) / 100.0


# --- people and households -----------------------------------------------------------------------------


def _people(rng: random.Random, households: int) -> list[SynthPerson]:
    persons: list[SynthPerson] = []
    serial = 2_000_000
    for h in range(households):
        district = rng.choice(names.DISTRICTS)
        family = rng.choice(sorted(names.FAMILY))
        size = max(1, min(11, int(rng.gauss(5.2, 2.0))))
        income = int(max(4_000, min(160_000, math.exp(rng.gauss(math.log(24_000), 0.5)))) // 100 * 100)
        other_aid = rng.random() < 0.13
        adults = _weighted(rng, ((1, 0.45), (2, 0.35), (3, 0.15), (4, 0.05)))
        for a in range(adults):
            serial += 1
            gender = "female" if (a == 0 and rng.random() < 0.6) or (a > 0 and rng.random() < 0.5) else "male"
            age = int(rng.uniform(19, 78))
            born = date(2026 - age, rng.randint(1, 12), rng.randint(1, 28))
            full_name, full_name_ur = names.make_name(rng, gender, family)
            widow = gender == "female" and rng.random() < (0.35 if age > 55 else 0.1)
            persons.append(SynthPerson(
                ref=f"P{len(persons) + 1:05d}", household_ref=f"H{h + 1:04d}", full_name=full_name, full_name_ur=full_name_ur,
                name_variants=names.name_variants(rng, full_name), gender=gender, dob=born.isoformat(), district=district,
                national_id=make_mock_id(serial), phone=make_mock_phone(serial), household_size=size, true_income_pkr=income,
                receives_other_aid=other_aid, is_widow=widow, has_disability=rng.random() < 0.08,
                misreporter=rng.random() < 0.12, in_registry=rng.random() < 0.94,
            ))  # fmt: skip
    return persons


def _registry_record(rng: random.Random, p: SynthPerson) -> RegistryRecord:
    income: int | None = None
    as_of: str | None = None
    if rng.random() < 0.75:
        stale = rng.random() < 0.3
        age_days = rng.randint(400, 1600) if stale else rng.randint(10, 330)
        noise = rng.gauss(-0.12, 0.3) if stale else rng.gauss(0.0, 0.04)
        income = int(p.true_income_pkr * math.exp(noise)) // 100 * 100
        as_of = (BASE_TIME.date() - timedelta(days=age_days)).isoformat()
    aid = p.receives_other_aid if rng.random() < 0.995 else not p.receives_other_aid
    return RegistryRecord(
        national_id=p.national_id, full_name=p.full_name, dob=p.dob, gender=p.gender, district=p.district,
        household_size=p.household_size if rng.random() < 0.6 else None, verified_income_pkr=income, income_as_of=as_of,
        receives_other_aid=aid if rng.random() < 0.96 else None,
        is_widow=p.is_widow if rng.random() < 0.6 else None, has_disability=p.has_disability if rng.random() < 0.6 else None,
    )  # fmt: skip


# --- documents -----------------------------------------------------------------------------------------


def _authenticity(choice: Authenticity | None, p_genuine: float, route: str, reasons: list[str]) -> TypedDecision[Authenticity]:
    p = round(p_genuine, 3)
    return TypedDecision[Authenticity](
        choice=choice, probabilities={"genuine": p, "suspect": round(1 - p, 3)},
        confidence=round(max(p, 1 - p), 3), route=route, reasons=reasons,
        model_version="synth-docs-1", abstained=choice is None,
    )  # fmt: skip


def _card(rng: random.Random, doc_id: str, holder: SynthPerson, *, kind: str = "genuine", copied_from: SynthPerson | None = None) -> DocumentCheck:
    """A Rahat card photo as the document checker would report it.

    kind: genuine | tampered_qr (signature fails) | no_qr (QR removed, edited print) | copied_qr (a real
    signed QR of someone else glued onto a card for the holder).
    """
    quality = _weighted(rng, (("ok", 0.76), ("glare", 0.09), ("blurry", 0.09), ("cropped", 0.04), ("not_a_card", 0.02)))
    p_found = {"ok": 0.97, "glare": 0.85, "blurry": 0.35, "cropped": 0.3, "not_a_card": 0.0}[quality]
    owner = copied_from or holder
    payload = {"national_id": owner.national_id, "name": owner.full_name, "dob": owner.dob}
    ocr_conf = {"ok": 0.9, "glare": 0.7, "blurry": 0.45, "cropped": 0.55, "not_a_card": 0.1}[quality]
    ocr = OcrResult(fields={"name": names.messy_variant(rng, holder.full_name, mess=0.3).upper()} if quality != "not_a_card" else {},
                    mean_confidence=round(max(0.0, min(1.0, rng.gauss(ocr_conf, 0.08))), 3))  # fmt: skip
    signals: list[DocumentSignal] = []
    retake = None if quality in ("ok", "glare") else f"retake_{quality}"
    if kind == "no_qr":
        found = False
    else:
        found = rng.random() < max(p_found, 0.5 if kind != "genuine" else 0.0) if quality != "not_a_card" else False
    if not found:
        qr = QrResult(found=False)
    elif kind == "tampered_qr":
        qr = QrResult(found=True, signature_valid=False, issuer_key_id="mock-issuer-1", payload=payload)
        signals.append(DocumentSignal(code="qr_signature_invalid", weight=3.0, staff_detail="QR signature does not verify"))
    else:
        qr = QrResult(found=True, signature_valid=True, issuer_key_id="mock-issuer-1", payload=payload)
        signals.append(DocumentSignal(code="qr_signature_valid", weight=-2.0, staff_detail="Signed by mock-issuer-1"))
    if kind == "copied_qr" and found:
        signals.append(DocumentSignal(code="ocr_qr_mismatch", weight=2.0, staff_detail="Printed name differs from the QR"))

    if qr.signature_valid is False:
        auth = _authenticity("suspect", rng.uniform(0.02, 0.15), "human", ["qr_signature_invalid"])
    elif kind == "copied_qr" and found:
        p = rng.uniform(0.15, 0.7)
        auth = _authenticity("suspect" if p < 0.5 else "genuine", p, "human" if p < 0.5 else "auto", ["ocr_qr_mismatch"])
    elif kind == "no_qr":
        p = rng.uniform(0.1, 0.8)
        if quality in ("blurry", "cropped", "not_a_card"):
            auth = _authenticity(None, 0.5, "ask_more", ["image_quality"])
        elif p < 0.45:
            signals.append(DocumentSignal(code="ela_anomaly", weight=1.5, staff_detail="Edited area around the photo"))
            auth = _authenticity("suspect", p, "human", ["ela_anomaly"])
        else:
            auth = _authenticity(None, p, "human", ["no_qr"])
    elif qr.signature_valid:
        auth = _authenticity("genuine", rng.uniform(0.9, 0.995), "auto", ["qr_signature_valid"])
    elif quality in ("blurry", "cropped", "not_a_card"):
        auth = _authenticity(None, 0.5, "ask_more", ["image_quality"])
    else:
        p = rng.uniform(0.6, 0.92)
        auth = _authenticity("genuine" if p >= 0.8 else None, p, "auto" if p >= 0.8 else "human", ["no_qr"])
    return DocumentCheck(document_id=doc_id, kind="rahat_id", quality=quality, retake_hint=retake, qr=qr, ocr=ocr,
                         authenticity=auth, signals=signals, model_version="synth-docs-1")  # fmt: skip


def _income_proof(doc_id: str, income: int) -> DocumentCheck:
    return DocumentCheck(
        document_id=doc_id, kind="income_proof", quality="ok",
        qr=QrResult(found=True, signature_valid=True, issuer_key_id="mock-employer-1", payload={"monthly_income_pkr": income}),
        ocr=OcrResult(fields={"income": str(income)}, mean_confidence=0.85),
        authenticity=_authenticity("genuine", 0.95, "auto", ["qr_signature_valid"]), model_version="synth-docs-1",
    )  # fmt: skip


# --- one application ------------------------------------------------------------------------------------


def _field(value: Any, rng: random.Random, provenance: str = "tapped", low: float = 0.75) -> FieldValue[Any]:
    if value is None:
        return FieldValue()
    return FieldValue(value=value, confidence=round(rng.uniform(low, 1.0), 2), provenance=provenance)


def _application(rng: random.Random, index: int, *, applicant: SynthPerson, claimed: SynthPerson, record: RegistryRecord | None,
                 fraud: str | None, cap: int, ring_score: float | None = None) -> SynthCase:  # fmt: skip
    """`claimed` is whose identity the form uses; `applicant` is who is really applying."""
    tags: list[str] = []
    case_id = f"C{index + 1:05d}"
    honest = fraud is None
    # The form: a messy version of the claimed name, typed or spoken.
    form_name = names.messy_variant(rng, claimed.full_name, mess=0.55 if honest else 0.4)
    national_id = claimed.national_id
    if honest and rng.random() < 0.03:
        national_id = make_mock_id(rng.randint(1_000_000, 9_999_999))
        tags.append("id_typo")
    true_band = _band_of(claimed.true_income_pkr)
    if rng.random() < 0.04:
        band: IncomeBand | None = None
    elif claimed.misreporter or not honest:
        band = _shift_band(true_band, -1) if rng.random() < 0.8 else true_band
        tags.append("income_misreport" if band != true_band else "declared_band")
    else:
        band = true_band if rng.random() < 0.85 else _shift_band(true_band, rng.choice((-1, 1)))
    declared_aid = claimed.receives_other_aid if honest and not claimed.misreporter and rng.random() < 0.95 else False
    declared_size = max(1, claimed.household_size + (rng.choice((-1, 0, 0, 0, 1, 2)) if honest else rng.choice((1, 2, 3))))
    form = ApplicationFormV1(
        full_name=_field(form_name, rng, "spoken", 0.6), national_id=_field(national_id, rng, "typed", 0.85),
        dob=_field(claimed.dob, rng, "typed", 0.8), gender=_field(claimed.gender, rng), district=_field(claimed.district, rng),
        phone=_field(applicant.phone if honest else make_mock_phone(rng.randint(1_000_000, 9_999_999)), rng, "typed", 0.9),
        household_size=_field(declared_size if rng.random() > 0.05 else None, rng, "spoken", 0.55),
        income_band=_field(band, rng, "tapped", 0.7),
        is_widow=_field(claimed.is_widow if rng.random() > 0.05 else None, rng),
        has_disability=_field(claimed.has_disability if rng.random() > 0.05 else None, rng),
        receives_other_aid=_field(declared_aid if rng.random() > 0.08 else None, rng),
        payout_account=_field(f"MOCK-WALLET-{(applicant.ref if fraud != 'ring' else 'RING')}-{rng.randint(10, 99)}", rng, "typed", 0.9),
        language=rng.choice(("ur", "ur", "ur", "en")),
    )  # fmt: skip

    # Documents.
    documents: list[DocumentCheck] = []
    if fraud == "forged_card":
        style = _weighted(rng, (("tampered_qr", 0.5), ("no_qr", 0.3), ("copied_qr", 0.2)))
        donor = applicant if style == "copied_qr" else None
        documents.append(_card(rng, f"{case_id}-D1", claimed, kind=style, copied_from=donor))
        tags.append(f"forged_{style}")
    elif rng.random() < 0.9 or not honest:
        documents.append(_card(rng, f"{case_id}-D1", claimed))
    else:
        tags.append("no_card")
    if documents and documents[0].quality not in ("ok", "glare"):
        tags.append(f"card_{documents[0].quality}")
    if rng.random() < 0.07:
        documents.append(_income_proof(f"{case_id}-D2", claimed.true_income_pkr if honest else int(claimed.true_income_pkr * 0.6)))
        tags.append("income_proof")

    # Identity service: does this ID, name and date of birth belong to one record?
    if rng.random() < 0.03:
        identity = IdentityCheck(status="unavailable")
        tags.append("identity_down")
    elif national_id != claimed.national_id or not claimed.in_registry:
        identity = IdentityCheck(status="not_found")
    else:
        score = name_similarity(form_name, claimed.full_name)
        if fraud in ("forged_card", "impersonation"):
            score = min(score, rng.uniform(0.45, 1.0))
        status = "match" if score >= 0.85 else "partial" if score >= 0.6 else "mismatch"
        identity = IdentityCheck(status=status, name_score=round(score, 3))
        if status != "match":
            tags.append(f"identity_{status}")

    # Registry.
    registry_status = "unavailable" if rng.random() < 0.05 else ("found" if record is not None else "not_found")
    if registry_status == "unavailable":
        tags.append("registry_down")
    elif registry_status == "not_found":
        tags.append("not_in_registry")
    elif record is not None:
        if record.verified_income_pkr is None:
            tags.append("registry_income_missing")
        elif record.income_as_of and (BASE_TIME.date() - date.fromisoformat(record.income_as_of)).days > 365:
            tags.append("registry_income_stale")

    # Dedupe and anomaly evidence.
    duplicate = None
    if rng.random() < 0.65 or fraud in ("double_dip", "impersonation"):
        if fraud == "double_dip":
            band_ = _weighted(rng, (("same", 0.5), ("possible", 0.4), ("distinct", 0.1)))
        elif fraud == "impersonation":
            band_ = _weighted(rng, (("possible", 0.45), ("distinct", 0.55)))
        else:
            band_ = "possible" if rng.random() < 0.05 else "distinct"
        score_ = {"same": rng.uniform(0.92, 0.99), "possible": rng.uniform(0.62, 0.88), "distinct": rng.uniform(0.05, 0.5)}[band_]
        duplicate = DuplicateEvidence(band=band_, score=round(score_, 3), other_person_ref=claimed.ref if band_ != "distinct" else None)
        if band_ != "distinct":
            tags.append(f"duplicate_{band_}")
    anomaly = None
    if rng.random() < 0.75 or fraud == "ring":
        if fraud == "ring":
            score_a = ring_score if ring_score is not None else rng.uniform(0.6, 0.98)
        elif fraud in ("impersonation", "double_dip"):
            score_a = rng.betavariate(5, 4)
        elif fraud == "forged_card":
            score_a = rng.betavariate(3, 4)
        else:
            score_a = rng.betavariate(2, 9)
        anomaly = AnomalyEvidence(score=round(score_a, 3), flagged=score_a >= 0.8,
                                  reasons=["shared_payout_account"] if fraud == "ring" else [])  # fmt: skip
        if anomaly.flagged:
            tags.append("anomaly_flagged")

    consent_ok = rng.random() > 0.01
    if not consent_ok:
        tags.append("consent_missing")
    if fraud:
        tags.append(fraud)
    if not tags:
        tags.append("clean")
    inp = DecisionInput(
        application_id=f"synth-{case_id}", program_slug="rahat", lang=form.language, form=form, documents=documents,
        identity=identity, registry_status=registry_status, registry=record if registry_status == "found" else None,
        duplicate=duplicate, anomaly=anomaly, consent_ok=consent_ok, queue_days=1.0,
        decided_at=(BASE_TIME + timedelta(minutes=7 * index)).isoformat(),
    )  # fmt: skip
    eligible = claimed.true_income_pkr <= cap and not claimed.receives_other_aid
    truth = Truth(eligible=eligible, genuine=fraud is None, fraud=fraud)
    return SynthCase(case_id=case_id, family_id=claimed.ref, person_ref=applicant.ref, truth=truth, income_cap=cap,
                     tags=tuple(dict.fromkeys(tags)), inp=inp)  # fmt: skip


def build_world(seed: int = SEED, households: int = 660) -> World:
    """The whole world from one seed. About 1,250 persons and 2,000+ labelled cases with the defaults."""
    rng = random.Random(seed)
    persons = _people(rng, households)
    registry = {p.national_id: _registry_record(rng, p) for p in persons if p.in_registry}
    caps = {p.ref: _weighted(rng, CAP_CHOICES) for p in persons}
    outsiders = [p for p in persons if rng.random() < 0.08]  # people who lend their face to someone else's ID
    cases: list[SynthCase] = []

    def add(applicant: SynthPerson, claimed: SynthPerson, fraud: str | None, ring_score: float | None = None) -> None:
        cases.append(_application(rng, len(cases), applicant=applicant, claimed=claimed, record=registry.get(claimed.national_id),
                                  fraud=fraud, cap=caps[claimed.ref], ring_score=ring_score))  # fmt: skip

    for person in persons:
        for _ in range(_weighted(rng, ((1, 0.62), (2, 0.25), (3, 0.08), (0, 0.05)))):
            add(person, person, None)
        roll = rng.random()
        if roll < 0.04 and outsiders:
            add(rng.choice(outsiders), person, "forged_card")
        elif roll < 0.075 and outsiders:
            add(rng.choice(outsiders), person, "impersonation")
        elif roll < 0.1:
            add(person, person, "double_dip")
    ring_members = [p for p in persons if p.in_registry and rng.random() < 0.035]
    for member in ring_members:
        add(member, member, "ring", ring_score=rng.uniform(0.55, 0.99) if rng.random() < 0.85 else rng.uniform(0.2, 0.5))
    return World(seed=seed, persons=tuple(persons), registry=registry, cases=tuple(cases))


@lru_cache(maxsize=4)
def default_world(seed: int = SEED) -> World:
    return build_world(seed)


def family_split(family_id: str, seed: int = SEED) -> str:
    """train | calibration | test, decided by a hash of the family so a split never leaks an identity."""
    import hashlib

    bucket = int(hashlib.sha256(f"{seed}:{family_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 60 else "calibration" if bucket < 80 else "test"
