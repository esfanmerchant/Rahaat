"""Find the card in a photo and map it onto the canonical layout.

The card is lighter than what it lies on, roughly rectangular, and has a dark green header band along one
long edge. We find its outline, order the corners so the header is on top, and compute the homography from
card coordinates to image coordinates. A card whose outline runs into the image border is cut off.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import numpy as np

from app.modules.docs_ai import layout as L

Method = Literal["outline", "full_frame", "qr_anchor", "header", "none"]

MIN_AREA_SHARE = 0.08
BORDER_TOUCH_PX = 3


@dataclass
class CardGeometry:
    method: Method
    matrix: np.ndarray | None = None  # card -> image homography
    touches_border: bool = False
    header_found: bool = False
    area_share: float = 0.0
    card_colours: bool = False  # solid patches of the header green or the SPECIMEN red are in the photo

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


def _card_colours(green: np.ndarray, r: np.ndarray, g: np.ndarray, b: np.ndarray) -> bool:
    """True when the photo holds solid patches of the card's own colours (not speckle from noise or texture)."""
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    red = (((r - g) > 22) & ((r - b) > 22) & (np.abs(g - b) < 12)).astype(np.uint8) * 255  # pink-red, not brown wood
    red_share = float(cv2.morphologyEx(red, cv2.MORPH_OPEN, kernel).mean()) / 255.0
    green_share = float(cv2.morphologyEx(green, cv2.MORPH_OPEN, kernel).mean()) / 255.0
    return red_share >= 0.002 or green_share >= 0.005


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
            colours = _card_colours(green, r, g, b)
            return CardGeometry("outline", _homography(corners), touches_border=True, header_found=header, area_share=share, card_colours=colours)

    if frame_like:
        # The upload is the card itself, edge to edge (a scan or the generated file).
        corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        corners, header = _oriented(corners, rgb)
        if header:
            return CardGeometry("full_frame", _homography(corners), touches_border=False, header_found=True, area_share=1.0)
    return CardGeometry("none")


def _project(matrix: np.ndarray, pts: np.ndarray) -> np.ndarray:
    h = np.hstack([pts.astype(np.float64), np.ones((len(pts), 1))]) @ matrix.T
    return np.asarray(h[:, :2] / h[:, 2:3])


CARD_CORNERS = np.array([[0, 0], [L.CARD_W, 0], [L.CARD_W, L.CARD_H], [0, L.CARD_H]], dtype=np.float64)


def from_qr(rgb: np.ndarray, points: np.ndarray, modules: int) -> CardGeometry:
    """Locate the card from its QR when the outline is lost (a white table, a screenshot with margins).

    The QR sits at a fixed place on the card, so its four corners fix the whole card. A card whose predicted
    corners fall outside the photo is cut off.
    """
    import cv2

    from app.modules.docs_ai.qr import symbol_box

    left, top, side = symbol_box(modules)
    # Only the three finder-pattern corners are measured; OpenCV extrapolates the fourth, so it is not used.
    src = np.array([[left, top], [left + side, top], [left, top + side]], dtype=np.float32)
    dst = points[[0, 1, 3]].astype(np.float32)
    matrix = np.vstack([cv2.getAffineTransform(src, dst), [0.0, 0.0, 1.0]])
    corners = _project(matrix, CARD_CORNERS)
    h, w = rgb.shape[:2]
    inside = bool(((corners[:, 0] >= -2) & (corners[:, 0] <= w + 1) & (corners[:, 1] >= -2) & (corners[:, 1] <= h + 1)).all())
    header = header_score(rectify(rgb, matrix)) >= 0.5
    area = float(cv2.contourArea(corners.astype(np.float32))) / float(w * h)
    return CardGeometry("qr_anchor", matrix, touches_border=not inside, header_found=header, area_share=area)


# Static print that is the same on every card, used to fine-tune the alignment: (x0, y0, x1, y1) in card pixels.
_ANCHORS: tuple[tuple[int, int, int, int], ...] = (
    (30, 12, 320, 66),  # RAHAT CARD
    (34, 66, 420, 94),  # PROTOTYPE - MOCK RELIEF PROGRAMME
    (770, 28, 966, 78),  # SPECIMEN badge
    (36, 132, 236, 392),  # photo placeholder
    (712, 384, 972, 404),  # SCAN TO VERIFY
    (30, 562, 760, 588),  # footer line 1
    (30, 592, 640, 612),  # footer line 2
    *((L.FIELD_X - 4, L.row_top(i) - 2, L.FIELD_X + 160, L.row_top(i) + 21) for i in range(len(L.FIELDS))),
)
ANCHOR_SEARCH = 18
ANCHOR_MIN_SCORE = 0.6


@lru_cache(maxsize=1)
def _reference_gray() -> np.ndarray:
    """A rendered card; only its static print is used."""
    import cv2

    from app.modules.docs_ai.card import render_card
    from app.modules.docs_ai.payload import CardFields

    fields = CardFields("Reference Card", "00000-0000000-0", "2000-01-01", "other", "Reference")
    with L.RENDER_LOCK:
        card = render_card(fields, "RC1|reference", key_id="reference")
    return np.asarray(cv2.cvtColor(np.asarray(card), cv2.COLOR_RGB2GRAY), dtype=np.float32)


