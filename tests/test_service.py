from datetime import datetime

from vocab_bot.models import DailyDelivery, StoredWord
from vocab_bot.repository import card_to_words
from vocab_bot.service import VocabularyService

from .test_repository import make_card


class FakeRepository:
    def __init__(self) -> None:
        self.updates: set[int] = set()
        self.words: list[StoredWord] = []
        self.deliveries: dict[str, DailyDelivery] = {}
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


def test_scheduled_delivery_is_idempotent_for_the_day() -> None:
    service, repository, _, telegram = make_service()
    repository.words = card_to_words(make_card())
    first = service.send_review()
    message_count = len(telegram.messages)
    second = service.send_review()
    assert first == second
    assert len(first) == 2
    assert len(telegram.messages) == message_count
