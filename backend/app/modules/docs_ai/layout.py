"""Geometry of the fictional Rahat specimen card, layout version 1 (payload version RC1).

The renderer draws from these numbers and the checker reads with them, so both always agree. The layout is
our own: a header band, a photo placeholder, five labelled rows and a QR on the right. It copies no real card.
All coordinates are pixels on the canonical 1000 x 630 card (about the ID-1 aspect ratio).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PIL import ImageFont

CARD_W = 1000
CARD_H = 630
CARD_ASPECT = CARD_W / CARD_H

BACKGROUND = (246, 243, 234)
BACKGROUND_LINE = (236, 234, 220)
HEADER_FILL = (28, 92, 74)
HEADER_TEXT = (250, 250, 244)
BADGE_FILL = (196, 38, 38)
LABEL_FILL = (104, 108, 100)
VALUE_FILL = (18, 22, 20)
FOOTER_FILL = (218, 231, 220)
FOOTER_TEXT = (28, 72, 58)
WATERMARK_FILL = (205, 45, 45, 70)
BORDER_FILL = (150, 160, 150)


@dataclass(frozen=True)
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1, self.y1)


HEADER = Box(0, 0, CARD_W, 104)
FOOTER = Box(0, 556, CARD_W, CARD_H)
BADGE = Box(770, 28, 966, 78)
PORTRAIT = Box(36, 132, 236, 392)
QR = Box(712, 118, 972, 378)
QR_MAX_PX = QR.w
WATERMARK_CENTER = (372, 330)

FIELD_X = 266
FIELD_MAX_W = 690 - FIELD_X
ROW_TOP = 126
ROW_PITCH = 76
LABEL_SIZE = 17
VALUE_SIZE = 30
VALUE_MIN_SIZE = 18
VALUE_DY = 22  # value baseline box starts this far below the label

# Field order on the card, the label printed above each value, and the key used in payloads and forms.
FIELDS: tuple[tuple[str, str], ...] = (
    ("full_name", "NAME"),
    ("national_id", "MOCK ID NO."),
    ("dob", "DATE OF BIRTH"),
    ("gender", "GENDER"),
    ("district", "DISTRICT"),
)


def row_top(index: int) -> int:
    return ROW_TOP + index * ROW_PITCH


def label_box(index: int) -> Box:
    y = row_top(index)
    return Box(FIELD_X, y, FIELD_X + 200, y + 20)


def value_box(index: int) -> Box:
    """Where a value is printed: generous enough for the largest font size and for small misalignment."""
    y = row_top(index) + VALUE_DY
    return Box(FIELD_X - 6, y - 4, FIELD_X + FIELD_MAX_W + 6, y + 40)


def field_index(name: str) -> int:
    for i, (key, _) in enumerate(FIELDS):
        if key == name:
            return i
    raise KeyError(name)


@lru_cache(maxsize=64)
def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Pillow's bundled font, scaled. No font files ship with the repo."""
    return ImageFont.load_default(size=size)


def text_width(text: str, size: int) -> float:
    return float(font(size).getlength(text))


def value_font_size(text: str) -> int:
    """The printed size for a value: the default size, shrunk until it fits the row."""
    size = VALUE_SIZE
    while size > VALUE_MIN_SIZE and text_width(text, size) > FIELD_MAX_W:
        size -= 1
    return size


def display_value(field: str, value: str) -> str:
    """How a payload value is printed on the card."""
    if field == "gender":
        return {"female": "FEMALE", "male": "MALE", "other": "OTHER"}.get(value, value.upper())
    return value


def glare_exclusions() -> tuple[Box, ...]:
    """Areas that are white by design (header text, QR modules), so saturated pixels there are not glare."""
    return (HEADER, QR, BADGE)
