"""Bounded image decoding and metadata reading for uploaded documents.

Uploads are untrusted. We refuse oversized or odd inputs before decoding pixels, decode large JPEGs at a reduced
scale, cap the working size, and read only a few metadata strings (as data, cleaned and truncated).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS_JPEG = 64_000_000  # JPEGs decode at reduced scale, so large camera files stay cheap
MAX_PIXELS_OTHER = 16_000_000
MIN_SIDE = 64
WORK_MAX_SIDE = 1600
ELA_MAX_PIXELS = 14_000_000
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})

_EDITORS = re.compile(
    r"photoshop|gimp|paint\.net|pixlr|canva|affinity|krita|picsart|snapseed|lightroom|photopea|fotor|paintshop|"
    r"corel|befunky|polarr|inkscape|pixelmator|acorn",
    re.IGNORECASE,
)
_XMP_TOOL = re.compile(rb"(?:CreatorTool|softwareAgent)[^>]{0,8}>?\s*=?\s*\"?([^<\"]{1,80})", re.IGNORECASE)
_PRINTABLE = re.compile(r"[^\x20-\x7e]")

_ORIENTATION_OPS = {2: "FLIP_LEFT_RIGHT", 3: "ROTATE_180", 4: "FLIP_TOP_BOTTOM", 5: "TRANSPOSE", 6: "ROTATE_270", 7: "TRANSVERSE", 8: "ROTATE_90"}


class DecodeError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class Decoded:
    rgb: np.ndarray  # working copy, uint8 RGB, longest side at most WORK_MAX_SIDE, upright
    format: str
    original_size: tuple[int, int]
    software: list[str] = field(default_factory=list)  # cleaned metadata strings that name software
    editors: list[str] = field(default_factory=list)  # the subset that names an image editor
    ela: np.ndarray | None = None  # error-level map at working size (JPEG only), uint8


def _clean(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return _PRINTABLE.sub("", str(value)).strip()[:80]


def _software_strings(im: Any) -> list[str]:
    found: list[str] = []
    try:
        exif = im.getexif()
        for tag in (0x0131, 0x000B):  # Software, ProcessingSoftware
            if tag in exif:
                found.append(_clean(exif[tag]))
    except Exception:  # noqa: BLE001, S110 - unreadable metadata is not an error
        pass
    info = getattr(im, "info", {}) or {}
    for key in ("Software", "software"):
        if key in info:
            found.append(_clean(info[key]))
    xmp = info.get("xmp") or info.get("XML:com.adobe.xmp")
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8", errors="replace")
    if isinstance(xmp, bytes):
        found.extend(_clean(m.group(1)) for m in _XMP_TOOL.finditer(xmp[:65536]))
    if "photoshop" in info:
        found.append("Photoshop resource block (APP13)")
    return [s for s in dict.fromkeys(found) if s]


def _upright(arr: np.ndarray, orientation: int) -> np.ndarray:
    op = _ORIENTATION_OPS.get(orientation)
    if op is None:
        return arr
    from PIL import Image

    img = Image.fromarray(arr)
    return np.asarray(img.transpose(getattr(Image.Transpose, op)))


def _error_levels(rgb: np.ndarray, quality: int = 90) -> np.ndarray:
    """Per-pixel difference between the image and itself re-saved as JPEG. Must run on the original pixel grid."""
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=quality)
    with Image.open(io.BytesIO(buf.getvalue())) as again:
        resaved = np.asarray(again.convert("RGB"), dtype=np.int16)
    return np.abs(rgb.astype(np.int16) - resaved).max(axis=2).astype(np.uint8)


def _shrink(arr: np.ndarray, max_side: int) -> np.ndarray:
    import cv2

    h, w = arr.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1.0:
        return arr
    return np.asarray(cv2.resize(arr, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA))


def decode(data: bytes) -> Decoded:
    """Decode an upload into a bounded working image. Raises DecodeError, never anything else."""
    if not data:
        raise DecodeError("image_empty", "no bytes were uploaded")
    if len(data) > MAX_BYTES:
        raise DecodeError("image_too_large", f"upload is {len(data)} bytes, over the {MAX_BYTES} byte limit")
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data), formats=sorted(ALLOWED_FORMATS)) as im:  # no exotic decoders on uploads
            fmt = (im.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise DecodeError("image_format", f"format {fmt or 'unknown'} is not accepted")
            w, h = im.size
            limit = MAX_PIXELS_JPEG if fmt == "JPEG" else MAX_PIXELS_OTHER
            if w * h > limit:
                raise DecodeError("image_too_large", f"image is {w}x{h} pixels, over the {limit} pixel limit")
            if min(w, h) < MIN_SIDE:
                raise DecodeError("image_too_small", f"image is {w}x{h} pixels")
            software = _software_strings(im)
            try:
                orientation = int(im.getexif().get(0x0112, 1))
            except Exception:  # noqa: BLE001
                orientation = 1
            ela_ok = fmt == "JPEG" and w * h <= ELA_MAX_PIXELS
            if fmt == "JPEG" and not ela_ok:
                im.draft("RGB", (w // 4, h // 4))  # DCT-domain downscale: cheap and bounded
            rgb = np.asarray(im.convert("RGB"))
    except DecodeError:
        raise
    except Image.DecompressionBombError:
        raise DecodeError("image_too_large", "image dimensions exceed the decoder's safety limit") from None
    except Exception as exc:  # noqa: BLE001 - any decoder failure is a bad upload, not a crash
        raise DecodeError("image_undecodable", f"the image could not be decoded ({type(exc).__name__})") from None

    ela = _upright(_error_levels(rgb), orientation) if ela_ok else None
    rgb = _upright(rgb, orientation)
    work = _shrink(rgb, WORK_MAX_SIDE)
    if ela is not None and ela.shape[:2] != work.shape[:2]:
        import cv2

        ela = np.asarray(cv2.resize(ela, (work.shape[1], work.shape[0]), interpolation=cv2.INTER_AREA))
    editors = [s for s in software if _EDITORS.search(s)]
    return Decoded(rgb=np.ascontiguousarray(work), format=fmt, original_size=(w, h), software=software, editors=editors, ela=ela)
