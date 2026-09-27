from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from vocab_bot.models import StoredWord

MIN_EASE_FACTOR = 1.3
MAX_EASE_FACTOR = 4.0
MAX_INTERVAL_DAYS = 365.0
AGAIN_INTERVAL_DAYS = 10 / (24 * 60)


class ReviewGrade(StrEnum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


GRADE_CODES = {
    "a": ReviewGrade.AGAIN,
    "h": ReviewGrade.HARD,
    "g": ReviewGrade.GOOD,
    "e": ReviewGrade.EASY,
}

GRADE_LABELS = {
    ReviewGrade.AGAIN: "Again",
    ReviewGrade.HARD: "Hard",
    ReviewGrade.GOOD: "Good",
    ReviewGrade.EASY: "Easy",
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_due(item: StoredWord, now: datetime) -> bool:
    return _utc(item.due_at) <= _utc(now)


def select_due_words(words: list[StoredWord], *, now: datetime, limit: int) -> list[StoredWord]:
    due = [item for item in words if is_due(item, now)]
    due.sort(key=lambda item: (_utc(item.due_at), item.review_count, item.word))
    return due[:limit]


def schedule_review(item: StoredWord, grade: ReviewGrade, *, reviewed_at: datetime) -> StoredWord:
    """Return the next deterministic review state for a recalled word.

    This is an intentionally small SM-2-inspired scheduler. The interval is driven by
    explicit recall quality instead of treating delivery as successful learning.
    """
    reviewed_at = _utc(reviewed_at)
    ease = item.ease_factor
    previous_interval = item.interval_days

    if grade is ReviewGrade.AGAIN:
        interval = AGAIN_INTERVAL_DAYS
        ease -= 0.20
        lapse_count = item.lapse_count + 1
    elif grade is ReviewGrade.HARD:
        interval = 1.0 if item.review_count == 0 else max(1.0, previous_interval * 1.2)
        ease -= 0.15
        lapse_count = item.lapse_count
    elif grade is ReviewGrade.GOOD:
        interval = 3.0 if item.review_count == 0 else max(1.0, previous_interval * ease)
        lapse_count = item.lapse_count
    else:
        interval = 7.0 if item.review_count == 0 else max(2.0, previous_interval * ease * 1.3)
        ease += 0.15
        lapse_count = item.lapse_count

    interval = min(interval, MAX_INTERVAL_DAYS)
    ease = min(MAX_EASE_FACTOR, max(MIN_EASE_FACTOR, ease))
    return item.model_copy(
        update={
            "review_count": item.review_count + 1,
            "lapse_count": lapse_count,
            "interval_days": interval,
            "ease_factor": ease,
            "last_reviewed_at": reviewed_at,
            "due_at": reviewed_at + timedelta(days=interval),
            "updated_at": reviewed_at,
        }
    )


def encode_review_callback(word: str, grade: ReviewGrade) -> str:
    code = grade.value[0]
    return f"review:{code}:{word}"


def decode_review_callback(value: str) -> tuple[str, ReviewGrade] | None:
    parts = value.split(":", 2)
    if len(parts) != 3 or parts[0] != "review":
        return None
    grade = GRADE_CODES.get(parts[1])
    word = parts[2].strip().lower()
    if grade is None or not word:
        return None
    return word, grade


def describe_interval(interval_days: float) -> str:
    minutes = round(interval_days * 24 * 60)
    if minutes < 60:
        return f"{minutes} 分鐘"
    if minutes < 24 * 60:
        return f"{round(minutes / 60)} 小時"
    return f"{round(interval_days)} 天"
