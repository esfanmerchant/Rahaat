"""Authenticity evidence that does not need OCR.

* Print check: we know the card's layout and font, so we can draw what the signed QR says should be printed in
  each field and compare it, glyph by glyph, with the photo. A changed name or digit stops matching.
* Error level analysis (ELA): a patch edited into an already-compressed photo re-compresses differently from the
  rest. We compare the error level over each printed value with the other values on the same card.
* Metadata: an image editor named in EXIF or XMP.

Each returns per-field results; `service` turns them into weighted signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw

from app.modules.docs_ai import layout as L

FieldResult = Literal["match", "mismatch", "unclear"]

PRINT_FILL = 18
PRINT_BACKGROUND = 246
GLOBAL_MIN = 0.6
GLYPH_MIN = 0.68
SATURATED = 248
GLYPH_SATURATED_MAX = 0.05
READABLE_GLYPHS_MIN = 0.6
DIGIT_MARGIN = 0.03  # another digit must fit this much better than the signed one

ELA_RATIO = 1.6
ELA_MIN_DIFF = 0.8
ELA_MIN_TEXT_PX = 40


BLUR_STEPS = (0.0, 0.5, 0.8, 1.1, 1.4, 1.7, 2.0, 2.4, 2.8, 3.3)
MAX_JUDGED_BLUR = 2.0  # above this (in card pixels) printed glyphs are too soft to tell apart


@dataclass
class PrintCheck:
    fields: dict[str, FieldResult] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)  # lowest readable glyph score per field
    digit_gaps: dict[str, float] = field(default_factory=dict)  # largest (best other digit - signed digit) per field
    blur_sigma: float = 0.0

    @property
    def mismatched(self) -> list[str]:
        return [f for f, r in self.fields.items() if r == "mismatch"]

    @property
    def all_match(self) -> bool:
        return bool(self.fields) and all(r == "match" for r in self.fields.values())


@dataclass
class ElaCheck:
    applicable: bool
    levels: dict[str, float] = field(default_factory=dict)
    anomalies: dict[str, float] = field(default_factory=dict)  # field -> ratio to the other fields


@dataclass(frozen=True)
class _Glyph:
    x0: int  # x range in template coordinates
    x1: int
    char: str
    left: float  # where the glyph is drawn, in render-canvas coordinates


@dataclass(frozen=True)
class _Template:
    pixels: np.ndarray  # float32, PRINT_FILL text on PRINT_BACKGROUND
    origin: tuple[int, int]  # card coordinates of the template's top-left
    glyphs: tuple[_Glyph, ...]  # every visible glyph
    size: int  # font size
    rows: tuple[int, int]  # template rows, in render-canvas coordinates
    x0: int  # template left edge, in render-canvas coordinates


@lru_cache(maxsize=256)
def _template(field_name: str, value: str) -> _Template | None:
    text = L.display_value(field_name, value)
    size = L.value_font_size(text)
    font = L.font(size)
    pad_top = 20
    img = Image.new("L", (L.CARD_W, 90), PRINT_BACKGROUND)
    ImageDraw.Draw(img).text((L.FIELD_X, pad_top), text, font=font, fill=PRINT_FILL)
    arr = np.asarray(img, dtype=np.float32)
    ys, xs = np.where(arr < 200)
    if ys.size == 0:
        return None
    y0, y1 = int(ys.min()) - 3, int(ys.max()) + 4
    x0, x1 = L.FIELD_X - 3, int(xs.max()) + 4
    glyphs = []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        left = L.FIELD_X + font.getlength(text[:i])
        g0 = int(left) - x0 - 1
        g1 = int(np.ceil(L.FIELD_X + font.getlength(text[: i + 1]))) - x0 + 1
        glyphs.append(_Glyph(max(0, g0), min(x1 - x0, g1), ch, left))
    row_y = L.row_top(L.field_index(field_name)) + L.VALUE_DY
    return _Template(arr[y0:y1, x0:x1].copy(), (x0, y0 - pad_top + row_y), tuple(glyphs), size, (y0, y1), x0)


@lru_cache(maxsize=512)
def _digit_cells(size: int, left: float, rows: tuple[int, int], cols: tuple[int, int]) -> dict[str, np.ndarray]:
    """Each digit drawn alone at one glyph position and cropped like that glyph's cell (the font's digits are tabular)."""
    font = L.font(size)
    out = {}
    for d in "0123456789":
        img = Image.new("L", (cols[1] + 4, 90), PRINT_BACKGROUND)
        ImageDraw.Draw(img).text((left, 20), d, font=font, fill=PRINT_FILL)
        out[d] = np.asarray(img, dtype=np.float32)[rows[0] : rows[1], cols[0] : cols[1]].copy()
    return out


def _ncc_max(window: np.ndarray, templ: np.ndarray) -> tuple[float, tuple[int, int]]:
    import cv2

    if window.shape[0] < templ.shape[0] or window.shape[1] < templ.shape[1] or float(templ.std()) < 1.0:
        return 0.0, (0, 0)
    res = cv2.matchTemplate(window, templ, cv2.TM_CCOEFF_NORMED)
    _, best, _, loc = cv2.minMaxLoc(res)
    return float(best), (int(loc[0]), int(loc[1]))


def _soften(pixels: np.ndarray, sigma: float) -> np.ndarray:
    import cv2

    return pixels if sigma <= 0 else np.asarray(cv2.GaussianBlur(pixels, (0, 0), sigma))


@lru_cache(maxsize=1)
def _label_templates() -> tuple[tuple[np.ndarray, tuple[int, int]], ...]:
    """The static labels printed on every card (NAME, MOCK ID NO., ...), as they are drawn."""
    out = []
    for i, (_, label) in enumerate(L.FIELDS):
        img = Image.new("L", (L.CARD_W, 60), PRINT_BACKGROUND)
        ImageDraw.Draw(img).text((L.FIELD_X, 20), label, font=L.font(L.LABEL_SIZE), fill=104)
        arr = np.asarray(img, dtype=np.float32)
        ys, xs = np.where(arr < 200)
        y0, y1, x0, x1 = int(ys.min()) - 3, int(ys.max()) + 4, int(xs.min()) - 3, int(xs.max()) + 4
        out.append((arr[y0:y1, x0:x1].copy(), (x0, y0 - 20 + L.row_top(i))))
    return tuple(out)


def estimate_blur(red: np.ndarray) -> float:
    """How soft this photo is, in card pixels: the Gaussian blur that makes the static labels match best."""
    windows = []
    for templ, (x, y) in _label_templates():
        m = 8
        windows.append((red[max(0, y - m) : y + templ.shape[0] + m, max(0, x - m) : x + templ.shape[1] + m], templ))
    best_sigma, best_score = 0.0, -1.0
    for sigma in BLUR_STEPS:
        score = float(np.mean([_ncc_max(win, _soften(t, sigma))[0] for win, t in windows]))
        if score > best_score:
            best_sigma, best_score = sigma, score
    return best_sigma


def print_check(card_rgb: np.ndarray, signed: dict[str, str]) -> PrintCheck:
    """Compare each printed value on the rectified card with what the signed payload says it should be.

    The templates are blurred to match the photo (estimated from the static labels), so a soft but genuine
    photo still matches while a changed glyph does not. Too soft a photo is "unclear", never "mismatch".
    """
    red = card_rgb[..., 0].astype(np.float32)  # the SPECIMEN watermark nearly vanishes in the red channel
    sigma = estimate_blur(red)
    out = PrintCheck(blur_sigma=sigma)
    margin, glyph_slack = 12, 4
    for name, _ in L.FIELDS:
        value = signed.get(name)
        tpl = _template(name, value) if value else None
        if tpl is None:
            continue
        if sigma > MAX_JUDGED_BLUR:
            out.fields[name] = "unclear"
            continue
        t = _soften(tpl.pixels, sigma)
        x, y = tpl.origin
        wy0, wx0 = max(0, y - margin), max(0, x - margin)
        window = red[wy0 : y + t.shape[0] + margin, wx0 : x + t.shape[1] + margin]
        best, (bx, by) = _ncc_max(window, t)
        glyph_scores: list[float] = []
        unreadable = 0
        other_digit = 0
        gap = -1.0
        for g in tpl.glyphs:
            gx0, gy0 = max(0, bx + g.x0 - glyph_slack), max(0, by - 2)
            win = window[gy0 : by + t.shape[0] + 2, gx0 : bx + g.x1 + glyph_slack]
            if win.size == 0 or float((win >= SATURATED).mean()) > GLYPH_SATURATED_MAX:
                unreadable += 1
                continue
            score, _ = _ncc_max(win, t[:, g.x0 : g.x1])
            glyph_scores.append(score)
            if g.char.isdigit():
                # Closed-set reading: does another digit explain this cell better than the signed one?
                cells = _digit_cells(tpl.size, g.left, tpl.rows, (g.x0 + tpl.x0, g.x1 + tpl.x0))
                fits = {d: _ncc_max(win, _soften(c, sigma))[0] for d, c in cells.items()}
                rival = max((d for d in fits if d != g.char), key=lambda d: fits[d])
                gap = max(gap, fits[rival] - fits[g.char])
                if fits[rival] - fits[g.char] > DIGIT_MARGIN:
                    other_digit += 1
        total = len(tpl.glyphs)
        if total == 0 or len(glyph_scores) / total < READABLE_GLYPHS_MIN:
            out.fields[name] = "unclear"
            continue
        low = min(glyph_scores)
        out.scores[name] = round(low, 3)
        if gap > -1.0:
            out.digit_gaps[name] = round(gap, 3)
        if low < GLYPH_MIN or other_digit or (unreadable == 0 and best < GLOBAL_MIN):
            out.fields[name] = "mismatch"
        else:
            out.fields[name] = "match"
    return out


def ela_check(card_ela: np.ndarray | None, card_rgb: np.ndarray) -> ElaCheck:
    """Error level over the printed text of each value, against the median of the other values on the card."""
    if card_ela is None:
        return ElaCheck(applicable=False)
    import cv2

    red = card_rgb[..., 0].astype(np.float32)
    grad = np.abs(cv2.Sobel(red, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(red, cv2.CV_32F, 0, 1))
    saturated = card_rgb.min(axis=2) >= SATURATED
    ela = card_ela.astype(np.float32)
    levels: dict[str, float] = {}
    for i, (name, _) in enumerate(L.FIELDS):
        vb = L.value_box(i)
        text = (grad[vb.y0 : vb.y1, vb.x0 : vb.x1] > 40) & ~saturated[vb.y0 : vb.y1, vb.x0 : vb.x1]
        if int(text.sum()) >= ELA_MIN_TEXT_PX:
            levels[name] = round(float(ela[vb.y0 : vb.y1, vb.x0 : vb.x1][text].mean()), 3)
    result = ElaCheck(applicable=len(levels) >= 3, levels=levels)
    if not result.applicable:
        return result
    for name, level in levels.items():
        others = [v for k, v in levels.items() if k != name]
        ref = float(np.median(others))
        if ref > 0 and level / ref >= ELA_RATIO and level - ref >= ELA_MIN_DIFF:
            result.anomalies[name] = round(level / ref, 2)
    return result
