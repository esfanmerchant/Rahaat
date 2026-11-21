"""Simulated phone photos of specimen cards, and the test variants built from them.

Every image comes from our own renderer and invented people. A variant is made the way it would happen in
life: a forger edits an already-compressed photo (so the edited patch has a different compression history),
glare is added light, blur is a defocused lens, a crop is a card that does not fit the frame.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from app.modules.docs_ai import layout as L
from app.modules.docs_ai.card import draw_value, qr_image, render_card
from app.modules.docs_ai.issuer import IssuerKey, key_from_seed
from app.modules.docs_ai.payload import CardFields, encode

VARIANTS: tuple[str, ...] = (
    "clean", "glare", "blurry", "glare_qr", "cropped", "altered", "wrong_qr", "unknown_issuer", "bad_signature",
)  # fmt: skip

# What each variant should produce. The evaluation and the demo manifest read this.
EXPECTED: dict[str, dict[str, Any]] = {
    "clean": {"retake": None, "authenticity": "genuine"},
    "glare": {"retake": None, "authenticity": "genuine"},
    "blurry": {"retake": "blurry", "authenticity": None},
    "glare_qr": {"retake": "glare", "authenticity": None},
    "cropped": {"retake": "cropped", "authenticity": None},
    "altered": {"retake": None, "authenticity": "suspect"},
    "wrong_qr": {"retake": None, "authenticity": "suspect"},
    "unknown_issuer": {"retake": None, "authenticity": "suspect"},
    "bad_signature": {"retake": None, "authenticity": "suspect"},
}

CAMERA_SOFTWARE = "SpecimenCam 1.0 (simulated phone camera)"
EDITOR_SOFTWARE = "GIMP 2.10.38"
FORGER_SEED = "an-untrusted-key-made-by-a-forger"


@dataclass(frozen=True)
class Shot:
    """How the simulated photo is taken."""

    canvas: tuple[int, int] = (1200, 900)
    card_width: float = 900.0
    angle: float = 2.0  # degrees, counter-clockwise
    shift: tuple[float, float] = (0.0, 0.0)  # card centre offset from the canvas centre, in pixels
    tilt: float = 0.0  # perspective: the top edge is this fraction of the card width narrower
    brightness: float = 0.96
    noise: float = 2.0
    quality: int = 86
    seed: int = 0
    background: tuple[int, int, int] = (92, 80, 70)


@dataclass(frozen=True)
class Forgery:
    """How a forger touched an existing photo before re-saving it."""

    first_quality: int = 80
    software: str | None = EDITOR_SOFTWARE


@dataclass
class Variant:
    name: str
    image: bytes
    fields: CardFields  # what the QR claims
    printed: CardFields  # what is printed
    info: dict[str, Any] = field(default_factory=dict)


def card_homography(shot: Shot) -> np.ndarray:
    """3x3 matrix mapping canonical card pixels to photo pixels."""
    import cv2

    s = shot.card_width / L.CARD_W
    w, h = L.CARD_W * s, L.CARD_H * s
    inset = shot.tilt * w / 2
    local = np.array([[-w / 2 + inset, -h / 2], [w / 2 - inset, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]], dtype=np.float64)
    a = math.radians(-shot.angle)
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    centre = np.array([shot.canvas[0] / 2 + shot.shift[0], shot.canvas[1] / 2 + shot.shift[1]])
    dst = (local @ rot.T + centre).astype(np.float32)
    src = np.array([[0, 0], [L.CARD_W, 0], [L.CARD_W, L.CARD_H], [0, L.CARD_H]], dtype=np.float32)
    return cv2.getPerspectiveTransform(src, dst)


def _background(shot: Shot, rng: np.random.Generator) -> np.ndarray:
    import cv2

    w, h = shot.canvas
    coarse = rng.normal(0.0, 1.0, size=(9, 12, 1)).astype(np.float32)
    smooth = cv2.resize(coarse, (w, h), interpolation=cv2.INTER_CUBIC)[..., None]
    grain = rng.normal(0.0, 1.0, size=(h, w, 1)).astype(np.float32)
    base = np.array(shot.background, dtype=np.float32)[None, None, :]
    return np.asarray(base + 14.0 * smooth + 4.0 * grain)


def _warp(card: np.ndarray, shot: Shot, matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import cv2

    size = shot.canvas
    warped = cv2.warpPerspective(card.astype(np.float32), matrix, size, flags=cv2.INTER_AREA, borderMode=cv2.BORDER_CONSTANT)
    ones = np.ones(card.shape[:2], dtype=np.float32)
    mask = cv2.warpPerspective(ones, matrix, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return warped, mask[..., None]


def photograph(card: Image.Image, shot: Shot) -> tuple[np.ndarray, np.ndarray]:
    """Place the card on a table, light it and add sensor noise. Returns float RGB pixels and the homography."""
    import cv2

    rng = np.random.default_rng(shot.seed)
    matrix = card_homography(shot)
    warped, mask = _warp(np.asarray(card.convert("RGB")), shot, matrix)
    shadow = cv2.GaussianBlur(np.roll(mask[..., 0], (10, 8), axis=(0, 1)), (0, 0), 9)[..., None]
    bg = _background(shot, rng) * (1.0 - 0.45 * shadow)
    out = bg * (1.0 - mask) + warped * mask
    out = out * shot.brightness + rng.normal(0.0, shot.noise, size=out.shape)
    return np.clip(out, 0, 255), matrix


def to_uint8(pixels: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(pixels), 0, 255).astype(np.uint8)


def jpeg_bytes(pixels: np.ndarray, quality: int, software: str | None = CAMERA_SOFTWARE) -> bytes:
    img = Image.fromarray(to_uint8(pixels), "RGB")
    buf = io.BytesIO()
    kwargs: dict[str, Any] = {"quality": quality, "optimize": True}
    if software:
        exif = Image.Exif()
        exif[0x0131] = software  # Software
        kwargs["exif"] = exif.tobytes()
    img.save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def jpeg_roundtrip(pixels: np.ndarray, quality: int) -> np.ndarray:
    with Image.open(io.BytesIO(jpeg_bytes(pixels, quality, software=None))) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


def add_glare(pixels: np.ndarray, centre: tuple[float, float], sigma: float, strength: float = 320.0) -> np.ndarray:
    """A specular highlight: white light added with a Gaussian falloff, saturating at the core."""
    h, w = pixels.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    spot = np.exp(-((xx - centre[0]) ** 2 + (yy - centre[1]) ** 2) / (2.0 * sigma * sigma))
    return np.asarray(np.clip(pixels + strength * spot[..., None], 0, 255))


def defocus(pixels: np.ndarray, sigma: float) -> np.ndarray:
    import cv2

    return np.asarray(cv2.GaussianBlur(pixels.astype(np.float32), (0, 0), sigma))


def to_photo(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    p = matrix @ np.array([x, y, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


def _patch(base: np.ndarray, card_edit: Image.Image, box: L.Box, shot: Shot, matrix: np.ndarray, seed: int) -> np.ndarray:
    """Paste the edited card's `box` area into an existing photo, warped and lit like the rest of it."""
    rng = np.random.default_rng(seed)
    warped, mask = _warp(np.asarray(card_edit.convert("RGB")), shot, matrix)
    region = np.zeros((L.CARD_H, L.CARD_W), dtype=np.float32)
    region[box.y0 : box.y1, box.x0 : box.x1] = 1.0
    import cv2

    area = cv2.warpPerspective(region, matrix, shot.canvas, flags=cv2.INTER_LINEAR)[..., None] * mask
    patch = warped * shot.brightness + rng.normal(0.0, shot.noise, size=warped.shape)
    return np.asarray(np.clip(base * (1.0 - area) + patch * area, 0, 255))


