"""Find the card in a photo and map it onto the canonical layout.

The card is lighter than what it lies on, roughly rectangular, and has a dark green header band along one
long edge. We find its outline, order the corners so the header is on top, and compute the homography from
card coordinates to image coordinates. A card whose outline runs into the image border is cut off.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.modules.docs_ai import layout as L

Method = Literal["outline", "full_frame", "none"]

MIN_AREA_SHARE = 0.08
BORDER_TOUCH_PX = 3


@dataclass
class CardGeometry:
    method: Method
    matrix: np.ndarray | None = None  # card -> image homography
    touches_border: bool = False
    header_found: bool = False
    area_share: float = 0.0

    @property
    def located(self) -> bool:
        return self.matrix is not None


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left in image terms."""
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1)[:, 0]
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _homography(corners: np.ndarray) -> np.ndarray:
    import cv2

    src = np.array([[0, 0], [L.CARD_W, 0], [L.CARD_W, L.CARD_H], [0, L.CARD_H]], dtype=np.float32)
    return np.asarray(cv2.getPerspectiveTransform(src, corners.astype(np.float32)))


def rectify(rgb: np.ndarray, matrix: np.ndarray, *, interpolation: int | None = None) -> np.ndarray:
    """Warp the image onto the canonical card (1000 x 630)."""
    import cv2

    flags = (cv2.INTER_LINEAR if interpolation is None else interpolation) | cv2.WARP_INVERSE_MAP
    return np.asarray(cv2.warpPerspective(rgb, matrix, (L.CARD_W, L.CARD_H), flags=flags, borderMode=cv2.BORDER_REPLICATE))


def header_score(card_rgb: np.ndarray) -> float:
    """How much the header strip looks like the card's dark green band (0..1)."""
    h = L.HEADER
    strip = card_rgb[h.y0 + 8 : h.y1 - 8, 12 : L.BADGE.x0 - 20].reshape(-1, 3).astype(np.int16)
    if strip.size == 0:
        return 0.0
    r, g, b = strip[:, 0], strip[:, 1], strip[:, 2]
    green = (g - r > 25) & (g >= b) & (g < 200)
    return float(green.mean())


def _oriented(corners: np.ndarray, rgb: np.ndarray) -> tuple[np.ndarray, bool]:
    """Rotate the corner order so the long edge is the width and the header band is on top."""
    top = np.linalg.norm(corners[1] - corners[0])
    left = np.linalg.norm(corners[3] - corners[0])
    if left > top:  # the card stands on its short edge
        corners = np.roll(corners, -1, axis=0)
    best, best_score = corners, -1.0
    for turn in (0, 2):
        candidate = np.roll(corners, -turn, axis=0)
        score = header_score(rectify(rgb, _homography(candidate)))
        if score > best_score:
            best, best_score = candidate, score
    return best, best_score >= 0.5


def _quad_from_contour(contour: np.ndarray) -> np.ndarray:
    import cv2

    peri = cv2.arcLength(contour, True)
    for eps in (0.01, 0.02, 0.03, 0.05):
        approx = cv2.approxPolyDP(contour, eps * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return _order_corners(approx.reshape(4, 2).astype(np.float32))
    box = cv2.boxPoints(cv2.minAreaRect(contour))
    return _order_corners(np.asarray(box, dtype=np.float32))


def locate_card(rgb: np.ndarray) -> CardGeometry:
    import cv2

    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    smooth = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(smooth, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # The header band is dark, so Otsu files it with the table; add it back by its colour (our own design).
    blurred = cv2.GaussianBlur(rgb, (5, 5), 0).astype(np.int16)
    r, g, b = blurred[..., 0], blurred[..., 1], blurred[..., 2]
    green = ((g - r > 25) & (g >= b - 4) & (g > 40)).astype(np.uint8) * 255
    mask = cv2.bitwise_or(mask, green)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    aspect = w / h
    frame_like = abs(aspect - L.CARD_ASPECT) / L.CARD_ASPECT < 0.08 or abs(1 / aspect - L.CARD_ASPECT) / L.CARD_ASPECT < 0.08

    if contours:
        biggest = max(contours, key=cv2.contourArea)
        share = float(cv2.contourArea(biggest)) / float(w * h)
        pts = biggest.reshape(-1, 2)
        near = (
            (pts[:, 0] <= BORDER_TOUCH_PX)
            | (pts[:, 1] <= BORDER_TOUCH_PX)
            | (pts[:, 0] >= w - 1 - BORDER_TOUCH_PX)
            | (pts[:, 1] >= h - 1 - BORDER_TOUCH_PX)
        )
        touches = bool(near.any())
        if share >= MIN_AREA_SHARE and not touches:
            corners, header = _oriented(_quad_from_contour(biggest), rgb)
            return CardGeometry("outline", _homography(corners), touches_border=False, header_found=header, area_share=share)
        if share >= MIN_AREA_SHARE and touches and not (frame_like and share > 0.5):
            corners, header = _oriented(_quad_from_contour(biggest), rgb)
            return CardGeometry("outline", _homography(corners), touches_border=True, header_found=header, area_share=share)

    if frame_like:
        # The upload is the card itself, edge to edge (a scan or the generated file).
        corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        corners, header = _oriented(corners, rgb)
        if header:
            return CardGeometry("full_frame", _homography(corners), touches_border=False, header_found=True, area_share=1.0)
    return CardGeometry("none")
