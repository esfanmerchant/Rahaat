"""The verdict every guard returns. Callers store it in the audit log (`service.record`)."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

Surface = Literal["question", "transcript", "ocr", "message", "answer", "action"]
GuardName = Literal["input", "output", "action"]
VerdictKind = Literal["allow", "mask", "flag", "block"]

_SEVERITY: dict[str, int] = {"allow": 0, "mask": 1, "flag": 2, "block": 3}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


class GuardVerdict(BaseModel):
    """allow: nothing found. mask: personal data was masked, carry on with the masked text. flag: instruction-like
    text was found; it is treated as data and never obeyed, and staff can see it. block: do not process."""

    guard: GuardName
    surface: Surface
    verdict: VerdictKind
    codes: list[str] = Field(default_factory=list, description="Reason codes, never free text")
    text_hash: str | None = None
    redacted_text: str | None = Field(default=None, description="The text with personal data masked; never the raw text")
    model_version: str

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    def summary(self) -> dict[str, object]:
        """What goes into an audit row or a response: no text."""
        return {"guard": self.guard, "surface": self.surface, "verdict": self.verdict, "codes": list(self.codes),
                "model_version": self.model_version}  # fmt: skip


def worst(verdicts: list[GuardVerdict]) -> str:
    return max((v.verdict for v in verdicts), key=lambda k: _SEVERITY[k], default="allow")
