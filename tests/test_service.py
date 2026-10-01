from datetime import UTC, datetime, timedelta

from vocab_bot.gemini import GeminiError
from vocab_bot.models import DailyDelivery, PendingWord, ReviewTaskPayload, StoredWord
from vocab_bot.repository import card_to_words
from vocab_bot.service import VocabularyService
from vocab_bot.spaced_repetition import ReviewGrade, schedule_review, select_due_words
from vocab_bot.telegram import TelegramError

from .test_repository import make_card


class FakeRepository:
    def __init__(self) -> None:
        self.updates: set[int] = set()
        self.words: list[StoredWord] = []
        self.deliveries: dict[str, DailyDelivery] = {}
        self.pending: dict[str, PendingWord] = {}
        self.saved_cards = 0
        self.clear_calls = 0

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

    def get_word(self, word: str) -> StoredWord | None:
        return next((item for item in self.words if item.word == word), None)

    def list_due_words(self, now: datetime, limit: int) -> list[StoredWord]:
        return select_due_words(self.words, now=now, limit=limit)

    def grade_review(
        self, word: str, grade: ReviewGrade, reviewed_at: datetime
    ) -> StoredWord | None:
        for index, item in enumerate(self.words):
            if item.word == word and item.due_at <= reviewed_at:
                reviewed = schedule_review(item, grade, reviewed_at=reviewed_at)
                self.words[index] = reviewed
                return reviewed
        return None

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

    def clear_user_data(self) -> dict[str, int]:
        self.clear_calls += 1
        counts = {
            "words": len(self.words),
            "pending_words": len(self.pending),
            "deliveries": len(self.deliveries),
        }
        self.words.clear()
        self.pending.clear()
        self.deliveries.clear()
        return counts


class FakeGemini:
    def __init__(self) -> None:
        self.calls = 0

    def create_card(self, word: str):
        self.calls += 1
        assert word == "leverage"
        return make_card()


class PhraseGemini(FakeGemini):
    def create_card(self, word: str):
        self.calls += 1
        assert word == "canonical record"
        return make_card().model_copy(update={"word": word})


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict | None]] = []
        self.callback_answers: list[tuple[str, str]] = []
        self.removed_keyboards: list[tuple[int, int]] = []

    def send_message(self, chat_id: int, text: str, *, reply_markup: dict | None = None) -> None:
        self.messages.append((chat_id, text, reply_markup))

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        self.callback_answers.append((callback_query_id, text))

    def remove_inline_keyboard(self, chat_id: int, message_id: int) -> None:
        self.removed_keyboards.append((chat_id, message_id))


class FakeReviewTaskQueue:
    def __init__(self) -> None:
        self.tasks: list[tuple[ReviewTaskPayload, str]] = []

    def enqueue(self, payload: ReviewTaskPayload, *, delivery_key: str) -> None:
        self.tasks.append((payload, delivery_key))


class CallbackAckFailingTelegram(FakeTelegram):
    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        raise TelegramError("Telegram answerCallbackQuery failed: query is too old")


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


def test_multi_word_term_is_generated_and_saved_as_one_entry() -> None:
    repository = FakeRepository()
    gemini = PhraseGemini()
    telegram = FakeTelegram()
    service = VocabularyService(
        repository=repository,
        gemini=gemini,
        telegram=telegram,
        owner_chat_id=123,
        review_size=2,
        timezone="Asia/Taipei",
    )

    service.handle_update(
        {
            "update_id": 107,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "text": "  Canonical   Record ",
            },
        }
    )

    assert gemini.calls == 1
    assert repository.saved_cards == 1
    assert repository.get_word("canonical record") is not None
    assert "正在整理 <b>canonical record</b>" in telegram.messages[0][1]


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
    assert "已儲存詞彙" in telegram.messages[0][1]
    assert "leverage" in telegram.messages[0][1]


