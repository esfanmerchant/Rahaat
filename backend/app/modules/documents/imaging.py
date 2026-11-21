"""Upload safety for images. Pure functions over bytes; no filesystem, no database.

* The type is decided by magic bytes (JPEG, PNG, WebP), never by the filename or the Content-Type header,
  and the decoder must agree with the magic bytes.
* Bytes and pixels are capped before anything is decoded, so a decompression bomb is refused from its header.
* The stored copy is re-encoded from raw pixels, so EXIF (GPS, device), ICC profiles and text chunks are gone.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

MAX_BYTES: Final = 5 * 1024 * 1024
MAX_PIXELS: Final = 12_000_000  # a 12 MP phone photo; decoding stays near 40 MB
STORED_MAX_SIDE: Final = 2400  # the stored copy officers view; checks run on the original
MAX_SIDE: Final = 10_000

_MIME: Final = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_EXT: Final = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}
_PIL_FORMAT: Final = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


class UnsupportedMediaType(AppError):
    status, code, title = 415, "unsupported_file_type", "Send a photo (JPEG, PNG or WebP)"


class PayloadTooLarge(AppError):
    status, code, title = 413, "file_too_large", "That photo is too large"


class UnreadableImage(AppError):
    status, code, title = 422, "unreadable_image", "We could not open that photo"


def sniff(data: bytes) -> str | None:
    """The image type from the first bytes, or None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@dataclass(frozen=True, slots=True)
class Inspected:
    kind: str  # jpeg | png | webp
    width: int
    height: int
    image: Image.Image

    @property
    def mime(self) -> str:
        return _MIME[self.kind]


def check_size(size: int) -> None:
    if size > MAX_BYTES:
        raise PayloadTooLarge(f"The limit is {MAX_BYTES // (1024 * 1024)} MB. Take the photo again a little further away.")
    if size == 0:
        raise UnreadableImage("The file is empty.", code="empty_file")


def inspect(data: bytes) -> Inspected:
    """Validate an upload and decode it, or raise a problem with a stable code."""
    check_size(len(data))
    kind = sniff(data)
    if kind is None:
        raise UnsupportedMediaType("Only JPEG, PNG or WebP photos are accepted.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            image = Image.open(io.BytesIO(data))  # reads the header only
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise PayloadTooLarge("That photo has too many pixels.", code="image_too_many_pixels") from exc
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
            raise UnreadableImage("The photo is damaged. Take it again.") from exc
        if (image.format or "").upper() != _PIL_FORMAT[kind]:
            raise UnsupportedMediaType("The file content does not match a photo type we accept.", code="type_mismatch")
        width, height = image.size
        if width <= 0 or height <= 0 or width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
            raise PayloadTooLarge("That photo has too many pixels.", code="image_too_many_pixels")
        try:
            image.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise PayloadTooLarge("That photo has too many pixels.", code="image_too_many_pixels") from exc
        except (OSError, ValueError, SyntaxError, MemoryError) as exc:
            raise UnreadableImage("The photo is damaged. Take it again.") from exc
    return Inspected(kind=kind, width=width, height=height, image=image)


def reencode(inspected: Inspected) -> tuple[bytes, str, str, int, int]:
    """A clean copy: orientation applied, then rebuilt from raw pixels and saved without any metadata.

    Returns (bytes, extension, mime, width, height).
    """
    image = inspected.image
    try:
        image = ImageOps.exif_transpose(image) or image
    except Exception:  # noqa: BLE001  (a broken orientation tag must not block the upload)
        image = inspected.image
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    mode = "RGBA" if has_alpha and inspected.kind in ("png", "webp") else "RGB"
    pixels = image.convert(mode)
    pixels.thumbnail((STORED_MAX_SIDE, STORED_MAX_SIDE))  # in place, only ever smaller
    clean = Image.frombytes(mode, pixels.size, pixels.tobytes())  # no info dict: EXIF, ICC and text are gone
    out = io.BytesIO()
    if inspected.kind == "jpeg":
        clean.save(out, format="JPEG", quality=90)
    elif inspected.kind == "png":
        clean.save(out, format="PNG", compress_level=6)
    else:
        clean.save(out, format="WEBP", quality=90)
    return out.getvalue(), _EXT[inspected.kind], _MIME[inspected.kind], clean.width, clean.height
