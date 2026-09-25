from datetime import UTC, datetime, timedelta

from vocab_bot.gemini import GeminiError
from vocab_bot.models import DailyDelivery, PendingWord, StoredWord
from vocab_bot.repository import card_to_words
from vocab_bot.service import VocabularyService

from .test_repository import make_card


class FakeRepository:
    def __init__(self) -> None:
        self.updates: set[int] = set()
        self.words: list[StoredWord] = []
        self.deliveries: dict[str, DailyDelivery] = {}
        self.pending: dict[str, PendingWord] = {}
        self.saved_cards = 0

    def claim_update(self, update_id: int) -> bool:
        if update_id in self.updates:
            return False
        self.updates.add(update_id)
        return True

    def save_card(self, card) -> None:
        self.saved_cards += 1
        self.words = card_to_words(card)

    def list_words(self) -> list[StoredWord]:
        return self.words

    def mark_reviewed(self, words, reviewed_at: datetime) -> None:
        for item in self.words:
            if item.word in words:
                item.review_count += 1
                item.last_reviewed_at = reviewed_at

    def get_delivery(self, date: str) -> DailyDelivery | None:
        return self.deliveries.get(date)

    def save_delivery(self, delivery: DailyDelivery) -> None:
        self.deliveries[delivery.date] = delivery

    def enqueue_retry(self, pending: PendingWord) -> None:
        self.pending[pending.word] = pending

    def claim_due_retry(self, now: datetime) -> PendingWord | None:
        due = [item for item in self.pending.values() if item.next_attempt_at <= now]
        return min(due, key=lambda item: item.next_attempt_at) if due else None

    def reschedule_retry(self, pending: PendingWord) -> None:
        self.pending[pending.word] = pending

    def delete_retry(self, word: str) -> None:
        self.pending.pop(word, None)


class FakeGemini:
    def __init__(self) -> None:
        self.calls = 0

    def create_card(self, word: str):
        self.calls += 1
        assert word == "leverage"
        return make_card()


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


class FailingGemini:
    def __init__(self, *, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def create_card(self, word: str):
        self.calls += 1
        if self.calls <= self.failures:
            raise GeminiError("temporary failure", code="http_503")
        assert word == "leverage"
        return make_card()


def make_service():
    repository = FakeRepository()
    gemini = FakeGemini()
    telegram = FakeTelegram()
    service = VocabularyService(
        repository=repository,
        gemini=gemini,
        telegram=telegram,
        owner_chat_id=123,
        review_size=2,
        timezone="Asia/Taipei",
    )
    return service, repository, gemini, telegram


def test_update_retry_does_not_call_gemini_twice() -> None:
    service, repository, gemini, telegram = make_service()
    update = {
        "update_id": 99,
        "message": {"chat": {"id": 123, "type": "private"}, "text": "Leverage"},
    }
    service.handle_update(update)
    service.handle_update(update)
    assert gemini.calls == 1
    assert repository.saved_cards == 1
    assert len(telegram.messages) == 2


def test_non_owner_message_is_ignored() -> None:
    service, repository, gemini, telegram = make_service()
    service.handle_update(
        {
            "update_id": 100,
            "message": {"chat": {"id": 999, "type": "private"}, "text": "leverage"},
        }
    )
    assert not repository.updates
    assert gemini.calls == 0
    assert not telegram.messages


def test_words_command_lists_repository_without_calling_gemini() -> None:
    service, repository, gemini, telegram = make_service()
    repository.words = card_to_words(make_card())

    service.handle_update(
        {
            "update_id": 102,
            "message": {"chat": {"id": 123, "type": "private"}, "text": "/words"},
        }
    )

    assert gemini.calls == 0
    assert "已儲存單字" in telegram.messages[0][1]
    assert "leverage" in telegram.messages[0][1]


def test_scheduled_delivery_is_idempotent_for_the_day() -> None:
    service, repository, _, telegram = make_service()
    repository.words = card_to_words(make_card())
    first = service.send_review()
    message_count = len(telegram.messages)
    second = service.send_review()
    assert first == second
    assert len(first) == 2
    assert len(telegram.messages) == message_count


def test_gemini_failure_is_saved_for_automatic_retry() -> None:
    service, repository, _, telegram = make_service()
    service.gemini = FailingGemini(failures=1)
    before = datetime.now(UTC)

    service.handle_update(
        {
            "update_id": 101,
            "message": {"chat": {"id": 123, "type": "private"}, "text": "leverage"},
        }
    )

    pending = repository.pending["leverage"]
    assert pending.attempt_count == 1
    assert pending.last_error_code == "http_503"
    assert pending.next_attempt_at >= before + timedelta(minutes=14)
    assert "自動重試" in telegram.messages[-1][1]


def test_due_retry_saves_card_and_removes_pending_word() -> None:
    service, repository, _, telegram = make_service()
    service.gemini = FailingGemini(failures=0)
    now = datetime.now(UTC)
    repository.enqueue_retry(
        PendingWord(
            word="leverage",
            chat_id=123,
            attempt_count=1,
            last_error_code="http_503",
            next_attempt_at=now,
        )
    )

    result = service.retry_failed_word(now=now)

    assert result == {"processed": 1, "succeeded": 1, "failed": 0}
    assert repository.saved_cards == 1
    assert "leverage" not in repository.pending
    assert "自動重試成功" in telegram.messages[-2][1]


def test_failed_retry_uses_longer_backoff() -> None:
    service, repository, _, _ = make_service()
    service.gemini = FailingGemini(failures=1)
    now = datetime.now(UTC)
    repository.enqueue_retry(
        PendingWord(
            word="leverage",
            chat_id=123,
            attempt_count=1,
            last_error_code="timeout",
            next_attempt_at=now,
        )
    )

    result = service.retry_failed_word(now=now)

    pending = repository.pending["leverage"]
    assert result == {"processed": 1, "succeeded": 0, "failed": 1}
    assert pending.attempt_count == 2
    assert pending.next_attempt_at == now + timedelta(hours=1)
