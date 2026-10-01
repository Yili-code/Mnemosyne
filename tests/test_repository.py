from datetime import UTC, datetime, timedelta
from pathlib import Path

from vocab_bot.models import (
    DailyDelivery,
    Example,
    PendingWord,
    RelatedWord,
    StoredWord,
    VocabularyCard,
)
from vocab_bot.repository import SQLiteRepository
from vocab_bot.spaced_repetition import ReviewGrade


def make_card() -> VocabularyCard:
    example = Example(english="We can leverage this tool.", chinese="我們可以善用這項工具。")
    return VocabularyCard(
        word="leverage",
        kk_phonetic="ˈlɛvərɪdʒ",
        part_of_speech=["verb"],
        meanings_zh=["善用"],
        usage_notes=["常用於商業與科技情境"],
        collocations=["leverage technology"],
        examples=[example, Example(english="They leverage data.", chinese="他們善用資料。")],
        related_words=[
            RelatedWord(
                word=word,
                kk_phonetic="rɪˈleɪtɪd",
                part_of_speech=["verb"],
                meaning_zh=meaning,
                connection="在相似情境中使用",
                example=Example(english=f"We {word} resources.", chinese="我們善用資源。"),
            )
            for word, meaning in [
                ("utilize", "利用"),
                ("optimize", "最佳化"),
                ("advantage", "優勢"),
            ]
        ],
    )


def test_sqlite_saves_headword_and_related_words(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    words = {item.word: item for item in repository.list_words()}
    assert set(words) == {"leverage", "utilize", "optimize", "advantage"}
    assert words["utilize"].is_related_seed is True
    assert words["utilize"].source_word == "leverage"


def test_sqlite_saves_and_finds_a_multi_word_term(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card().model_copy(update={"word": "canonical record"}))

    stored = repository.get_word("canonical record")

    assert stored is not None
    assert stored.word == "canonical record"


def test_claim_update_is_idempotent(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    assert repository.claim_update(42) is True
    assert repository.claim_update(42) is False


def test_sqlite_review_grade_is_atomic_and_cannot_be_repeated(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    now = datetime.now(UTC) + timedelta(seconds=1)

    reviewed = repository.grade_review("leverage", ReviewGrade.GOOD, now)
    repeated = repository.grade_review("leverage", ReviewGrade.EASY, now)

    assert reviewed is not None
    assert reviewed.review_count == 1
    assert reviewed.interval_days == 3
    assert reviewed.due_at == now + timedelta(days=3)
    assert repeated is None


def test_saving_refreshed_card_preserves_review_schedule(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    now = datetime.now(UTC) + timedelta(seconds=1)
    reviewed = repository.grade_review("leverage", ReviewGrade.GOOD, now)
    assert reviewed is not None

    repository.save_card(make_card())
    refreshed = next(item for item in repository.list_words() if item.word == "leverage")

    assert refreshed.review_count == 1
    assert refreshed.interval_days == 3
    assert refreshed.due_at == now + timedelta(days=3)


def test_old_word_without_due_at_becomes_due_from_created_at() -> None:
    created_at = datetime(2026, 9, 1, tzinfo=UTC)
    stored = StoredWord.model_validate(
        {"word": "legacy", "meanings_zh": ["舊資料"], "created_at": created_at}
    )

    assert stored.due_at == created_at


def test_sqlite_retry_queue_persists_claims_and_completion(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    now = datetime.now(UTC)
    repository.enqueue_retry(
        PendingWord(
            word="protestation",
            chat_id=123,
            last_error_code="invalid_response",
            next_attempt_at=now,
        )
    )

    claimed = repository.claim_due_retry(now)

    assert claimed is not None
    assert claimed.word == "protestation"
    assert repository.claim_due_retry(now) is None
    repository.delete_retry("protestation")
    assert repository.claim_due_retry(now + timedelta(days=1)) is None


def test_sqlite_clear_user_data_is_atomic_and_keeps_update_deduplication(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    repository.save_delivery(DailyDelivery(date="2026-09-27", words=["leverage"]))
    repository.enqueue_retry(
        PendingWord(
            word="protestation",
            chat_id=123,
            last_error_code="timeout",
            next_attempt_at=datetime.now(UTC),
        )
    )
    assert repository.claim_update(42) is True

    counts = repository.clear_user_data()

    assert counts == {"words": 4, "pending_words": 1, "deliveries": 1}
    assert repository.list_words() == []
    assert repository.get_delivery("2026-09-27") is None
    assert repository.claim_due_retry(datetime.now(UTC) + timedelta(days=1)) is None
    assert repository.claim_update(42) is False
