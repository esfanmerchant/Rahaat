"""DB-free upload safety tests: magic bytes, caps, decompression bombs, metadata stripping, the citizen view."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from app.contracts.decision import TypedDecision
from app.contracts.documents import DocumentCheck, DocumentSignal, QrResult
from app.modules.documents import imaging, views


def jpeg_with_exif(size: tuple[int, int] = (64, 40)) -> bytes:
    image = Image.new("RGB", size, (200, 120, 40))
    exif = Image.Exif()
    exif[0x010F] = "SpyCam Inc"  # Make
    exif[0x0131] = "EditorPro 9"  # Software
    exif[0x8825] = {2: (24.0, 51.0, 36.0)}  # GPS IFD with a latitude
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


def png(size: tuple[int, int], mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size).save(out, format="PNG")
    return out.getvalue()


def png_header_only(width: int, height: int) -> bytes:
    """A tiny file that claims huge dimensions: the classic decompression bomb."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 64)) + chunk(b"IEND", b"")


def test_magic_bytes_decide_the_type() -> None:
    assert imaging.sniff(jpeg_with_exif()) == "jpeg"
    assert imaging.sniff(png((4, 4))) == "png"
    webp = io.BytesIO()
    Image.new("RGB", (8, 8)).save(webp, format="WEBP")
    assert imaging.sniff(webp.getvalue()) == "webp"
    assert imaging.sniff(b"<?php system($_GET['c']); ?>") is None
    assert imaging.sniff(b"GIF89a....") is None


@pytest.mark.parametrize("payload", [b"<?php echo 1; ?>", b"%PDF-1.7\n", b"GIF89a\x01\x00\x01\x00", b"<svg onload=alert(1)>"])
def test_non_images_are_refused_with_415(payload: bytes) -> None:
    with pytest.raises(imaging.UnsupportedMediaType) as err:
        imaging.inspect(payload)
    assert err.value.status == 415


def test_magic_bytes_followed_by_garbage_is_unreadable() -> None:
    with pytest.raises(imaging.UnreadableImage):
        imaging.inspect(b"\x89PNG\r\n\x1a\n" + b"not really a png" * 10)


def test_size_cap() -> None:
    with pytest.raises(imaging.PayloadTooLarge) as err:
        imaging.inspect(b"\xff\xd8\xff" + b"\x00" * imaging.MAX_BYTES)
    assert err.value.status == 413
    with pytest.raises(imaging.UnreadableImage):
        imaging.inspect(b"")


def test_decompression_bombs_are_refused_from_the_header() -> None:
    bomb = png_header_only(60_000, 60_000)
    assert len(bomb) < 200
    with pytest.raises(imaging.PayloadTooLarge) as err:
        imaging.inspect(bomb)
    assert err.value.code == "image_too_many_pixels"
    # Under Pillow's own limit but over ours, and a real, decodable file.
    with pytest.raises(imaging.PayloadTooLarge):
        imaging.inspect(png((6000, 6000), mode="1"))
    with pytest.raises(imaging.PayloadTooLarge):
        imaging.inspect(png((imaging.MAX_SIDE + 1, 2), mode="1"))


def test_reencode_strips_exif_and_keeps_pixels() -> None:
    original = jpeg_with_exif()
    assert Image.open(io.BytesIO(original)).getexif(), "the fixture must carry EXIF"
    clean, ext, mime, width, height = imaging.reencode(imaging.inspect(original))
    assert (ext, mime, width, height) == (".jpg", "image/jpeg", 64, 40)
    reopened = Image.open(io.BytesIO(clean))
    assert not reopened.getexif() and "exif" not in reopened.info and "icc_profile" not in reopened.info
    assert b"SpyCam" not in clean and b"EditorPro" not in clean
    r, g, b = reopened.convert("RGB").getpixel((10, 10))  # type: ignore[misc]
    assert abs(r - 200) < 10 and abs(g - 120) < 10 and abs(b - 40) < 10


def test_reencode_keeps_png_transparency_and_drops_text_chunks() -> None:
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret location")
    out = io.BytesIO()
    Image.new("RGBA", (10, 10), (1, 2, 3, 0)).save(out, format="PNG", pnginfo=info)
    clean, ext, mime, *_ = imaging.reencode(imaging.inspect(out.getvalue()))
    assert ext == ".png" and b"secret location" not in clean and Image.open(io.BytesIO(clean)).mode == "RGBA"


# --- citizen view ------------------------------------------------------------------------------------


def _check(quality: str = "ok", *, genuine: bool = True, qr_valid: bool | None = None, abstain: bool = False) -> DocumentCheck:
    authenticity: TypedDecision[str] = (
        TypedDecision(choice=None, confidence=0.4, route="human", abstained=True, model_version="t")
        if abstain
        else TypedDecision(choice="genuine" if genuine else "suspect", confidence=0.95, route="auto" if genuine else "human", model_version="t")
    )
    return DocumentCheck(
        document_id="d1", kind="rahat_id", quality=quality,  # type: ignore[arg-type]
        qr=QrResult(found=qr_valid is not None, signature_valid=qr_valid, payload={"name": "Zainab Bibi"} if qr_valid else None),
        authenticity=authenticity,  # type: ignore[arg-type]
        signals=[DocumentSignal(code="ela_anomaly", weight=1.2, staff_detail="edited region near the name")], model_version="t",
    )  # fmt: skip


def test_citizen_view_hides_detection_details() -> None:
    suspect = views.citizen_view("d1", "rahat_id", _check(genuine=False))
    assert suspect.accepted and suspect.message_key == "doc_person_will_check"
    dumped = suspect.model_dump_json()
    assert "ela_anomaly" not in dumped and "edited region" not in dumped and "signals" not in dumped


def test_citizen_view_outcomes() -> None:
    assert views.citizen_view("d1", "rahat_id", _check()).message_key == "doc_ok"
    blurry = views.citizen_view("d1", "rahat_id", _check("blurry"))
    assert not blurry.accepted and blurry.message_key == "doc_retake_blurry" and blurry.retake_hint
    glare_signed = views.citizen_view("d1", "rahat_id", _check("glare", qr_valid=True))
    assert glare_signed.accepted, "glare with a valid signed QR is not blocked"
    assert views.citizen_view("d1", "rahat_id", _check(abstain=True)).message_key == "doc_person_will_check"
    assert views.citizen_view("d1", "rahat_id", None).message_key == "doc_person_will_check"
    mismatch = views.citizen_view("d1", "rahat_id", _check(qr_valid=True), identity_mismatch=True)
    assert mismatch.message_key == "doc_person_will_check"
    assert views.document_status(_check(qr_valid=True), identity_mismatch=True) == "mismatch"
