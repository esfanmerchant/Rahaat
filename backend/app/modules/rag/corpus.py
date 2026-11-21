"""Read the policy corpus from `data/policy`: one Markdown file per document and language.

Pure: no database. A file's content hash is its identity, so ingestion can tell an unchanged document from
an edited one, and refuses an edit that kept the same version number.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

POLICY_DIR: Final = Path(__file__).resolve().parents[4] / "data" / "policy"
LANGS: Final = ("en", "ur")
_REQUIRED: Final = ("doc", "lang", "version", "title", "status")
_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*(?:\{#(?P<id>[a-z0-9-]+)\})?\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?۔؟])\s+")


class CorpusError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Section:
    section_id: str
    heading: str
    ordinal: int
    sentences: tuple[str, ...]

    @property
    def text(self) -> str:
        return " ".join(self.sentences)


@dataclass(frozen=True, slots=True)
class CorpusDoc:
    doc_key: str
    lang: str
    version: int
    title: str
    status: str
    rule_version: int | None
    path: str
    content_hash: str
    sections: tuple[Section, ...]

    @property
    def source(self) -> str:
        """Stable id of the document in one language, stored in `kb_documents.source`."""
        return f"policy:{self.doc_key}:{self.lang}"


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.extend(s.strip() for s in _SENTENCE_END.split(line) if s.strip())
    return out


def _front_matter(lines: list[str], path: str) -> tuple[dict[str, str], int]:
    if not lines or lines[0].strip() != "---":
        raise CorpusError(f"{path}: missing front matter")
    meta: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            missing = [k for k in _REQUIRED if k not in meta]
            if missing:
                raise CorpusError(f"{path}: front matter lacks {missing}")
            return meta, i + 1
        key, sep, value = line.partition(":")
        if not sep:
            raise CorpusError(f"{path}: bad front matter line {line!r}")
        meta[key.strip()] = value.split("#", 1)[0].strip() if key.strip() != "title" else value.strip()
    raise CorpusError(f"{path}: front matter is not closed")


def parse_document(text: str, path: str) -> CorpusDoc:
    lines = text.replace("\r\n", "\n").split("\n")
    meta, start = _front_matter(lines, path)
    if meta["lang"] not in LANGS:
        raise CorpusError(f"{path}: lang must be one of {LANGS}")
    sections: list[Section] = []
    heading: tuple[str, str] | None = None
    body: list[str] = []
    seen: set[str] = set()

    def close() -> None:
        if heading is None:
            return
        sentences = tuple(split_sentences("\n".join(body)))
        if not sentences:
            raise CorpusError(f"{path}: section {heading[0]!r} is empty")
        sections.append(Section(section_id=heading[0], heading=heading[1], ordinal=len(sections), sentences=sentences))

    for line in lines[start:]:
        match = _HEADING.match(line)
        if match:
            close()
            section_id = match.group("id")
            if not section_id:
                raise CorpusError(f"{path}: heading {line!r} needs a {{#section-id}}")
            if section_id in seen:
                raise CorpusError(f"{path}: duplicate section id {section_id}")
            seen.add(section_id)
            heading, body = (section_id, match.group("title").strip()), []
        elif line.startswith("#"):
            continue
        elif heading is not None:
            body.append(line)
    close()
    if not sections:
        raise CorpusError(f"{path}: no sections")
    rule_version = meta.get("rule_version")
    return CorpusDoc(
        doc_key=meta["doc"], lang=meta["lang"], version=int(meta["version"]), title=meta["title"], status=meta["status"],
        rule_version=int(rule_version) if rule_version else None, path=path,
        content_hash=hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest(), sections=tuple(sections),
    )  # fmt: skip


def load_corpus(directory: Path = POLICY_DIR) -> list[CorpusDoc]:
    """Every `<doc>.<lang>.md` file, sorted. Raises CorpusError on a malformed file."""
    docs = []
    for path in sorted(directory.glob("*.*.md")):
        docs.append(parse_document(path.read_text(encoding="utf-8"), f"data/policy/{path.name}"))
    keys = [(d.doc_key, d.lang) for d in docs]
    if len(keys) != len(set(keys)):
        raise CorpusError("two files define the same document and language")
    return docs
