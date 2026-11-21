"""Write the specimen cards and their test variants for every demo citizen.

    uv run python -m app.modules.docs_ai.generate --out ../data/demo_cards

For each person in `app.demo_accounts.demo_citizens()`: `card.png` (the flat card) and one JPEG photo per
variant, plus `manifest.json` (what each file is and what `check_document` should say) and `issuer_jwks.json`
(the mock issuer's public key). Deterministic: the same seed gives the same files. Fictional people only.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from app.modules.docs_ai.issuer import issuer_key, public_jwks
from app.modules.docs_ai.payload import CardFields
from app.modules.docs_ai.variants import EDITOR_SOFTWARE, EXPECTED, VARIANTS, Forgery, Shot, flat_card_png, make_variant

MAX_FILE_BYTES = 150 * 1024
NOTICE = (
    "Fictional Rahat specimen cards for a hackathon prototype. Invented people, mock 00000- numbers, "
    "SPECIMEN watermark. Not a real ID and not modelled on one."
)
# The name a forger prints on each person's card in the `altered` variant (invented).
FORGED_NAMES = ("Nasreen Akhtar", "Tariq Mehmood", "Saima Begum", "Kamran Ali")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def person_fields(person: dict[str, str]) -> CardFields:
    return CardFields(
        full_name=person["name"], national_id=person["national_id"], dob=person["dob"],
        gender=person["gender"], district=person["district"],
    )  # fmt: skip


def _demo_shot(person_index: int, variant_index: int, quality: int) -> Shot:
    angle = (-3.0, 2.0, 4.0, -1.5)[(person_index + variant_index) % 4]
    return Shot(canvas=(1120, 840), card_width=840.0, angle=angle, noise=1.2, quality=quality, seed=100 * person_index + variant_index)


def build_variant(variant: str, index: int, people: list[CardFields], variant_index: int) -> tuple[bytes, dict[str, Any]]:
    """The demo set's variant: the size cap lowers JPEG quality in steps if a file is too large."""
    key = issuer_key()
    fields = people[index]
    other = people[(index + 1) % len(people)]
    quality = 92 if variant == "altered" else 84
    while True:
        forgery = Forgery(first_quality=70, software=EDITOR_SOFTWARE) if variant == "altered" else Forgery(first_quality=85, software=None)
        result = make_variant(
            variant, fields, key, shot=_demo_shot(index, variant_index, quality), other=other,
            edit=("full_name", FORGED_NAMES[index % len(FORGED_NAMES)]), forgery=forgery,
        )  # fmt: skip
        if len(result.image) <= MAX_FILE_BYTES or quality <= 70:
            break
        quality -= 3
    info = {
        "variant": variant, "expected": EXPECTED[variant], "jpeg_quality": quality,
        "qr_claims": result.fields.as_dict(), "printed": result.printed.as_dict(),
        **{k: v for k, v in result.info.items() if k not in ("variant", "expected")},
    }  # fmt: skip
    return result.image, info


def generate(out: Path) -> list[dict[str, Any]]:
    from app.demo_accounts import demo_citizens

    citizens = demo_citizens()
    people = [person_fields(p) for p in citizens]
    out.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for index, (person, fields) in enumerate(zip(citizens, people, strict=True)):
        folder = out / slug(person["name"])
        folder.mkdir(exist_ok=True)
        png = flat_card_png(fields, issuer_key())
        (folder / "card.png").write_bytes(png)
        entries.append({"file": f"{folder.name}/card.png", "person": person["name"], "national_id": person["national_id"],
                        "variant": "flat", "expected": EXPECTED["clean"], "bytes": len(png)})  # fmt: skip
        for variant_index, variant in enumerate(VARIANTS):
            data, info = build_variant(variant, index, people, variant_index)
            (folder / f"{variant}.jpg").write_bytes(data)
            entries.append({"file": f"{folder.name}/{variant}.jpg", "person": person["name"],
                            "national_id": person["national_id"], "bytes": len(data), **info})  # fmt: skip
    key = issuer_key()
    manifest = {"notice": NOTICE, "issuer_key_id": key.key_id, "files": entries}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "issuer_jwks.json").write_text(json.dumps(public_jwks(), indent=2) + "\n", encoding="utf-8")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate fictional Rahat specimen cards and test variants.")
    parser.add_argument("--out", type=Path, default=Path("../data/demo_cards"))
    args = parser.parse_args(argv)
    entries = generate(args.out)
    largest = max(e["bytes"] for e in entries)
    print(f"wrote {len(entries)} images to {args.out} (largest {largest // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