def _refine_pass(rgb: np.ndarray, matrix: np.ndarray, search: int, min_score: float, max_move: float) -> tuple[np.ndarray, int]:
    import cv2

    ref = _reference_gray()
    observed = cv2.cvtColor(rectify(rgb, matrix), cv2.COLOR_RGB2GRAY).astype(np.float32)
    card_pts, seen_pts = [], []
    for x0, y0, x1, y1 in _ANCHORS:
        templ = ref[y0:y1, x0:x1]
        wx0, wy0 = max(0, x0 - search), max(0, y0 - search)
        window = observed[wy0 : min(L.CARD_H, y1 + search), wx0 : min(L.CARD_W, x1 + search)]
        if window.shape[0] < templ.shape[0] or window.shape[1] < templ.shape[1]:
            continue
        res = cv2.matchTemplate(window, templ, cv2.TM_CCOEFF_NORMED)
        _, score, _, (bx, by) = cv2.minMaxLoc(res)
        if score < min_score:
            continue
        card_pts.append(((x0 + x1) / 2, (y0 + y1) / 2))
        seen_pts.append((wx0 + bx + (x1 - x0) / 2, wy0 + by + (y1 - y0) / 2))
    if len(card_pts) < 6:
        return matrix, len(card_pts)
    image_pts = _project(matrix, np.array(seen_pts))
    refined, inliers = cv2.findHomography(np.array(card_pts, dtype=np.float32), image_pts.astype(np.float32), cv2.RANSAC, 2.5)
    if refined is None or inliers is None or int(inliers.sum()) < 6:
        return matrix, len(card_pts)
    moved = np.abs(_project(refined, CARD_CORNERS) - _project(matrix, CARD_CORNERS)).max()
    if moved > max_move * L.CARD_W:  # a big jump means the anchors disagree with each other; keep what we had
        return matrix, int(inliers.sum())
    return np.asarray(refined), int(inliers.sum())


def refine(rgb: np.ndarray, matrix: np.ndarray) -> tuple[np.ndarray, int]:
    """Re-fit the homography to the static print, coarse then fine. Returns the matrix and how many anchors agreed."""
    matrix, _ = _refine_pass(rgb, matrix, search=60, min_score=0.5, max_move=0.12)
    return _refine_pass(rgb, matrix, search=ANCHOR_SEARCH, min_score=ANCHOR_MIN_SCORE, max_move=0.06)


def from_header(rgb: np.ndarray) -> CardGeometry:
    """Locate the card from its green header band, which spans the card's full width.

    Used when the outline is lost: a light table merges with the card, and a blurred or glared QR cannot anchor it.
    """
    import cv2

    blurred = cv2.GaussianBlur(rgb, (5, 5), 0).astype(np.int16)
    r, g, b = blurred[..., 0], blurred[..., 1], blurred[..., 2]
    raw = ((g - r > 25) & (g >= b - 4) & (g > 40)).astype(np.uint8) * 255
    closed = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    green = cv2.morphologyEx(closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return CardGeometry("none")
    band = max(contours, key=cv2.contourArea)
    h, w = rgb.shape[:2]
    pts = band.reshape(-1, 2)
    band_cut = bool(
        (
            (pts[:, 0] <= BORDER_TOUCH_PX)
            | (pts[:, 1] <= BORDER_TOUCH_PX)
            | (pts[:, 0] >= w - 1 - BORDER_TOUCH_PX)
            | (pts[:, 1] >= h - 1 - BORDER_TOUCH_PX)
        ).any()
    )
    rect = cv2.minAreaRect(band)
    bw, bh = rect[1]
    long, short = max(bw, bh), min(bw, bh)
    if short < 8 or not 6.0 <= long / short <= 14.0 or long * short < 0.01 * w * h:
        return CardGeometry("none")
    box = np.asarray(cv2.boxPoints(rect), dtype=np.float64)
    edges = [(box[i], box[(i + 1) % 4]) for i in range(4)]
    long_edges = sorted(edges, key=lambda e: -float(np.linalg.norm(e[1] - e[0])))[:2]
    height = L.CARD_H * long / L.CARD_W
    best: CardGeometry | None = None
    best_score = -1.0
    for top, other in ((long_edges[0], long_edges[1]), (long_edges[1], long_edges[0])):
        a, c = top
        mid_top, mid_other = (a + c) / 2, (other[0] + other[1]) / 2
        normal = (mid_other - mid_top) / max(1e-6, float(np.linalg.norm(mid_other - mid_top)))
        tl, tr = (a, c) if (c - a)[0] * normal[1] - (c - a)[1] * normal[0] > 0 else (c, a)
        corners = np.array([tl, tr, tr + normal * height, tl + normal * height], dtype=np.float32)
        matrix = _homography(corners)
        score = header_score(rectify(rgb, matrix))
        if score > best_score:
            inside = bool(((corners[:, 0] >= -2) & (corners[:, 0] <= w + 1) & (corners[:, 1] >= -2) & (corners[:, 1] <= h + 1)).all())
            best_score = score
            # A band that reaches the frame edge may be cut short, so its width cannot be trusted: call it cut off.
            best = CardGeometry("header", matrix, touches_border=band_cut or not inside, header_found=score >= 0.5, area_share=0.0)
    return best if best is not None else CardGeometry("none")