def _replace_value(card: Image.Image, field_name: str, new_value: str) -> Image.Image:
    """Paint over one printed value with the card's background colour and print another (a crude edit)."""
    edited = card.copy()
    draw = ImageDraw.Draw(edited)
    i = L.field_index(field_name)
    vb = L.value_box(i)
    draw.rectangle((vb.x0 + 4, vb.y0 + 2, vb.x1 - 4, vb.y1 - 2), fill=L.BACKGROUND)
    draw_value(draw, i, field_name, new_value)
    return edited


def forger_key() -> IssuerKey:
    return key_from_seed(FORGER_SEED)


def tampered_payload(qr_text: str, new_dob: str) -> str:
    """Change the date of birth inside a signed payload and keep the old signature."""
    parts = qr_text.split("|")
    parts[4] = new_dob
    return "|".join(parts)


def make_variant(
    name: str,
    fields: CardFields,
    key: IssuerKey,
    *,
    shot: Shot | None = None,
    other: CardFields | None = None,
    edit: tuple[str, str] | None = None,
    forgery: Forgery | None = None,
    blur_sigma: float = 4.5,
    glare_at: tuple[float, float] = (300.0, 230.0),
    glare_sigma: float = 70.0,
    glare_strength: float = 320.0,
    crop_fraction: float = 0.24,
    crop_side: str = "right",
    forwarded_quality: int | None = None,
) -> Variant:
    """Build one variant image for one person. Deterministic for the same arguments.

    `edit` is (field, printed value) for the altered variant; by default the name is replaced.
    `forwarded_quality` re-saves a clean photo once more, the way a messaging app forwards it.
    """
    shot = shot or Shot()
    forgery = forgery or Forgery()
    qr_text = encode(fields, key)
    card = render_card(fields, qr_text, key_id=key.key_id)
    printed = fields
    info: dict[str, Any] = {"variant": name, "expected": EXPECTED[name]}

    if name in ("clean", "glare", "glare_qr", "blurry"):
        pixels, matrix = photograph(card, shot)
        if name == "glare":
            pixels = add_glare(pixels, to_photo(matrix, *glare_at), glare_sigma * shot.card_width / L.CARD_W, glare_strength)
        elif name == "glare_qr":
            qx, qy = (L.QR.x0 + L.QR.x1) / 2, (L.QR.y0 + L.QR.y1) / 2
            pixels = add_glare(pixels, to_photo(matrix, qx, qy), 90.0 * shot.card_width / L.CARD_W, strength=max(glare_strength, 380.0))
        elif name == "blurry":
            pixels = defocus(pixels, blur_sigma)
        if forwarded_quality:
            pixels = jpeg_roundtrip(pixels, shot.quality)
            image = jpeg_bytes(pixels, forwarded_quality, software=None)
        else:
            image = jpeg_bytes(pixels, shot.quality)
    elif name == "cropped":
        # Part of the card falls outside the frame.
        cut = crop_fraction * (shot.card_width if crop_side in ("left", "right") else shot.card_width / L.CARD_ASPECT)
        half_w, half_h = shot.canvas[0] / 2, shot.canvas[1] / 2
        card_half_w, card_half_h = shot.card_width / 2, shot.card_width / L.CARD_ASPECT / 2
        dx = {"right": half_w - card_half_w + cut, "left": -(half_w - card_half_w + cut)}.get(crop_side, 0.0)
        dy = {"bottom": half_h - card_half_h + cut, "top": -(half_h - card_half_h + cut)}.get(crop_side, 0.0)
        pixels, _ = photograph(card, replace(shot, shift=(dx, dy)))
        image = jpeg_bytes(pixels, shot.quality)
        info["crop_side"] = crop_side
    elif name in ("altered", "wrong_qr"):
        if name == "altered":
            field_name, new_value = edit or ("full_name", "Nasreen Akhtar")
            values = fields.as_dict()
            values[field_name] = new_value
            printed = CardFields(**values)
            edited = _replace_value(card, field_name, new_value)
            box = L.value_box(L.field_index(field_name))
            info["edited_region"] = field_name
        else:
            if other is None:
                raise ValueError("wrong_qr needs another person's fields")
            edited = card.copy()
            edited.paste(qr_image(encode(other, key)), (L.QR.x0, L.QR.y0))
            fields = other  # the QR now speaks for the other person
            box = L.QR
            info["edited_region"] = "qr"
        original, matrix = photograph(card, shot)
        first = jpeg_roundtrip(original, forgery.first_quality)
        pixels = _patch(first, edited, box, shot, matrix, seed=shot.seed + 7)
        image = jpeg_bytes(pixels, shot.quality, software=forgery.software)
        info["editor_metadata"] = forgery.software
        info["first_quality"] = forgery.first_quality
    elif name == "unknown_issuer":
        rogue = forger_key()
        qr_text = encode(fields, rogue)
        pixels, _ = photograph(render_card(fields, qr_text, key_id=rogue.key_id), shot)
        image = jpeg_bytes(pixels, shot.quality)
    elif name == "bad_signature":
        new_dob = f"{int(fields.dob[:4]) + 9}{fields.dob[4:]}"
        printed = CardFields(fields.full_name, fields.national_id, new_dob, fields.gender, fields.district)
        qr_text = tampered_payload(qr_text, new_dob)
        pixels, _ = photograph(render_card(printed, qr_text, key_id=key.key_id), shot)
        image = jpeg_bytes(pixels, shot.quality)
        fields = printed
    else:
        raise ValueError(f"unknown variant {name}")
    return Variant(name=name, image=image, fields=fields, printed=printed, info=info)


def flat_card_png(fields: CardFields, key: IssuerKey) -> bytes:
    """The card itself, as a lossless image (what a printer would get)."""
    buf = io.BytesIO()
    render_card(fields, encode(fields, key), key_id=key.key_id).save(buf, "PNG", optimize=True)
    return buf.getvalue()
