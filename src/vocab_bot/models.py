from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Example(BaseModel):
    english: str = Field(min_length=3, max_length=240)
    chinese: str = Field(min_length=1, max_length=160)


class RelatedWord(BaseModel):
    word: str = Field(pattern=r"^[A-Za-z][A-Za-z -]{0,48}[A-Za-z]$|^[A-Za-z]$")
    meaning_zh: str = Field(min_length=1, max_length=100)
    connection: str = Field(min_length=2, max_length=160)
    example: Example
    exceptional_derivation: bool = False
    exception_reason: str | None = Field(default=None, max_length=120)

    @field_validator("word")
    @classmethod
    def normalize_word(cls, value: str) -> str:
        return " ".join(value.lower().split())


class VocabularyCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str
    part_of_speech: list[str] = Field(min_length=1, max_length=3)
    meanings_zh: list[str] = Field(min_length=1, max_length=3)
    usage_notes: list[str] = Field(min_length=1, max_length=4)
    collocations: list[str] = Field(default_factory=list, max_length=5)
    examples: list[Example] = Field(min_length=2, max_length=3)
    related_words: list[RelatedWord] = Field(min_length=3, max_length=8)

    @field_validator("word")
    @classmethod
    def normalize_headword(cls, value: str) -> str:
        return " ".join(value.lower().split())


class StoredWord(BaseModel):
    word: str
    part_of_speech: list[str] = Field(default_factory=list)
    meanings_zh: list[str]
    usage_notes: list[str] = Field(default_factory=list)
    collocations: list[str] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    related_words: list[RelatedWord] = Field(default_factory=list)
    source_word: str | None = None
    is_related_seed: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    review_count: int = 0
    last_reviewed_at: datetime | None = None


class DailyDelivery(BaseModel):
    date: str
    words: list[str]
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingWord(BaseModel):
    word: str
    chat_id: int
    attempt_count: int = Field(default=1, ge=1)
    last_error_code: str = Field(max_length=80)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_attempted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    next_attempt_at: datetime
