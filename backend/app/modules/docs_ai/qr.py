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
    points: np.ndarray | None = None  # symbol corners in the photo (TL, TR, BR, BL), when read from the whole photo
    modules: int | None = None  # symbol size in modules, when known


def _try(detector: object, gray: np.ndarray) -> tuple[bool, str, np.ndarray | None, int | None]:
    try:
        text, points, straight = detector.detectAndDecode(gray)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a detector failure is "not read", never a crash
        return False, "", None, None
    seen = points is not None and len(points) > 0
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2) if seen else None
    modules = int(straight.shape[0]) if text and straight is not None and getattr(straight, "ndim", 0) == 2 else None
    return seen, text or "", pts if pts is not None and pts.shape == (4, 2) else None, modules


def read_qr(rgb: np.ndarray, card: np.ndarray | None) -> QrRead:
    """Try the QR area of the rectified card first (small and sharp), then the whole photo."""
    import cv2

    attempts: list[tuple[np.ndarray, bool]] = []
    if card is not None:
        m = 24
        region = card[max(0, L.QR.y0 - m) : L.QR.y1 + m, max(0, L.QR.x0 - m) : L.QR.x1 + m]
        g = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        attempts.append((g, False))
        attempts.append((cv2.resize(g, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC), False))
    attempts.append((cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), True))

    found = False
    detectors: list[object] = [cv2.QRCodeDetector()]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.append(cv2.QRCodeDetectorAruco())
    for detector in detectors:
        for gray, whole in attempts:
            seen, text, points, modules = _try(detector, gray)
            found = found or seen
            if text:
                if len(text.encode("utf-8", errors="replace")) > MAX_PAYLOAD_BYTES:
                    return QrRead(found=True, text=None, oversized=True)
                return QrRead(found=True, text=text, points=points if whole else None, modules=modules)
    return QrRead(found=found)


def symbol_box(modules: int) -> tuple[float, float, float]:
    """Where the renderer puts a symbol of this size: (left, top, side) in card coordinates."""
    total = modules + 8
    scale = max(1, L.QR_MAX_PX // total)
    offset = (L.QR.w - total * scale) // 2 + 4 * scale
    return float(L.QR.x0 + offset), float(L.QR.y0 + offset), float(modules * scale)
