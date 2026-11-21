"""Draws the fictional Rahat specimen card with Pillow.

Every card says SPECIMEN (a large diagonal watermark and a badge), says it is not a real ID, and carries only
mock data. The QR holds the signed payload from `payload.encode`.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from app.modules.docs_ai import layout as L
from app.modules.docs_ai.payload import CardFields


def qr_image(text: str) -> Image.Image:
    """The QR as a white square of `layout.QR` size, modules drawn at an integer scale with a 4-module quiet zone."""
    import segno

    code = segno.make(text, error="m", micro=False)
    matrix = [list(row) for row in code.matrix]
    modules = len(matrix) + 8
    scale = max(1, L.QR_MAX_PX // modules)
    side = modules * scale
    img = Image.new("L", (L.QR.w, L.QR.h), 255)
    draw = ImageDraw.Draw(img)
    off_x = (L.QR.w - side) // 2 + 4 * scale
    off_y = (L.QR.h - side) // 2 + 4 * scale
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                x, y = off_x + c * scale, off_y + r * scale
                draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=0)
    return img.convert("RGB")


def _watermark() -> Image.Image:
    """A large diagonal SPECIMEN between the photo and the QR. Its red barely shows in the red channel, which
    the checker reads text from, so the watermark stays clearly visible without hiding the printed values."""
    layer = Image.new("RGBA", (760, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((layer.width / 2, layer.height / 2), "SPECIMEN", font=L.font(128), fill=L.WATERMARK_FILL, anchor="mm")
    return layer.rotate(16, resample=Image.Resampling.BICUBIC, expand=True)


def draw_value(draw: ImageDraw.ImageDraw, index: int, field: str, value: str, fill: tuple[int, int, int] = L.VALUE_FILL) -> None:
    text = L.display_value(field, value)
    draw.text((L.FIELD_X, L.row_top(index) + L.VALUE_DY), text, font=L.font(L.value_font_size(text)), fill=fill)


def render_card(fields: CardFields, qr_text: str, *, key_id: str, printed: CardFields | None = None) -> Image.Image:
    """Render a card. `printed` overrides what is printed (used only to make forged test variants)."""
    shown = printed or fields
    card = Image.new("RGB", (L.CARD_W, L.CARD_H), L.BACKGROUND)
    draw = ImageDraw.Draw(card)
    for x in range(-L.CARD_H, L.CARD_W, 14):  # fine diagonal guilloche-like lines
        draw.line((x, L.CARD_H, x + L.CARD_H, 0), fill=L.BACKGROUND_LINE, width=1)

    wm = _watermark()
    card.paste(wm, (L.WATERMARK_CENTER[0] - wm.width // 2, L.WATERMARK_CENTER[1] - wm.height // 2), wm)
    draw = ImageDraw.Draw(card)

    draw.rectangle(L.HEADER.as_tuple(), fill=L.HEADER_FILL)
    draw.text((36, 16), "RAHAT CARD", font=L.font(44), fill=L.HEADER_TEXT)
    draw.text((38, 70), "PROTOTYPE  -  MOCK RELIEF PROGRAMME", font=L.font(18), fill=L.HEADER_TEXT)
    draw.rectangle(L.BADGE.as_tuple(), fill=L.BADGE_FILL)
    draw.text(((L.BADGE.x0 + L.BADGE.x1) / 2, (L.BADGE.y0 + L.BADGE.y1) / 2), "SPECIMEN", font=L.font(30), fill=L.HEADER_TEXT, anchor="mm")

    p = L.PORTRAIT
    draw.rounded_rectangle(p.as_tuple(), radius=12, fill=(226, 224, 214), outline=(180, 182, 172), width=2)
    cx = (p.x0 + p.x1) // 2
    draw.ellipse((cx - 44, p.y0 + 46, cx + 44, p.y0 + 134), fill=(170, 172, 164))
    draw.rounded_rectangle((cx - 78, p.y0 + 150, cx + 78, p.y1 - 14), radius=40, fill=(170, 172, 164))
    draw.text((cx, p.y1 + 18), "NO PHOTO", font=L.font(16), fill=L.LABEL_FILL, anchor="mm")

    values = shown.as_dict()
    for i, (key, label) in enumerate(L.FIELDS):
        draw.text((L.FIELD_X, L.row_top(i)), label, font=L.font(L.LABEL_SIZE), fill=L.LABEL_FILL)
        draw_value(draw, i, key, values[key])

    card.paste(qr_image(qr_text), (L.QR.x0, L.QR.y0))
    draw.text(((L.QR.x0 + L.QR.x1) / 2, L.QR.y1 + 16), "SCAN TO VERIFY (MOCK ISSUER)", font=L.font(15), fill=L.LABEL_FILL, anchor="mm")
    draw.text(((L.QR.x0 + L.QR.x1) / 2, L.QR.y1 + 36), f"KEY {key_id}", font=L.font(14), fill=L.LABEL_FILL, anchor="mm")

    draw.rectangle(L.FOOTER.as_tuple(), fill=L.FOOTER_FILL)
    draw.text((36, L.FOOTER.y0 + 12), "NOT A REAL ID  -  PROTOTYPE FOR A HACKATHON DEMO  -  MOCK DATA ONLY", font=L.font(18), fill=L.FOOTER_TEXT)
    small = "Rahat specimen card, fictional layout v1. Numbers starting 00000- are not real."
    draw.text((36, L.FOOTER.y0 + 40), small, font=L.font(14), fill=L.FOOTER_TEXT)
    draw.rectangle((0, 0, L.CARD_W - 1, L.CARD_H - 1), outline=L.BORDER_FILL, width=2)
    return card