def test_search_returns_one_stored_word_without_writing_or_calling_gemini() -> None:
    service, repository, gemini, telegram = make_service()
    repository.words = card_to_words(make_card())

    service.handle_update(
        {
            "update_id": 104,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "text": "/search Leverage",
            },
        }
    )

    assert gemini.calls == 0
    assert repository.saved_cards == 0
    assert len(repository.words) == 4
    assert len(telegram.messages) == 1
    assert "<b>leverage</b>" in telegram.messages[0][1]
    assert "中文釋義" in telegram.messages[0][1]


def test_search_returns_a_saved_multi_word_term_without_writing() -> None:
    service, repository, gemini, telegram = make_service()
    repository.words = card_to_words(make_card().model_copy(update={"word": "canonical record"}))

    service.handle_update(
        {
            "update_id": 108,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "text": "/search Canonical   Record",
            },
        }
    )

    assert gemini.calls == 0
    assert repository.saved_cards == 0
    assert "<b>canonical record</b>" in telegram.messages[0][1]


def test_search_missing_word_does_not_add_it() -> None:
    service, repository, gemini, telegram = make_service()
    repository.words = card_to_words(make_card())

    service.handle_update(
        {
            "update_id": 105,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "text": "/search apple",
            },
        }
    )

    assert gemini.calls == 0
    assert repository.saved_cards == 0
    assert repository.get_word("apple") is None
    assert "找不到 <b>apple</b>" in telegram.messages[0][1]


def test_search_requires_one_valid_term() -> None:
    service, repository, gemini, telegram = make_service()

    service.handle_update(
        {
            "update_id": 106,
            "message": {"chat": {"id": 123, "type": "private"}, "text": "/search"},
        }
    )

    assert gemini.calls == 0
    assert repository.saved_cards == 0
    assert "/search canonical record" in telegram.messages[0][1]


def test_removed_stats_command_is_not_routed() -> None:
    service, repository, gemini, telegram = make_service()
    repository.words = card_to_words(make_card())

    service.handle_update(
        {
            "update_id": 103,
            "message": {"chat": {"id": 123, "type": "private"}, "text": "/stats"},
        }
    )

    assert gemini.calls == 0
    assert len(telegram.messages) == 1
    assert "英文單字或片語" in telegram.messages[0][1]
    assert "資料庫共有" not in telegram.messages[0][1]


def test_scheduled_delivery_is_idempotent_for_the_day() -> None:
    service, repository, _, telegram = make_service()
    repository.words = card_to_words(make_card())
    first = service.send_review()
    message_count = len(telegram.messages)
    second = service.send_review()
    assert first == second
    assert len(first) == 2
    assert len(telegram.messages) == message_count
    assert telegram.messages[0][2] is not None
    assert repository.words[0].review_count == 0


def test_review_queue_returns_without_sending_telegram_messages() -> None:
    service, repository, _, telegram = make_service()
    queue = FakeReviewTaskQueue()
    service.review_task_queue = queue
    repository.words = card_to_words(make_card())

    selected = service.send_review(force=True, delivery_key="telegram-321")

    assert len(selected) == 2
    assert not telegram.messages
    assert [task.item.word for task, _ in queue.tasks] == selected
    assert {delivery_key for _, delivery_key in queue.tasks} == {"telegram-321"}


def test_review_worker_sends_exactly_one_card() -> None:
    service, repository, _, telegram = make_service()
    item = card_to_words(make_card())[0]
    repository.words = [item]

    service.send_review_card(ReviewTaskPayload(chat_id=123, item=item))

    assert len(telegram.messages) == 1
    assert telegram.messages[0][0] == 123
    assert telegram.messages[0][2] is not None


def test_review_worker_skips_a_word_deleted_after_enqueue() -> None:
    service, repository, _, telegram = make_service()
    item = card_to_words(make_card())[0]

    service.send_review_card(ReviewTaskPayload(chat_id=123, item=item))

    assert not telegram.messages


