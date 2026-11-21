"""RapidOCR on the committed specimen cards (data/demo_cards). Skipped only when RapidOCR cannot be imported."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.modules.docs_ai.ocr import NoOcr, OcrLine, RapidOcr, default_engine
from app.modules.docs_ai.service import check_document

CARDS = Path(__file__).resolve().parents[5] / "data" / "demo_cards"
pytestmark = pytest.mark.skipif(not RapidOcr().available(), reason="rapidocr-onnxruntime cannot be imported")


def _check(slug: str, name: str, engine: object | None = None):  # type: ignore[no-untyped-def]
    return check_document((CARDS / slug / name).read_bytes(), "rahat_id", document_id="d", ocr_engine=engine or RapidOcr())


def _codes(check) -> set[str]:  # type: ignore[no-untyped-def]
    return {s.code for s in check.signals}


@pytest.mark.parametrize("slug", ["zainab-bibi", "aslam-khan", "rukhsana-parveen"])
def test_genuine_demo_card_passes_with_ocr_agreeing(slug: str) -> None:
    check = _check(slug, "clean.jpg")
    assert check.ocr.available and check.ocr.mean_confidence >= 0.6
    assert "ocr_matches_qr" in _codes(check) and "ocr_qr_mismatch" not in _codes(check)
    assert check.authenticity.choice == "genuine" and check.authenticity.route == "auto"


@pytest.mark.parametrize(("slug", "name"), [("zainab-bibi", "altered.jpg"), ("aslam-khan", "altered.jpg"), ("rukhsana-parveen", "altered.jpg"),
                                            ("zainab-bibi", "wrong_qr.jpg"), ("aslam-khan", "wrong_qr.jpg")])  # fmt: skip
def test_tampered_or_mismatched_card_raises_the_ocr_signal(slug: str, name: str) -> None:
    check = _check(slug, name)
    assert "ocr_qr_mismatch" in _codes(check)
    assert check.authenticity.choice == "suspect" and check.authenticity.route == "human"


def test_blank_band_is_not_read_not_guessed() -> None:
    lines = RapidOcr().read_lines([np.full((60, 400), 255, np.uint8)])
    assert lines == [None] or (lines[0] is not None and lines[0].confidence < 0.9)


def test_low_confidence_goes_to_unclear_not_a_guess() -> None:
    class Unsure:
        name = "unsure"

        def available(self) -> bool:
            return True

        def read_lines(self, bands: list[np.ndarray]) -> list[OcrLine | None]:
            return [OcrLine("Nasreen Akhtar", 0.3) for _ in bands]  # confident-looking text, low score

    check = _check("zainab-bibi", "clean.jpg", Unsure())
    assert "ocr_qr_mismatch" not in _codes(check)  # a shaky read must not be treated as a tampering finding


def test_default_engine_prefers_rapidocr() -> None:
    engine = default_engine()
    assert engine.name == "rapidocr" and not isinstance(engine, NoOcr)
