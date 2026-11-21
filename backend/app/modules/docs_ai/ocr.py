"""OCR of the printed card fields, behind a small engine interface.

The default local engine is RapidOCR (PP-OCR models in ONNX, bundled in the wheel, no network). Tesseract through
`pytesseract` is the fallback when its binary is installed. Without either, `available()` is false and the rest of
`check_document` still works. Whatever OCR
returns is data: it is normalised with fixed rules and compared with the signed QR, never interpreted.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np
from rapidfuzz import fuzz

OCR_TIMEOUT_S = 4
BAND_GAP = 24


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float  # 0..1


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def read_lines(self, bands: list[np.ndarray]) -> list[OcrLine | None]:
        """Read one line of text from each grayscale band image, in order."""
        ...


class NoOcr:
    name = "none"

    def available(self) -> bool:
        return False

    def read_lines(self, bands: list[np.ndarray]) -> list[OcrLine | None]:
        return [None for _ in bands]


class TesseractOcr:
    """One Tesseract run per card: the field bands are stacked into one image to avoid a process per field."""

    name = "tesseract"

    def __init__(self, cmd: str | None = None) -> None:
        self.cmd = cmd or os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")

    def available(self) -> bool:
        return bool(self.cmd)

    def read_lines(self, bands: list[np.ndarray]) -> list[OcrLine | None]:
        if not self.cmd or not bands:
            return [None for _ in bands]
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = self.cmd
        width = max(b.shape[1] for b in bands)
        rows: list[np.ndarray] = []
        spans: list[tuple[int, int]] = []
        y = BAND_GAP
        rows.append(np.full((BAND_GAP, width), 255, np.uint8))
        for band in bands:
            padded = np.full((band.shape[0], width), 255, np.uint8)
            padded[:, : band.shape[1]] = band
            rows.append(padded)
            spans.append((y, y + band.shape[0]))
            y += band.shape[0] + BAND_GAP
            rows.append(np.full((BAND_GAP, width), 255, np.uint8))
        sheet = np.vstack(rows)
        try:
            data = pytesseract.image_to_data(sheet, lang="eng", config="--psm 6 --oem 1", output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - OCR failure means "not read", never a crash
            return [None for _ in bands]
        words: list[list[tuple[int, str, float]]] = [[] for _ in bands]
        for text, conf, top, height, left in zip(data["text"], data["conf"], data["top"], data["height"], data["left"], strict=False):
            word = str(text).strip()
            try:
                c = float(conf)
            except (TypeError, ValueError):
                continue
            if not word or c < 0:
                continue
            middle = int(top) + int(height) // 2
            for i, (y0, y1) in enumerate(spans):
                if y0 <= middle < y1:
                    words[i].append((int(left), word, c / 100.0))
                    break
        out: list[OcrLine | None] = []
        for ws in words:
            if not ws:
                out.append(None)
                continue
            ws.sort()
            out.append(OcrLine(" ".join(w for _, w, _ in ws), float(np.mean([c for _, _, c in ws]))))
        return out


_rapid_lock = threading.Lock()
_rapid_model: object | None = None


def _rapid_instance() -> object | None:
    """One recogniser per process, built on first use under a lock. None when the package cannot be imported."""
    global _rapid_model
    if _rapid_model is None:
        with _rapid_lock:
            if _rapid_model is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR

                    _rapid_model = RapidOCR()
                except Exception:  # noqa: BLE001 - missing package or model: "not available", never a crash
                    return None
    return _rapid_model


class RapidOcr:
    """PP-OCR recogniser only: each field band is one line, so no text detection and no angle classifier run."""

    name = "rapidocr"

    def __init__(self) -> None:
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is None:
            self._available = importlib.util.find_spec("rapidocr_onnxruntime") is not None and _rapid_instance() is not None
        return self._available

    def read_lines(self, bands: list[np.ndarray]) -> list[OcrLine | None]:
        model = _rapid_instance() if bands else None
        if model is None:
            return [None for _ in bands]
        import cv2

        out: list[OcrLine | None] = []
        for band in bands:
            try:
                img = cv2.cvtColor(band, cv2.COLOR_GRAY2BGR) if band.ndim == 2 else band
                with _rapid_lock:  # one call at a time: the wrapper keeps per-call state
                    result, _ = model(img, use_det=False, use_cls=False, use_rec=True)  # type: ignore[operator]
                text, score = str(result[0][0]).strip(), float(result[0][1])
                out.append(OcrLine(text, max(0.0, min(1.0, score))) if text else None)
            except Exception:  # noqa: BLE001 - OCR failure means "not read", never a crash
                out.append(None)
        return out


@lru_cache(maxsize=1)
def default_engine() -> OcrEngine:
    """RapidOCR, then Tesseract, then nothing."""
    for engine in (RapidOcr(), TesseractOcr()):
        if engine.available():
            return engine
    return NoOcr()


# ---------------------------------------------------------------- field parsing (pure, unit-tested with canned text)

_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "i": "1", "!": "1",
                              "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "G": "6", "b": "6", "T": "7", "g": "9"})  # fmt: skip
_DASHES = re.compile(r"[‐-―_~=]")
_ID = re.compile(r"(\d{5})\s*-?\s*(\d{7})\s*-?\s*(\d)")
_DATE = re.compile(r"(\d{4})\s*[-./ ]\s*(\d{2})\s*[-./ ]\s*(\d{2})")
_NOT_NAME = re.compile(r"[^A-Za-z .'\-]")
_SPACES = re.compile(r"\s+")


def _digits_view(text: str) -> str:
    return _DASHES.sub("-", text).translate(_DIGIT_FIXES)


def normalise_text(text: str) -> str:
    """Letters and spaces only, single-spaced, case-folded. For names and districts."""
    return _SPACES.sub(" ", _NOT_NAME.sub(" ", text)).strip().casefold()


def parse_field(field: str, text: str) -> str | None:
    """Turn one OCR'd line into a field value in payload form, or None when it does not parse."""
    text = text.strip()
    if not text:
        return None
    if field == "national_id":
        m = _ID.search(_digits_view(text))
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    if field == "dob":
        m = _DATE.search(_digits_view(text))
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    if field == "gender":
        word = normalise_text(text).replace(" ", "").upper()
        best = max(("FEMALE", "MALE", "OTHER"), key=lambda g: fuzz.ratio(word, g))
        return best.lower() if fuzz.ratio(word, best) >= 75 else None
    cleaned = _SPACES.sub(" ", _NOT_NAME.sub(" ", text)).strip(" .'-")  # letters kept as printed; compared case-folded
    return cleaned or None


def _digit_distance(a: str, b: str) -> int:
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    if len(da) != len(db):
        return max(len(da), len(db))
    return sum(1 for x, y in zip(da, db, strict=True) if x != y)


def compare_field(field: str, ocr_value: str | None, signed_value: str) -> str:
    """'match', 'mismatch' or 'unclear' for one field: printed (OCR) against signed (QR)."""
    if ocr_value is None:
        return "unclear"
    if field in ("national_id", "dob"):
        d = _digit_distance(ocr_value, signed_value)
        return "match" if d == 0 else ("unclear" if d == 1 else "mismatch")
    if field == "gender":
        return "match" if ocr_value == signed_value else "mismatch"
    score = fuzz.ratio(normalise_text(ocr_value), normalise_text(signed_value)) / 100.0
    if score >= 0.85:
        return "match"
    return "mismatch" if score <= 0.6 else "unclear"