def test_review_worker_rejects_a_different_chat() -> None:
    service, repository, _, telegram = make_service()
    item = card_to_words(make_card())[0]

    try:
        service.send_review_card(ReviewTaskPayload(chat_id=999, item=item))
    except ValueError as exc:
        assert "owner" in str(exc)
    else:
        raise AssertionError("Expected a mismatched review task chat to be rejected")

    assert not telegram.messages


def test_review_callback_grades_word_once_and_removes_buttons() -> None:
    service, repository, _, telegram = make_service()
    repository.words = card_to_words(make_card())
    update = {
        "update_id": 200,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": 123},
            "data": "review:g:leverage",
            "message": {
                "message_id": 55,
                "chat": {"id": 123, "type": "private"},
            },
        },
    }

    service.handle_update(update)
    service.handle_update(
        {
            **update,
            "update_id": 201,
            "callback_query": {**update["callback_query"], "id": "callback-2"},
        }
    )

    reviewed = next(item for item in repository.words if item.word == "leverage")
    assert reviewed.review_count == 1
    assert reviewed.interval_days == 3
    assert "Good" in telegram.callback_answers[0][1]
    assert "已評分" in telegram.callback_answers[1][1]
    assert telegram.removed_keyboards == [(123, 55), (123, 55)]


def test_clear_command_requires_explicit_confirmation() -> None:
    service, repository, _, telegram = make_service()
    repository.words = card_to_words(make_card())

    service.handle_update(
        {
            "update_id": 300,
            "message": {"chat": {"id": 123, "type": "private"}, "text": "/clear"},
        }
    )

    assert repository.clear_calls == 0
    assert len(repository.words) == 4
    keyboard = telegram.messages[-1][2]
    assert keyboard is not None
    assert [button["text"] for button in keyboard["inline_keyboard"][0]] == [
        "確認清空",
        "取消",
    ]


def test_clear_confirmation_deletes_learning_data() -> None:
    service, repository, _, telegram = make_service()
    repository.words = card_to_words(make_card())
    repository.deliveries["2026-09-27"] = DailyDelivery(date="2026-09-27", words=["leverage"])
    repository.pending["retry"] = PendingWord(
        word="retry",
        chat_id=123,
        last_error_code="timeout",
        next_attempt_at=datetime.now(UTC),
    )

    service.handle_update(
        {
            "update_id": 301,
            "callback_query": {
                "id": "clear-callback",
                "from": {"id": 123},
                "data": "clear:confirm",
                "message": {
                    "message_id": 60,
                    "chat": {"id": 123, "type": "private"},
                },
            },
        }
    )

    assert repository.clear_calls == 1
    assert not repository.words
    assert not repository.deliveries
    assert not repository.pending
    assert telegram.removed_keyboards == [(123, 60)]
    assert "4</b> 個詞彙" in telegram.messages[-1][1]


def test_clear_cancellation_preserves_learning_data() -> None:
    service, repository, _, telegram = make_service()
    repository.words = card_to_words(make_card())

    service.handle_update(
        {
            "update_id": 302,
            "callback_query": {
                "id": "cancel-callback",
                "from": {"id": 123},
                "data": "clear:cancel",
                "message": {
                    "message_id": 61,
                    "chat": {"id": 123, "type": "private"},
                },
            },
        }
    )

    assert repository.clear_calls == 0
    assert len(repository.words) == 4
    assert telegram.removed_keyboards == [(123, 61)]


def test_expired_callback_ack_does_not_hide_a_successful_grade() -> None:
    service, repository, _, _ = make_service()
    telegram = CallbackAckFailingTelegram()
    service.telegram = telegram
    repository.words = card_to_words(make_card())

    service.handle_update(
        {
            "update_id": 202,
            "callback_query": {
                "id": "expired-callback",
                "from": {"id": 123},
                "data": "review:e:leverage",
                "message": {
                    "message_id": 56,
                    "chat": {"id": 123, "type": "private"},
                },
            },
        }
    )

    reviewed = next(item for item in repository.words if item.word == "leverage")
    assert reviewed.review_count == 1
    assert reviewed.interval_days == 7
    assert telegram.removed_keyboards == [(123, 56)]


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
