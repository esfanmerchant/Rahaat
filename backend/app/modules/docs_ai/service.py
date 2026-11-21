"""`check_document`: quality gate, signed QR, OCR, and authenticity for an uploaded document (PLAN 6.4).

Pure function of the image bytes: no database, no network, no clock in the result. Order of work:

1. Decode within bounds (size, pixels, format). A malformed upload returns a safe result routed to a human.
2. Quality gate: find the card, then check crop, blur and glare. Poor quality asks for a retake with a reason
   code (`retake_hint`); it is never a rejection. Glare is accepted when the signed QR still verifies.
3. QR: decode with OpenCV, verify the Ed25519 signature against the mock issuer keys, return the payload.
4. OCR (Tesseract, when installed) of each printed value, compared with the signed payload.
5. Authenticity, from independent signals: signature, OCR and print checks against the payload, error level
   analysis localised over a printed value, and an image editor named in the metadata. `genuine` acts alone
   only when the signature is valid and no strong signal fires; `suspect` always goes to a human; without
   enough evidence (no QR on a readable card) the decision abstains and goes to a human.

How a caller reads the result: `retake_hint` set means ask the citizen for a new photo (`citizen_view`).
Otherwise the document is stored; `authenticity.route == "auto"` with `choice == "genuine"` means no person
needs to look at it. Signals and their `staff_detail` are for staff and auditors only.

The signal weights are set by hand and checked on the synthetic evaluation (`python -m app.modules.docs_ai.evaluate`).
They are not calibrated on real cards; there are none in this project.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.contracts.common import DocumentKind, DocumentQuality
from app.contracts.decision import TypedDecision
from app.contracts.documents import Authenticity, DocumentCheck, DocumentCitizenView, DocumentSignal, OcrResult, QrResult
from app.modules.docs_ai import layout as L

MODEL_VERSION = "docs-ai-1.0.0"

# Quality gate (calibrated on generated photos; see evaluate.py).
BLUR_MIN = 60.0  # variance of the Laplacian over the printed values, at the card's native scale (red channel)
BLUR_SOFT = 400.0  # below this an unreadable QR is treated as a focus problem
MIN_CARD_PX = 480.0  # a card narrower than this in the (downscaled) photo is too far away to read
GLARE_MIN = 0.02  # share of near-white pixels on the card outside the areas that are white by design
FIELD_GLARE_MAX = 0.15  # a value this covered by glare is not compared

# Authenticity: log-odds weights. p_suspect = sigmoid(PRIOR + sum of fired weights).
PRIOR = -1.5
STRONG = 3.5  # a strong signal alone outweighs a valid signature
GENUINE_AUTO_FLOOR = 0.95
WEIGHTS: dict[str, float] = {
    "qr_signature_valid": -2.0,
    "ocr_matches_qr": -1.0,
    "print_matches_qr": -0.5,
    "qr_signature_invalid": 4.0,
    "qr_issuer_unknown": 4.0,
    "qr_not_issuer_format": 4.0,
    "qr_payload_oversized": 4.0,
    "ocr_qr_mismatch": 4.0,
    "print_qr_mismatch": 4.0,
    "ela_anomaly": 3.6,
    "metadata_editor": 1.5,
    "layout_unverified": 1.0,
    "qr_missing": 0.0,
    "qr_unreadable": 0.0,
}

RETAKE_HINTS: dict[str, str] = {
    "blurry": "doc_retake_blurry",
    "glare": "doc_retake_glare",
    "cropped": "doc_retake_cropped",
    "not_a_card": "doc_retake_not_a_card",
}

FIELD_LABELS = {"full_name": "name", "national_id": "mock ID number", "dob": "date of birth", "gender": "gender", "district": "district"}


@dataclass
class _Evidence:
    signals: list[DocumentSignal] = field(default_factory=list)

    def add(self, code: str, detail: str) -> None:
        self.signals.append(DocumentSignal(code=code, weight=WEIGHTS[code], staff_detail=detail))

    @property
    def codes(self) -> list[str]:
        return [s.code for s in self.signals]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _abstain(route: str, reasons: list[str]) -> TypedDecision[Authenticity]:
    return TypedDecision[Authenticity](
        choice=None, probabilities={}, confidence=0.0, route=route,  # type: ignore[arg-type]
        reasons=reasons, model_version=MODEL_VERSION, abstained=True,
    )  # fmt: skip


def _result(
    document_id: str, kind: DocumentKind, quality: DocumentQuality, authenticity: TypedDecision[Authenticity], *,
    retake: bool = False, qr: QrResult | None = None, ocr: OcrResult | None = None, signals: list[DocumentSignal] | None = None,
) -> DocumentCheck:  # fmt: skip
    return DocumentCheck(
        document_id=document_id, kind=kind, quality=quality,
        retake_hint=RETAKE_HINTS[quality] if retake else None,
        qr=qr or QrResult(), ocr=ocr or OcrResult(available=_ocr_engine(None).available()),
        authenticity=authenticity, signals=signals or [], model_version=MODEL_VERSION,
    )  # fmt: skip


def _ocr_engine(engine: Any) -> Any:
    if engine is not None:
        return engine
    from app.modules.docs_ai.ocr import default_engine

    return default_engine()


# ------------------------------------------------------------------------------------------------ measurements


def card_width_px(matrix: np.ndarray) -> float:
    """How wide the card appears in the working image, in pixels."""
    pts = np.array([[0, 0, 1], [L.CARD_W, 0, 1], [L.CARD_W, L.CARD_H, 1], [0, L.CARD_H, 1]], dtype=np.float64).T
    p = matrix @ pts
    xy = (p[:2] / p[2]).T
    return float((np.linalg.norm(xy[1] - xy[0]) + np.linalg.norm(xy[2] - xy[3])) / 2)


def blur_score(rgb: np.ndarray, matrix: np.ndarray) -> float:
    """Variance of the Laplacian over the printed values, measured at the card's own scale in the photo.

    Red channel only, so the SPECIMEN watermark does not count as detail. Measuring at native scale (never
    upsampled) keeps the score about focus rather than about how far away the card was.
    """
    import cv2

    scale = min(1.0, card_width_px(matrix) / L.CARD_W)
    to_native = np.diag([scale, scale, 1.0]) @ np.linalg.inv(matrix)
    w, h = max(1, round(L.CARD_W * scale)), max(1, round(L.CARD_H * scale))
    native = cv2.warpPerspective(rgb[..., 0], to_native, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    y0, y1 = round(L.ROW_TOP * scale), round(L.value_box(len(L.FIELDS) - 1).y1 * scale)
    x0, x1 = round((L.FIELD_X - 10) * scale), round((L.FIELD_X + L.FIELD_MAX_W) * scale)
    region = native[y0:y1, x0:x1].astype(np.float32)
    return float(cv2.Laplacian(region, cv2.CV_32F).var()) if region.size else 0.0


def _glare_mask() -> np.ndarray:
    mask = np.ones((L.CARD_H, L.CARD_W), dtype=bool)
    for box in L.glare_exclusions():
        mask[box.y0 : box.y1, box.x0 : box.x1] = False
    edge = 12
    mask[:edge, :] = mask[-edge:, :] = False
    mask[:, :edge] = mask[:, -edge:] = False
    return mask


_GLARE_MASK = _glare_mask()


def glare_share(card: np.ndarray) -> float:
    return float((card.min(axis=2)[_GLARE_MASK] >= 250).mean())


def _field_glare(card: np.ndarray) -> dict[str, float]:
    sat = card.min(axis=2) >= 248
    out = {}
    for i, (name, _) in enumerate(L.FIELDS):
        vb = L.value_box(i)
        out[name] = float(sat[vb.y0 : vb.y1, vb.x0 : vb.x1].mean())
    return out


def _ocr_bands(card: np.ndarray) -> list[np.ndarray]:
    import cv2

    bands = []
    for i in range(len(L.FIELDS)):
        vb = L.value_box(i)
        crop = card[vb.y0 : vb.y1, vb.x0 : vb.x1, 0]
        bands.append(np.asarray(cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)))
    return bands


def _run_ocr(engine: Any, card: np.ndarray, signed: dict[str, str] | None, glare: dict[str, float]) -> tuple[OcrResult, dict[str, str]]:
    """OCR each printed value; compare with the signed payload when there is one."""
    from app.modules.docs_ai.ocr import compare_field, parse_field

    lines = engine.read_lines(_ocr_bands(card))
    fields: dict[str, str] = {}
    conf: dict[str, float] = {}
    raw: list[str] = []
    for (name, label), line in zip(L.FIELDS, lines, strict=True):
        if line is None:
            continue
        raw.append(f"{label}: {line.text[:80]}")
        value = parse_field(name, line.text)
        if value is not None:
            fields[name] = value[:80]
            conf[name] = round(max(0.0, min(1.0, line.confidence)), 3)
    mean = round(float(np.mean(list(conf.values()))), 3) if conf else 0.0
    result = OcrResult(available=True, fields=fields, field_confidence=conf, mean_confidence=mean, raw_text="\n".join(raw) or None)
    comparisons: dict[str, str] = {}
    if signed:
        for name, _ in L.FIELDS:
            if glare.get(name, 0.0) > FIELD_GLARE_MAX or conf.get(name, 0.0) < 0.6:
                comparisons[name] = "unclear"
            else:
                comparisons[name] = compare_field(name, fields.get(name), signed[name])
    return result, comparisons


# ------------------------------------------------------------------------------------------------ the check


def check_document(
    image_bytes: bytes,
    kind: DocumentKind,
    *,
    document_id: str,
    trusted_keys: dict[str, Ed25519PublicKey] | None = None,
    ocr_engine: Any = None,
) -> DocumentCheck:
    """Look at an uploaded document image. Never raises on bad input; see the module docstring."""
    try:
        return _check(image_bytes, kind, document_id=document_id, trusted_keys=trusted_keys, ocr_engine=ocr_engine)
    except Exception:  # noqa: BLE001 - the last line of defence: a person looks instead
        from app.core.logging import get_logger

        get_logger("rahat.docs_ai").exception("document check failed", extra={"document_id": document_id})
        signal = DocumentSignal(code="check_failed", weight=0.0, staff_detail="The automatic check failed on this image.")
        return _result(document_id, kind, "not_a_card", _abstain("human", ["check_failed"]), signals=[signal])


def _check(
    image_bytes: bytes, kind: DocumentKind, *, document_id: str,
    trusted_keys: dict[str, Ed25519PublicKey] | None, ocr_engine: Any,
) -> DocumentCheck:  # fmt: skip
    from app.modules.docs_ai import issuer
    from app.modules.docs_ai.forensics import ela_check, print_check
    from app.modules.docs_ai.geometry import locate_card, rectify
    from app.modules.docs_ai.imageio import DecodeError, decode
    from app.modules.docs_ai.payload import verify
    from app.modules.docs_ai.qr import read_qr

    engine = _ocr_engine(ocr_engine)
    evidence = _Evidence()

    try:
        decoded = decode(image_bytes)
    except DecodeError as exc:
        signal = DocumentSignal(code=exc.code, weight=0.0, staff_detail=exc.detail)
        return _result(document_id, kind, "not_a_card", _abstain("human", [exc.code]), retake=True,
                       ocr=OcrResult(available=engine.available()), signals=[signal])  # fmt: skip

    if decoded.editors:
        evidence.add("metadata_editor", f"Image metadata names an editing program: {decoded.editors[0][:40]}")

    if kind != "rahat_id":
        return _check_other(decoded.rgb, kind, document_id, evidence, engine.available())

    geom = locate_card(decoded.rgb)
    card = rectify(decoded.rgb, geom.matrix) if geom.matrix is not None else None
    qr_read = read_qr(decoded.rgb, card if geom.header_found else None)
    ocr_off = OcrResult(available=engine.available())

    def retake(quality: DocumentQuality, reason: str, detail: str) -> DocumentCheck:
        signals = [*evidence.signals, DocumentSignal(code=f"quality_{quality}", weight=0.0, staff_detail=detail)]
        return _result(document_id, kind, quality, _abstain("ask_more", [f"quality_{quality}", reason]), retake=True,
                       qr=QrResult(found=qr_read.found), ocr=ocr_off, signals=signals)  # fmt: skip

    # 2. Quality gate -------------------------------------------------------------------------------
    if card is None or (not geom.header_found and not qr_read.text):
        if qr_read.found:
            return retake("cropped", "card_outline_not_found", "A QR code is visible but the card outline is not.")
        return retake("not_a_card", "card_not_found", "No Rahat card was found in the image.")
    if geom.touches_border:
        return retake("cropped", "card_touches_border", "The card runs off the edge of the photo.")
    width = card_width_px(geom.matrix) if geom.matrix is not None else 0.0
    if width < MIN_CARD_PX:
        return retake("blurry", "card_too_small", f"The card is only {width:.0f} px wide; move closer.")
    blur = blur_score(decoded.rgb, geom.matrix) if geom.matrix is not None else 0.0
    if blur < BLUR_MIN:
        return retake("blurry", "low_sharpness", f"Sharpness {blur:.0f} is below {BLUR_MIN:.0f}.")
    glare = glare_share(card)
    quality: DocumentQuality = "ok"
    if glare >= GLARE_MIN:
        if not qr_read.text:
            return retake("glare", "glare_hides_qr", f"Glare covers {glare:.0%} of the card and the QR cannot be read.")
        quality = "glare"  # accepted: the signed QR still reads
    elif qr_read.found and not qr_read.text and blur < BLUR_SOFT:
        return retake("blurry", "qr_unreadable_soft_focus", f"The QR is visible but unreadable; sharpness {blur:.0f}.")

    # 3. QR and signature ---------------------------------------------------------------------------
    trusted = trusted_keys if trusted_keys is not None else issuer.trusted_public_keys()
    qr = QrResult(found=qr_read.found or bool(qr_read.text))
    signed: dict[str, str] | None = None
    if qr_read.oversized:
        evidence.add("qr_payload_oversized", "The QR holds far more data than a Rahat card payload.")
        qr.signature_valid = False
    elif qr_read.text:
        check = verify(qr_read.text, trusted)
        qr.issuer_key_id = check.key_id
        if check.fields is not None:
            qr.payload = check.fields.as_dict()
            signed = check.fields.as_dict()
        qr.signature_valid = check.valid
        if check.status == "valid":
            evidence.add("qr_signature_valid", f"QR payload signed by trusted issuer key {check.key_id}.")
        elif check.status == "invalid_signature":
            evidence.add("qr_signature_invalid", f"QR payload does not match its signature (key {check.key_id}); the data was changed.")
        elif check.status == "unknown_issuer":
            evidence.add("qr_issuer_unknown", f"QR payload is signed by key {check.key_id}, which is not a trusted issuer key.")
        else:
            evidence.add("qr_not_issuer_format", "The QR does not hold a Rahat card payload.")
    elif qr_read.found:
        evidence.add("qr_unreadable", "A QR code is present but could not be decoded.")
    else:
        evidence.add("qr_missing", "No QR code was found on a readable card.")
    if not geom.header_found:
        evidence.add("layout_unverified", "The card's header band was not recognised, so printed values were not compared.")

    # 4. OCR, and the print check against the signed payload -----------------------------------------
    field_glare = _field_glare(card)
    ocr = OcrResult(available=engine.available())
    if engine.available() and geom.header_found:
        ocr, comparisons = _run_ocr(engine, card, signed, field_glare)
        bad = [f for f, r in comparisons.items() if r == "mismatch"]
        if bad:
            evidence.add("ocr_qr_mismatch", "OCR of the printed " + ", ".join(FIELD_LABELS[f] for f in bad) + " differs from the signed QR.")
        elif comparisons.get("full_name") == "match" and comparisons.get("national_id") == "match":
            evidence.add("ocr_matches_qr", "OCR of the printed name and mock ID matches the signed QR.")
    if signed and geom.header_found:
        printed = print_check(card, signed)
        if printed.mismatched:
            parts = [f"{FIELD_LABELS[f]} (glyph score {printed.scores.get(f, 0):.2f})" for f in printed.mismatched]
            evidence.add("print_qr_mismatch", "Printed " + ", ".join(parts) + " does not match what the signed QR says.")
        elif printed.all_match:
            evidence.add("print_matches_qr", "Every printed value matches the signed QR, glyph by glyph.")

    # 5. Error level analysis, localised over the printed values --------------------------------------
    if decoded.ela is not None and geom.header_found:
        import cv2

        card_ela = rectify(decoded.ela, geom.matrix, interpolation=cv2.INTER_LINEAR) if geom.matrix is not None else None
        ela = ela_check(card_ela, card)
        if ela.anomalies:
            name, ratio = max(ela.anomalies.items(), key=lambda kv: kv[1])
            detail = f"Error level over the printed {FIELD_LABELS[name]} is {ratio:.1f}x the other values: likely edited after an earlier save."
            evidence.add("ela_anomaly", detail)

    return _result(document_id, kind, quality, _decide(evidence, qr), qr=qr, ocr=ocr, signals=evidence.signals)


def _decide(evidence: _Evidence, qr: QrResult) -> TypedDecision[Authenticity]:
    codes = evidence.codes
    score = PRIOR + sum(s.weight for s in evidence.signals)
    p_suspect = _sigmoid(score)
    reasons = [s.code for s in sorted(evidence.signals, key=lambda s: -abs(s.weight))]
    strong = any(s.weight >= STRONG for s in evidence.signals)
    probabilities = {"genuine": round(1.0 - p_suspect, 4), "suspect": round(p_suspect, 4)}
    if strong or p_suspect >= 0.5:
        return TypedDecision[Authenticity](choice="suspect", probabilities=probabilities, confidence=round(p_suspect, 4),
                                           route="human", reasons=reasons, model_version=MODEL_VERSION)  # fmt: skip
    if "qr_signature_valid" not in codes or not qr.signature_valid:
        return _abstain("human", reasons or ["qr_missing"])
    p_genuine = 1.0 - p_suspect
    route = "auto" if p_genuine >= GENUINE_AUTO_FLOOR else "human"
    if route == "human":
        reasons = [*reasons, "below_auto_floor"]
    return TypedDecision[Authenticity](choice="genuine", probabilities=probabilities, confidence=round(p_genuine, 4),
                                       route=route, reasons=reasons, model_version=MODEL_VERSION)  # fmt: skip


def _check_other(rgb: np.ndarray, kind: DocumentKind, document_id: str, evidence: _Evidence, ocr_available: bool) -> DocumentCheck:
    """Income proofs and other papers: quality gate only. Nothing here can verify them, so a person does."""
    import cv2

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    scale = 1000.0 / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    sharp = float(cv2.Laplacian(small.astype(np.float32), cv2.CV_32F).var())
    glare = float((rgb.min(axis=2) >= 250).mean())
    ocr = OcrResult(available=ocr_available)
    if sharp < BLUR_MIN / 2:
        signals = [*evidence.signals, DocumentSignal(code="quality_blurry", weight=0.0, staff_detail=f"Sharpness {sharp:.0f}.")]
        return _result(document_id, kind, "blurry", _abstain("ask_more", ["quality_blurry"]), retake=True, ocr=ocr, signals=signals)
    quality: DocumentQuality = "glare" if glare > 0.25 else "ok"
    reasons = ["doc_kind_not_machine_verifiable", *evidence.codes]
    return _result(document_id, kind, quality, _abstain("human", reasons), ocr=ocr, signals=evidence.signals)


# ------------------------------------------------------------------------------------------------ helpers for callers


def citizen_view(check: DocumentCheck) -> DocumentCitizenView:
    """What the citizen hears back. No signals, no scores: a retake request, 'ok', or 'a person will check'."""
    if check.retake_hint:
        return DocumentCitizenView(document_id=check.document_id, kind=check.kind, accepted=False, quality=check.quality,
                                   retake_hint=check.retake_hint, message_key=check.retake_hint)  # fmt: skip
    ok = check.authenticity.choice == "genuine" and check.authenticity.route == "auto"
    return DocumentCitizenView(document_id=check.document_id, kind=check.kind, accepted=True, quality=check.quality,
                               message_key="doc_ok" if ok else "doc_person_will_check")  # fmt: skip


def providers() -> dict[str, str]:
    """Which document-AI providers are active on this host, for /v1/system/health."""
    from app.modules.docs_ai import issuer
    from app.modules.docs_ai.ocr import default_engine

    return {
        "ocr_tesseract": "available" if default_engine().available() else "missing",
        "qr_opencv": "available",
        "ela": "available",
        "issuer_keys": ",".join(issuer.public_keys()),
        "issuer_seed": "default_dev_seed" if issuer.is_default_seed() else "configured",
    }
