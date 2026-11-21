"""Evaluate check_document on generated specimen photos.

    uv run python -m app.modules.docs_ai.evaluate [--people 24] [--seed 2026] [--json out.json]

The demo citizens plus invented people (seeded), each photographed under random conditions (angle, distance,
light, noise, JPEG quality, background), in every variant. Forgery parameters vary too: the first compression
of the photo the forger edited, the quality they saved at, and whether their editor wrote its name into the
metadata. Numbers are printed as measured.

Limits of this evaluation: every image comes from our own renderer and photo simulator, and the thresholds
were set while looking at generated images. It shows the logic works on in-distribution synthetic data; it is
not evidence about real phone photos of real cards (there are none in this project).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.mockdata import make_mock_id
from app.modules.docs_ai import layout as L
from app.modules.docs_ai.issuer import issuer_key
from app.modules.docs_ai.payload import CardFields
from app.modules.docs_ai.service import check_document
from app.modules.docs_ai.variants import EDITOR_SOFTWARE, Forgery, Shot, flat_card_png, make_variant

# Invented name parts and places; combinations are random and belong to no one.
FIRST_F = ("Amna", "Bushra", "Farzana", "Hina", "Kiran", "Mehwish", "Nadia", "Rabia", "Sadia", "Tahira", "Uzma", "Shazia")
FIRST_M = ("Bilal", "Danish", "Fahad", "Hamza", "Junaid", "Kamran", "Naveed", "Owais", "Qasim", "Rizwan", "Usman", "Waqar")
LAST = ("Abbasi", "Baloch", "Chandio", "Jatoi", "Khoso", "Laghari", "Memon", "Narejo", "Qureshi", "Rajput", "Talpur", "Unar")
DISTRICTS = ("Karachi East", "Karachi West", "Hyderabad", "Sukkur", "Larkana", "Thatta", "Badin", "Lahore", "Multan", "Jamshoro")

GENUINE = ("clean", "flat", "clean_glare", "clean_forwarded")
QUALITY = {"blurry": "blurry", "glare_qr": "glare", "cropped": "cropped"}
FORGED = ("altered_name", "altered_digit", "wrong_qr", "unknown_issuer", "bad_signature")
OCR_SIGNALS = ("ocr_qr_mismatch", "ocr_matches_qr")
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])


@dataclass
class Row:
    person: int
    variant: str
    quality: str
    retake: str | None
    choice: str | None
    route: str
    signals: list[str]
    seconds: float
    params: dict[str, Any]


def invented_people(n: int, rng: random.Random) -> list[CardFields]:
    from app.demo_accounts import demo_citizens

    people = [
        CardFields(p["name"], p["national_id"], p["dob"], p["gender"], p["district"])  # fmt: skip
        for p in demo_citizens()
    ][:n]
    serial = 3_000_000
    while len(people) < n:
        female = rng.random() < 0.5
        name = f"{rng.choice(FIRST_F if female else FIRST_M)} {rng.choice(LAST)}"
        dob = f"{rng.randint(1950, 2004)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        people.append(CardFields(name, make_mock_id(serial + len(people)), dob, "female" if female else "male", rng.choice(DISTRICTS)))
    return people


def random_shot(rng: random.Random, seed: int) -> Shot:
    """A random but well-framed photo: the whole card is inside the frame (crops are made on purpose elsewhere)."""
    canvas = rng.choice(((1200, 900), (1120, 840), (1600, 1200), (1000, 750)))
    angle = rng.uniform(-10, 10) + (180.0 if rng.random() < 0.1 else 0.0)
    shade = rng.randint(45, 160) if rng.random() < 0.8 else rng.randint(160, 235)  # one in five on a light table
    c, s = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
    fits = min(0.93 * canvas[0] / (c + s / L.CARD_ASPECT), 0.93 * canvas[1] / (s + c / L.CARD_ASPECT))
    return Shot(
        canvas=canvas,
        card_width=min(rng.uniform(0.55, 0.88) * canvas[0], fits),
        angle=angle,
        tilt=rng.uniform(0.0, 0.06),
        brightness=rng.uniform(0.85, 1.0),
        noise=rng.uniform(0.8, 2.5),
        quality=rng.randint(72, 94),
        seed=seed,
        background=(shade + rng.randint(0, 25), shade + rng.randint(-5, 15), shade - rng.randint(0, 20)),
    )


def _other_digit(national_id: str, rng: random.Random) -> str:
    body = national_id[6:13]
    pos = rng.randrange(7)
    digit = str((int(body[pos]) + rng.randint(1, 9)) % 10)
    return make_mock_id(int(body[:pos] + digit + body[pos + 1 :]))


def build(variant: str, i: int, people: list[CardFields], rng: random.Random) -> tuple[bytes, dict[str, Any]]:
    key = issuer_key()
    me, other = people[i], people[(i + 1) % len(people)]
    shot = random_shot(rng, seed=rng.randrange(1 << 30))
    params: dict[str, Any] = {"card_width": round(shot.card_width), "angle": round(shot.angle, 1), "jpeg": shot.quality}
    if variant == "flat":
        return flat_card_png(me, key), params
    if variant == "clean":
        return make_variant("clean", me, key, shot=shot).image, params
    if variant == "clean_glare":
        at = (rng.uniform(60, 640), rng.uniform(150, 530))
        strength, sigma = rng.uniform(240, 360), rng.uniform(45, 90)
        params |= {"glare_at": [round(at[0]), round(at[1])], "glare_strength": round(strength)}
        return make_variant("glare", me, key, shot=shot, glare_at=at, glare_sigma=sigma, glare_strength=strength).image, params
    if variant == "clean_forwarded":
        fq = rng.randint(55, 80)
        params["forwarded_quality"] = fq
        return make_variant("clean", me, key, shot=shot, forwarded_quality=fq).image, params
    if variant == "blurry":
        sigma = rng.uniform(1.8, 5.0)
        params["blur_sigma"] = round(sigma, 2)
        return make_variant("blurry", me, key, shot=shot, blur_sigma=sigma).image, params
    if variant == "glare_qr":
        return make_variant("glare_qr", me, key, shot=shot).image, params
    if variant == "cropped":
        side, frac = rng.choice(("right", "left", "top", "bottom")), rng.uniform(0.15, 0.4)
        params |= {"crop_side": side, "crop_fraction": round(frac, 2)}
        return make_variant("cropped", me, key, shot=shot, crop_side=side, crop_fraction=frac).image, params
    if variant in ("altered_name", "altered_digit", "wrong_qr"):
        forgery = Forgery(first_quality=rng.randint(60, 92), software=EDITOR_SOFTWARE if rng.random() < 0.5 else None)
        final = rng.randint(80, 95)
        shot = Shot(**{**shot.__dict__, "quality": final})
        params |= {"first_quality": forgery.first_quality, "jpeg": final, "editor_metadata": bool(forgery.software)}
        if variant == "wrong_qr":
            return make_variant("wrong_qr", me, key, shot=shot, other=other, forgery=forgery).image, params
        if variant == "altered_name":
            edit = ("full_name", other.full_name if other.full_name != me.full_name else "Nasreen Akhtar")
        elif rng.random() < 0.5:
            edit = ("national_id", _other_digit(me.national_id, rng))
        else:
            edit = ("dob", f"{int(me.dob[:4]) + rng.choice((-10, -5, 5, 10))}{me.dob[4:]}")
        params["edited"] = edit[0]
        return make_variant("altered", me, key, shot=shot, edit=edit, forgery=forgery).image, params
    return make_variant(variant, me, key, shot=shot).image, params


def case_rng(seed: int, person: int, variant: str) -> random.Random:
    """Each (person, variant) has its own random stream, so one case can be rebuilt on its own."""
    return random.Random(f"{seed}:{person}:{variant}")


def run(people_count: int, seed: int, dump: Path | None = None) -> list[Row]:
    people = invented_people(people_count, random.Random(seed))
    check_document(flat_card_png(people[0], issuer_key()), "rahat_id", document_id="warmup")
    rows: list[Row] = []
    for i in range(len(people)):
        for variant in (*GENUINE, *QUALITY, *FORGED):
            data, params = build(variant, i, people, case_rng(seed, i, variant))
            started = time.perf_counter()
            check = check_document(data, "rahat_id", document_id=f"eval-{i}-{variant}")
            elapsed = time.perf_counter() - started
            a = check.authenticity
            row = Row(i, variant, check.quality, check.retake_hint, a.choice, a.route, [s.code for s in check.signals], elapsed, params)
            rows.append(row)
            if dump is not None and _is_miss(row):
                dump.mkdir(parents=True, exist_ok=True)
                suffix = "png" if data.startswith(PNG_MAGIC) else "jpg"
                (dump / f"{seed}-{i}-{variant}.{suffix}").write_bytes(data)
    return rows


def _is_miss(r: Row) -> bool:
    if r.variant in FORGED:
        return r.choice != "suspect"
    if r.variant in GENUINE:
        return r.choice == "suspect" or r.retake is not None
    return r.retake is None or r.quality != QUALITY[r.variant]


def pct(n: int, d: int) -> str:
    return f"{n}/{d} = {100.0 * n / d:5.1f}%" if d else "n/a"


def report(rows: list[Row], ocr_available: bool) -> dict[str, Any]:
    by: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by[r.variant].append(r)
    summary: dict[str, Any] = {"ocr_available": ocr_available, "checks": len(rows)}

    print(f"\nRahat document check evaluation: {len(rows)} checks, {len(by['clean'])} people, OCR {'ON' if ocr_available else 'OFF'}")
    print("=" * 100)

    print("\nGenuine cards (should be accepted; a false alarm is a 'suspect' verdict)")
    total = Counter[str]()
    for v in GENUINE:
        rs = by[v]
        auto = sum(r.choice == "genuine" and r.route == "auto" for r in rs)
        fa = sum(r.choice == "suspect" for r in rs)
        human = sum(r.retake is None and r.route == "human" and r.choice != "suspect" for r in rs)
        retake = sum(r.retake is not None for r in rs)
        total.update(n=len(rs), auto=auto, fa=fa, human=human, retake=retake)
        n = len(rs)
        print(f"  {v:16s} auto-accepted {pct(auto, n)}   false alarm {pct(fa, n)}   to human {pct(human, n)}   retake {pct(retake, n)}")
    print(
        f"  {'ALL GENUINE':16s} auto-accepted {pct(total['auto'], total['n'])}   false alarm {pct(total['fa'], total['n'])}   "
        f"to human {pct(total['human'], total['n'])}   retake {pct(total['retake'], total['n'])}"
    )
    summary["genuine"] = dict(total)

    print("\nPoor quality (should ask for a retake, with the right hint)")
    qtotal = Counter[str]()
    for v, want in QUALITY.items():
        rs = by[v]
        asked = sum(r.retake is not None for r in rs)
        right = sum(r.quality == want and r.retake is not None for r in rs)
        auto = sum(r.route == "auto" for r in rs)
        qtotal.update(n=len(rs), asked=asked, right=right, auto=auto)
        wrong_hints = Counter(r.quality for r in rs if r.retake is not None and r.quality != want)
        extra = f"   other hints {dict(wrong_hints)}" if wrong_hints else ""
        print(f"  {v:16s} retake asked {pct(asked, len(rs))}   right hint {pct(right, len(rs))}   auto-accepted {pct(auto, len(rs))}{extra}")
    print(f"  {'ALL POOR':16s} retake asked {pct(qtotal['asked'], qtotal['n'])}   right hint {pct(qtotal['right'], qtotal['n'])}")
    summary["quality"] = dict(qtotal)

    print("\nForged cards (detected = 'suspect'; every non-auto outcome still reaches a person)")
    ftotal = Counter[str]()
    for v in FORGED:
        rs = by[v]
        det = sum(r.choice == "suspect" for r in rs)
        not_auto = sum(r.route != "auto" for r in rs)
        ftotal.update(n=len(rs), det=det, not_auto=not_auto)
        print(f"  {v:16s} detected {pct(det, len(rs))}   not auto-accepted {pct(not_auto, len(rs))}")
    print(f"  {'ALL FORGED':16s} detected {pct(ftotal['det'], ftotal['n'])}   not auto-accepted {pct(ftotal['not_auto'], ftotal['n'])}")
    summary["forged"] = dict(ftotal)

    print("\nWhich signals fired (share of checks of that variant that were not sent for a retake)")
    names = ("qr_signature_valid", "qr_signature_invalid", "qr_issuer_unknown", "print_qr_mismatch", "print_matches_qr",
             "ela_anomaly", "metadata_editor", "ocr_qr_mismatch", "ocr_matches_qr", "qr_missing", "qr_unreadable")  # fmt: skip
    print("  " + "variant".ljust(16) + "".join(n.replace("qr_", "").replace("_", " ")[:13].rjust(14) for n in names))
    for v in (*GENUINE, *FORGED):
        rs = [r for r in by[v] if r.retake is None]
        cells = "".join((f"{100 * sum(n in r.signals for r in rs) / len(rs):.0f}%" if rs else "-").rjust(14) for n in names)
        print("  " + v.ljust(16) + cells)

    altered = by["altered_name"] + by["altered_digit"] + by["wrong_qr"]
    ela_hits = [r for r in altered if "ela_anomaly" in r.signals]
    big_gap = [r for r in altered if r.params.get("jpeg", 0) - r.params.get("first_quality", 100) >= 15 and r.variant != "wrong_qr"]
    print("\nELA (localised over a printed value; the QR area is not covered)")
    print(f"  fired on edited cards {pct(len(ela_hits), len(altered))}")
    print(f"  fired on edited values where the final save was 15+ quality points above the photo's first save: "
          f"{pct(sum('ela_anomaly' in r.signals for r in big_gap), len(big_gap))}")  # fmt: skip
    genuine_rows = [r for v in GENUINE for r in by[v]]
    print(f"  fired on genuine cards {pct(sum('ela_anomaly' in r.signals for r in genuine_rows), len(genuine_rows))}")

    secs = sorted(r.seconds for r in rows)
    p50, p95 = statistics.median(secs), secs[int(0.95 * (len(secs) - 1))]
    print(f"\nLatency per check: median {p50:.2f}s, p95 {p95:.2f}s, max {secs[-1]:.2f}s")
    summary["latency_s"] = {"p50": round(p50, 3), "p95": round(p95, 3), "max": round(secs[-1], 3)}

    if not ocr_available:
        print("\nOCR was not available on this host (Tesseract binary missing), so these signals could not fire:")
        print("  ocr_qr_mismatch (printed text differs from the signed QR, read by OCR) and ocr_matches_qr.")
        print("  The OCR-free print check (print_qr_mismatch) compares the printed glyphs with the signed payload instead.")
    misses = [r for r in rows if _is_miss(r)]
    if misses:
        print("\nMisses (forged not flagged; genuine flagged or asked to retake; poor quality not asked or wrong hint):")
        for r in misses[:25]:
            print(f"  person {r.person:2d} {r.variant:15s} q={r.quality:10s} choice={r.choice} route={r.route} signals={r.signals} {r.params}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate check_document on generated specimen photos.")
    parser.add_argument("--people", type=int, default=24)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--json", type=Path, default=None, help="also write the summary and every row as JSON")
    parser.add_argument("--dump", type=Path, default=None, help="write the image of every miss to this folder")
    args = parser.parse_args(argv)
    from app.modules.docs_ai.ocr import default_engine

    started = time.perf_counter()
    rows = run(args.people, args.seed, args.dump)
    summary = report(rows, default_engine().available())
    print(f"\nTotal time {time.perf_counter() - started:.0f}s (seed {args.seed})")
    if args.json:
        payload = {"summary": summary, "rows": [r.__dict__ for r in rows]}
        args.json.write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
