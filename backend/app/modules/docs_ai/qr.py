"""Find and read the card's QR code with OpenCV. The decoded text is data; the caller only parses and verifies it."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.modules.docs_ai import layout as L
from app.modules.docs_ai.payload import MAX_PAYLOAD_BYTES


@dataclass
class QrRead:
    found: bool  # a QR symbol was detected, whether or not it decoded
    text: str | None = None
    oversized: bool = False


def _try(detector: object, gray: np.ndarray) -> tuple[bool, str]:
    try:
        text, points, _ = detector.detectAndDecode(gray)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a detector failure is "not read", never a crash
        return False, ""
    return points is not None and len(points) > 0, text or ""


def read_qr(rgb: np.ndarray, card: np.ndarray | None) -> QrRead:
    """Try the QR area of the rectified card first (small and sharp), then the whole photo."""
    import cv2

    attempts: list[np.ndarray] = []
    if card is not None:
        m = 24
        region = card[max(0, L.QR.y0 - m) : L.QR.y1 + m, max(0, L.QR.x0 - m) : L.QR.x1 + m]
        g = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        attempts.append(g)
        attempts.append(cv2.resize(g, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC))
    attempts.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))

    found = False
    detectors: list[object] = [cv2.QRCodeDetector()]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.append(cv2.QRCodeDetectorAruco())
    for detector in detectors:
        for gray in attempts:
            seen, text = _try(detector, gray)
            found = found or seen
            if text:
                if len(text.encode("utf-8", errors="replace")) > MAX_PAYLOAD_BYTES:
                    return QrRead(found=True, text=None, oversized=True)
                return QrRead(found=True, text=text)
    return QrRead(found=found)
