"""Request and response shapes of the voice endpoints."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.contracts.common import Strict
from app.contracts.decision import TypedDecision
from app.modules.voice.phrases import Spoken

QuestionKey = Literal["household_size", "income_band", "is_widow", "has_disability", "receives_other_aid", "full_name", "confirm"]
ExpectedType = Literal["yes_no", "number", "income_band", "name_confirm"]
Transcript = Annotated[str, StringConstraints(max_length=400)]


class VoiceInterpretIn(Strict):
    question_key: QuestionKey = Field(description="Which question was asked. `confirm` is the answer to a read-back.")
    expected: ExpectedType = Field(description="The answer type the question expects; must match the question")
    transcript: Transcript = Field(description="What the speech engine heard. Treated as data, never as instructions.")
    stt_confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="The engine's own confidence; 0 or absent means not reported")
    alternatives: list[Transcript] = Field(default_factory=list, max_length=4, description="Other hypotheses from the engine, best first")
    lang: Literal["ur", "en"] | None = Field(default=None, description="Language of the read-back; defaults to Accept-Language, then Urdu")
    engine: Literal["device", "server"] = Field(default="device", description="device: the phone's recogniser; server: POST /v1/voice/stt")
    attempt: int = Field(default=1, ge=1, le=10, description="1 for the first try at this question; from 3 the screen offers pictures")
    expected_name: str | None = Field(default=None, max_length=120, description="full_name only: the name read from the card")
    application_id: UUID | None = Field(default=None, description="Links the audit entry to the application being filled")


class FormValueOut(BaseModel):
    """Ready to send in `PATCH /v1/applications/{id}` once the person has confirmed the read-back."""

    value: int | bool | str | None
    confidence: float
    provenance: Literal["spoken"] = "spoken"


class VoiceInterpretOut(BaseModel):
    decision: TypedDecision[str] = Field(description="choice is 'yes', 'no', 'unknown', a number like '5', or a band like 'under_15k'")
    question_key: str
    expected: str
    field: str | None = Field(description="The form field this answers, or null (name confirmation, read-back confirmation)")
    value: int | bool | str | None = Field(description="The form value; null for 'I do not know' and when abstained")
    unknown: bool = Field(description="The person said they do not know; a valid answer that stays unknown")
    form_patch: dict[str, FormValueOut] | None = Field(description="Send this only after the person confirms the read-back")
    needs_confirmation: bool = Field(description="Always true for an answer: read it back and ask 'Is that right?'")
    readback: Spoken | None = Field(description="'You said: five people. Is that right?' with its clips, in the person's language")
    ask_again: Spoken | None = Field(description="When abstained: what to say before asking again")
    fallback: Literal["none", "say_again", "use_pictures"] = Field(description="use_pictures after three tries or when speech cannot help")


class SttOut(BaseModel):
    transcript: str
    confidence: float | None = Field(description="Provider confidence (0 to 1) when it gives one")
    lang: str
    provider: str
    duration_s: float | None = None
    notice: str = "The audio was not stored."
