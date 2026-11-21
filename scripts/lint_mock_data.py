#!/usr/bin/env python3
"""Fail when text files contain anything shaped like a real CNIC or Pakistani mobile number.

Allowed mock shapes: CNIC 00000-NNNNNNN-C, phone 0999-NNNNNNN.
Add the marker `mock-lint: allow` on a line to skip it (regex definitions, tests).
Usage: python scripts/lint_mock_data.py [--self-test] [root]
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

CNIC = re.compile(r"\b\d{5}-\d{7}-\d\b")  # mock-lint: allow
PHONE_LOCAL = re.compile(r"\b03\d{2}[- ]?\d{7}\b")  # mock-lint: allow
PHONE_INTL = re.compile(r"\+92 ?3\d{2}[- ]?\d{7}")  # mock-lint: allow
MARKER = "mock-lint: allow"

SKIP_DIRS = {".git", "node_modules", ".venv", "dist", ".devdb", "__pycache__",
             ".mypy_cache", ".ruff_cache", ".pytest_cache", "var", "htmlcov", "worktrees", ".wt"}
SKIP_NAMES = {"package-lock.json", "uv.lock", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}
SKIP_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp3", ".ogg",
             ".opus", ".wav", ".m4a", ".woff", ".woff2", ".onnx", ".pkl", ".zip", ".gz",
             ".pyc", ".sqlite", ".db", ".bin", ".tar"}


def scan_line(line: str) -> list[str]:
    """Return a description for each violation on the line."""
    if MARKER in line:
        return []
    found = []
    for m in CNIC.finditer(line):
        if not m.group(0).startswith("00000-"):
            found.append(f"CNIC-shaped value {m.group(0)}")
    for rx in (PHONE_LOCAL, PHONE_INTL):
        for m in rx.finditer(line):
            found.append(f"Pakistani mobile number {m.group(0)}")
    return found


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if name in SKIP_NAMES or p.suffix.lower() in SKIP_EXTS:
                continue
            yield p


def scan(root: Path) -> list[str]:
    problems = []
    for p in iter_files(root):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for msg in scan_line(line):
                problems.append(f"{p.relative_to(root).as_posix()}:{n}: {msg}")
    return problems


def self_test() -> int:
    bad = [
        "id 42101-1234567-1",  # mock-lint: allow
        "call 0300-1234567",  # mock-lint: allow
        "call 03001234567",  # mock-lint: allow
        "call 0300 1234567",  # mock-lint: allow
        "call +92 300 1234567",  # mock-lint: allow
        "call +923001234567",  # mock-lint: allow
    ]
    good = [
        "id 00000-1234567-1",
        "call 0999-1234567",
        "call 09991234567",
        "regex 42101-1234567-1  # mock-lint: allow",
        "timestamp 2026-11-21 10:00:00",
        "number 123456789012345",
    ]
    failures = [s for s in bad if not scan_line(s)] + [s for s in good if scan_line(s)]
    for s in failures:
        print(f"self-test FAILED on: {s}")
    if failures:
        return 1
    print("self-test ok")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    args = [a for a in argv if not a.startswith("-")]
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parent.parent
    problems = scan(root)
    if problems:
        print("Mock-data lint failed. Use 00000-NNNNNNN-C and 0999-NNNNNNN only:")
        for p in problems:
            print(f"  {p}")
        return 1
    print("mock-data lint ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
