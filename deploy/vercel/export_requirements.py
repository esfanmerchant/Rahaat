"""Write the root requirements.txt that Vercel installs, from backend/uv.lock (runtime packages only).

    npm run vercel:requirements                    # rewrite requirements.txt
    npm run vercel:requirements -- --check         # fail when it is out of date (CI)
    npm run vercel:requirements -- --with-ocr      # keep the RapidOCR stack (needs a larger function, see the README)

Vercel installs the function's dependencies from a requirements.txt at the project root, but the project's
single source of truth is backend/uv.lock. This keeps the two in step.

Dropped on purpose:
* uvloop, httptools, watchfiles, websockets: server extras that Vercel's own runtime replaces.
* the RapidOCR stack (rapidocr-onnxruntime, onnxruntime and what only they need, about 100 MB): with it the
  function is about 554 MB installed, over Vercel's 500 MB limit. Without it the document check still verifies
  the signed QR; the printed-text cross-check reports "OCR unavailable", as it does anywhere no OCR engine exists.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "requirements.txt"
SERVER_EXTRAS = {"uvloop", "httptools", "watchfiles", "websockets"}
OCR_ROOTS = {"rapidocr-onnxruntime", "onnxruntime"}
HEADER = (
    "# Generated from backend/uv.lock by deploy/vercel/export_requirements.py. Do not edit by hand.\n"
    "# Run: npm run vercel:requirements\n"
)


def _name(line: str) -> str:
    return re.split(r"[=;\s]", line.strip(), maxsplit=1)[0].lower()


def _exported() -> list[str]:
    return subprocess.run(  # noqa: S603  (fixed command, no user input)
        ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project", "--project", str(ROOT / "backend"), "--quiet"],  # noqa: S607
        check=True, capture_output=True, text=True, cwd=ROOT,
    ).stdout.splitlines()  # fmt: skip


def _only_needed_by(parents: dict[str, list[str]], roots: set[str]) -> set[str]:
    """The roots plus every package whose only dependents are already in the set."""
    dropped = set(roots)
    changed = True
    while changed:
        changed = False
        for package, who in parents.items():
            if package not in dropped and who and all(p in dropped for p in who):
                dropped.add(package)
                changed = True
    return dropped


def render(with_ocr: bool = False) -> str:
    packages: list[tuple[str, str]] = []  # (name, requirement line)
    parents: dict[str, list[str]] = {}
    current = ""
    for line in _exported():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith(" "):
            note = line.strip().lstrip("#").strip()
            note = note.removeprefix("via").strip()
            if note:
                parents[current].append(note.lower())
            continue
        current = _name(line)
        packages.append((current, line.rstrip()))
        parents[current] = []
    drop = set(SERVER_EXTRAS) | (set() if with_ocr else _only_needed_by(parents, OCR_ROOTS))
    return HEADER + "\n".join(line for name, line in packages if name not in drop) + "\n"


def main() -> int:
    text = render(with_ocr="--with-ocr" in sys.argv)
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("requirements.txt is out of date: run `npm run vercel:requirements`", file=sys.stderr)
            return 1
        print("requirements.txt is up to date")
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.name}: {len(text.splitlines()) - 2} packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
