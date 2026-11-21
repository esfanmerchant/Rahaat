"""Fixtures for document-AI tests. Images are generated once per session from invented people."""

from __future__ import annotations

import shutil
from collections.abc import Sequence

import numpy as np
import pytest

from app.core.mockdata import make_mock_id
from app.modules.docs_ai.ocr import OcrLine
from app.modules.docs_ai.payload import CardFields

requires_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract binary not installed on this host")

PERSON = CardFields("Zainab Bibi", make_mock_id(1000201), "1978-03-14", "female", "Karachi East")
OTHER = CardFields("Aslam Khan", make_mock_id(1000202), "1981-09-02", "male", "Hyderabad")


class CannedOcr:
    """An OCR engine that returns fixed lines, one per field band, so OCR logic is testable without Tesseract."""

    name = "canned"

    def __init__(self, lines: Sequence[str | None], confidence: float = 0.9) -> None:
        self.lines = list(lines)
        self.confidence = confidence
        self.calls = 0

    def available(self) -> bool:
        return True

    def read_lines(self, bands: list[np.ndarray]) -> list[OcrLine | None]:
        self.calls += 1
        assert len(bands) == len(self.lines)
        return [OcrLine(t, self.confidence) if t is not None else None for t in self.lines]


class NoOcrEngine:
    name = "none"

    def available(self) -> bool:
        return False

    def read_lines(self, bands: list[np.ndarray]) -> list[OcrLine | None]:
        return [None for _ in bands]


@pytest.fixture(scope="session")
def key():  # type: ignore[no-untyped-def]
    from app.modules.docs_ai.issuer import issuer_key

    return issuer_key()


@pytest.fixture(scope="session")
def images(key) -> dict[str, bytes]:  # type: ignore[no-untyped-def]
    """One image per scenario, built with the same parameters the demo set uses."""
    from app.modules.docs_ai.variants import EDITOR_SOFTWARE, Forgery, Shot, flat_card_png, make_variant

    shot = Shot(canvas=(1120, 840), card_width=840.0, angle=2.0, noise=1.2, quality=84, seed=3)
    out: dict[str, bytes] = {"flat": flat_card_png(PERSON, key)}
    for name in ("clean", "glare", "glare_qr", "blurry", "cropped", "wrong_qr", "unknown_issuer", "bad_signature"):
        out[name] = make_variant(name, PERSON, key, shot=shot, other=OTHER).image
    out["altered"] = make_variant(
        "altered", PERSON, key, shot=Shot(canvas=(1120, 840), card_width=840.0, quality=92, noise=1.2, seed=4),
        edit=("full_name", "Nasreen Akhtar"), forgery=Forgery(first_quality=70, software=EDITOR_SOFTWARE),
    ).image  # fmt: skip
    out["altered_plain"] = make_variant(
        "altered", PERSON, key, shot=shot, edit=("full_name", "Nasreen Akhtar"), forgery=Forgery(first_quality=88, software=None)
    ).image
    out["altered_id_digit"] = make_variant(
        "altered", PERSON, key, shot=shot, edit=("national_id", make_mock_id(1000207)), forgery=Forgery(first_quality=88, software=None)
    ).image
    out["cropped_bottom"] = make_variant("cropped", PERSON, key, shot=shot, crop_side="bottom", crop_fraction=0.3).image
    out["upside_down"] = make_variant("clean", PERSON, key, shot=Shot(angle=178.0, seed=5)).image
    out["forwarded"] = make_variant("clean", PERSON, key, shot=Shot(quality=90, seed=6), forwarded_quality=75).image
    out["white_table"] = make_variant("clean", PERSON, key, shot=Shot(background=(236, 234, 230), angle=4.0, seed=7)).image
    out["screenshot"] = _on_white_page(out["flat"])
    return out


def _on_white_page(card_png: bytes) -> bytes:
    """The card file shown inside a white page, as in a screenshot."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(card_png)) as card:
        page = Image.new("RGB", (1400, 1100), (255, 255, 255))
        page.paste(card.convert("RGB"), (200, 240))
    buf = io.BytesIO()
    page.save(buf, "PNG")
    return buf.getvalue()
