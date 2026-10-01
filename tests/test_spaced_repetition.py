from datetime import UTC, datetime, timedelta

import pytest

from vocab_bot.models import StoredWord
from vocab_bot.spaced_repetition import (
    ReviewGrade,
    decode_review_callback,
    encode_review_callback,
    schedule_review,
    select_due_words,
)


@pytest.mark.parametrize(
    ("grade", "expected_days"),
    [
        (ReviewGrade.AGAIN, 10 / (24 * 60)),
        (ReviewGrade.HARD, 1.0),
        (ReviewGrade.GOOD, 3.0),
        (ReviewGrade.EASY, 7.0),
    ],
)
def test_first_review_uses_learning_intervals(grade: ReviewGrade, expected_days: float) -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    word = StoredWord(word="leverage", meanings_zh=["善用"], due_at=now)

    reviewed = schedule_review(word, grade, reviewed_at=now)

    assert reviewed.review_count == 1
    assert reviewed.interval_days == pytest.approx(expected_days)
    assert reviewed.due_at == now + timedelta(days=expected_days)


def test_again_records_lapse_and_reduces_ease() -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    word = StoredWord(
        word="leverage",
        meanings_zh=["善用"],
        review_count=4,
        interval_days=12,
        due_at=now,
    )

    reviewed = schedule_review(word, ReviewGrade.AGAIN, reviewed_at=now)

    assert reviewed.lapse_count == 1
    assert reviewed.ease_factor == pytest.approx(2.3)
    assert reviewed.interval_days == pytest.approx(10 / (24 * 60))


def test_good_multiplies_previous_interval_by_ease() -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    word = StoredWord(
        word="leverage",
        meanings_zh=["善用"],
        review_count=2,
        interval_days=4,
        ease_factor=2.5,
        due_at=now,
    )

    reviewed = schedule_review(word, ReviewGrade.GOOD, reviewed_at=now)

    assert reviewed.interval_days == 10


def test_due_selection_excludes_future_words_and_orders_oldest_first() -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    words = [
        StoredWord(word="future", meanings_zh=["未來"], due_at=now + timedelta(days=1)),
        StoredWord(word="today", meanings_zh=["今天"], due_at=now),
        StoredWord(word="old", meanings_zh=["舊"], due_at=now - timedelta(days=3)),
    ]

    selected = select_due_words(words, now=now, limit=10)

    assert [item.word for item in selected] == ["old", "today"]


def test_review_callback_preserves_a_multi_word_term() -> None:
    callback = encode_review_callback("canonical record", ReviewGrade.GOOD)

    assert len(callback.encode()) <= 64
    assert decode_review_callback(callback) == ("canonical record", ReviewGrade.GOOD)
