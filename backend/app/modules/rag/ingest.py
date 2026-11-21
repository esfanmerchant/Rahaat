"""Put the policy corpus into `kb_documents` and `kb_chunks`, one chunk per section. Safe to run again.

A published version is immutable: the same version with different text is refused (bump the version), a
new version is added and the older one retired, so earlier answers still cite the version they used.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.db import models
from app.modules.rag.corpus import CorpusDoc, load_corpus


@dataclass(slots=True)
class IngestReport:
    added: list[str] = field(default_factory=list)
    unchanged: int = 0
    retired: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)  # text changed without a version bump, or older than stored

    def as_dict(self) -> dict[str, object]:
        return {"added": self.added, "unchanged": self.unchanged, "retired": self.retired, "refused": self.refused}


def ingest(
    db: Session,
    tenant_id: UUID,
    docs: list[CorpusDoc] | None = None,
    *,
    actor_type: str = "system",
    actor_id: UUID | None = None,
    actor_role: str | None = None,
) -> IngestReport:
    """Does not commit; the caller does. Writes one audit row per added or retired document version."""
    docs = load_corpus() if docs is None else docs
    report = IngestReport()
    rows = db.scalars(select(models.KbDocument).where(models.KbDocument.tenant_id == tenant_id,
                                                      models.KbDocument.source.like("policy:%"))).all()  # fmt: skip
    by_source: dict[str, list[models.KbDocument]] = {}
    for row in rows:
        by_source.setdefault(row.source or "", []).append(row)
    for doc in docs:
        stored = by_source.get(doc.source, [])
        same = [r for r in stored if r.version_no == doc.version]
        if same:
            if same[0].content_hash == doc.content_hash:
                report.unchanged += 1
            else:
                report.refused.append(f"{doc.source}:v{doc.version}: text changed without a new version")
            continue
        if any(r.version_no > doc.version for r in stored):
            report.refused.append(f"{doc.source}:v{doc.version}: a newer version is already stored")
            continue
        document = models.KbDocument(
            id=uuid.uuid4(), tenant_id=tenant_id, title=doc.title[:200], lang=doc.lang, version_no=doc.version, source=doc.source,
            status=doc.status, content_hash=doc.content_hash, approved_by=actor_id,
        )  # fmt: skip
        db.add(document)
        db.flush()
        for section in doc.sections:
            db.add(models.KbChunk(
                id=uuid.uuid4(), tenant_id=tenant_id, document_id=document.id, section=section.heading[:120], ordinal=section.ordinal,
                text=section.text, meta={"doc_key": doc.doc_key, "section_id": section.section_id, "heading": section.heading,
                                         "sentences": list(section.sentences), "rule_version": doc.rule_version, "path": doc.path},
            ))  # fmt: skip
        retired = []
        for old in stored:
            if old.status == "approved":
                old.status = "retired"
                retired.append(f"{old.source}:v{old.version_no}")
        report.added.append(f"{doc.source}:v{doc.version}")
        report.retired.extend(retired)
        audit.write(db, tenant_id=tenant_id, action="kb.document_ingested", actor_type=actor_type, actor_id=actor_id,
                    actor_role=actor_role, object_type="kb_document", object_id=document.id,
                    details={"source": doc.source, "version": doc.version, "content_hash": doc.content_hash,
                             "sections": len(doc.sections), "retired": retired, "rule_version": doc.rule_version})  # fmt: skip
    db.flush()
    return report


def department_ids(db: Session) -> list[UUID]:
    return list(db.scalars(select(models.Tenant.id).where(models.Tenant.kind == "department", models.Tenant.status == "active")).all())
