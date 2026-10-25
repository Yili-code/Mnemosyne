from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from vocab_bot.batch_review import decode_batch_callback, make_batch
from vocab_bot.batch_store import FirestoreBatchStore
from vocab_bot.models import StoredWord
from vocab_bot.repository import SQLiteRepository
from vocab_bot.service import VocabularyService
from vocab_bot.spaced_repetition import ReviewGrade
from vocab_bot.telegram import TelegramClient, TelegramError, render_review_batch

from .test_repository import make_card
from .test_service import FakeGemini, FakeReviewTaskQueue, FakeTelegram


class Snapshot:
    def __init__(self, value):
        self.value = copy.deepcopy(value)
        self.exists = value is not None

    def to_dict(self):
        return self.value


class Ref:
    def __init__(self, client, collection, key):
        self.client, self.path = client, (collection, key)

    def get(self, transaction=None):
        if transaction:
            assert not transaction.writes, "Firestore reads must precede writes"
        return Snapshot(self.client.data.get(self.path))


class Collection:
    def __init__(self, client, name):
        self.client, self.name = client, name

    def document(self, key):
        return Ref(self.client, self.name, key)


class Transaction:
    def __init__(self, client):
        self.client, self.writes = client, []

    def set(self, ref, value):
        self.writes.append((ref.path, copy.deepcopy(value)))


class MemoryFirestore(FirestoreBatchStore):
    # Exercises the adapter's exact read/write transaction body without a network.
    def __init__(self):
        self.client = self
        self.data = {}

    def collection(self, name):
        return Collection(self, name)

    def transaction(self):
        return Transaction(self)

    def get_word(self, word):
        value = self.data.get(("words", word))
        return StoredWord.model_validate(value) if value else None


@pytest.fixture(params=["sqlite", "firestore"])
def store(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        repository = SQLiteRepository(tmp_path / "words.sqlite3")
        repository.save_card(make_card())
        yield repository
        repository.connection.close()
    else:
        from vocab_bot.repository import card_to_words

        def transactional(func):
            def run(transaction):
                result = func(transaction)
                for path, value in transaction.writes:
                    transaction.client.data[path] = value
                return result

            return run

        monkeypatch.setattr("vocab_bot.batch_store.firestore.transactional", transactional)
        repository = MemoryFirestore()
        for item in card_to_words(make_card()):
            repository.data[("words", item.word)] = item.model_dump(mode="json")
        yield repository


def create_batch(store, now=None):
    now = now or datetime.now(UTC)
    item = store.get_word("leverage")
    return store.create_review_batch(make_batch([item], "test-delivery", now))


def test_only_explicit_completion_changes_schedule(store):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    before = store.get_word("leverage")
    # Completion before reveal is rejected, even if all items would be remembered.
    assert store.update_review_batch(batch.id, 0, "done", now).stage == "prompt"
    assert store.get_word("leverage") == before
    batch = store.update_review_batch(batch.id, 0, "reveal", now)
    batch = store.update_review_batch(batch.id, batch.revision, "0", now)
    assert store.get_word("leverage") == before
    assert batch.unfamiliar == [0]
    batch = store.update_review_batch(batch.id, batch.revision, "done", now)
    reviewed = store.get_word("leverage")
    assert reviewed.review_count == 1
    assert reviewed.due_at == now + timedelta(minutes=10)
    assert batch.unfamiliar_count == 1
    # Replaying after the Again interval still cannot grade twice.
    repeated = store.update_review_batch(batch.id, 2, "done", now + timedelta(days=1))
    assert repeated == batch
    assert store.get_word("leverage") == reviewed


def test_remembered_words_are_rescheduled_and_never_deleted(store):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    store.update_review_batch(batch.id, 0, "reveal", now)
    completed = store.update_review_batch(batch.id, 1, "done", now)
    assert completed.remembered_count == 1
    item = store.get_word("leverage")
    assert item.review_count == 1
    assert item.due_at == now + timedelta(days=3)


def test_selection_can_be_undone_and_stale_revision_is_not_reapplied(store):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    store.update_review_batch(batch.id, 0, "reveal", now)
    selected = store.update_review_batch(batch.id, 1, "0", now)
    assert store.update_review_batch(batch.id, 1, "0", now) == selected
    assert store.update_review_batch(batch.id, 1, "done", now) == selected
    assert store.update_review_batch(batch.id, 2, "4", now) == selected
    deselected = store.update_review_batch(batch.id, 2, "0", now)
    assert deselected.unfamiliar == []
    assert store.get_word("leverage").review_count == 0


def test_expired_and_missing_batches_do_not_grade(store):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    expired = now + timedelta(days=8)
    assert store.update_review_batch(batch.id, 0, "reveal", expired) == batch
    assert store.update_review_batch("f" * 24, 0, "done", now) is None
    assert store.get_word("leverage").review_count == 0


def test_creating_same_batch_preserves_progress(store):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    revealed = store.update_review_batch(batch.id, 0, "reveal", now)
    assert store.create_review_batch(batch) == revealed
    assert store.get_review_batch(batch.id) == revealed


def test_stale_snapshot_does_not_overwrite_newer_review_even_when_due_again(store):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    store.update_review_batch(batch.id, 0, "reveal", now)
    if isinstance(store, SQLiteRepository):
        reviewed = store.grade_review("leverage", ReviewGrade.AGAIN, now)
    else:
        from vocab_bot.spaced_repetition import schedule_review

        reviewed = schedule_review(store.get_word("leverage"), ReviewGrade.AGAIN, reviewed_at=now)
        store.data[("words", "leverage")] = reviewed.model_dump(mode="json")
    completed = store.update_review_batch(batch.id, 1, "done", now + timedelta(hours=1))
    assert completed.skipped_count == 1
    assert store.get_word("leverage") == reviewed


def test_sqlite_restart_keeps_selection_and_completion(tmp_path):
    path = tmp_path / "words.sqlite3"
    first = SQLiteRepository(path)
    first.save_card(make_card())
    now = datetime.now(UTC)
    batch = create_batch(first, now)
    first.update_review_batch(batch.id, 0, "reveal", now)
    first.update_review_batch(batch.id, 1, "0", now)
    first.connection.close()
    second = SQLiteRepository(path)
    assert second.get_review_batch(batch.id).unfamiliar == [0]
    second.update_review_batch(batch.id, 2, "done", now)
    second.connection.close()
    third = SQLiteRepository(path)
    assert third.get_review_batch(batch.id).stage == "completed"
    assert third.get_word("leverage").review_count == 1
    third.connection.close()


def test_sqlite_concurrent_completion_grades_each_word_once(tmp_path):
    path = tmp_path / "words.sqlite3"
    repository = SQLiteRepository(path)
    repository.save_card(make_card())
    now = datetime.now(UTC)
    batch = create_batch(repository, now)
    repository.update_review_batch(batch.id, 0, "reveal", now)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: repository.update_review_batch(batch.id, 1, "done", now), range(4))
        )
    assert all(result.stage == "completed" for result in results)
    assert repository.get_word("leverage").review_count == 1
    repository.connection.close()


def test_sqlite_completion_rolls_back_every_word_and_session_on_failure(tmp_path):
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    now = datetime.now(UTC)
    items = repository.list_words()
    batch = repository.create_review_batch(make_batch(items, "rollback", now))
    repository.update_review_batch(batch.id, 0, "reveal", now)
    repository.connection.execute(
        "CREATE TRIGGER fail_batch BEFORE UPDATE ON review_batches "
        "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    repository.connection.commit()
    with pytest.raises(Exception, match="test failure"):
        repository.update_review_batch(batch.id, 1, "done", now)
    assert repository.get_review_batch(batch.id).stage == "revealed"
    assert all(item.review_count == 0 for item in repository.list_words())
    repository.connection.close()


def test_clear_invalidates_old_batches_and_readded_words(tmp_path):
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    now = datetime.now(UTC)
    batch = create_batch(repository, now)
    repository.clear_user_data()
    repository.save_card(make_card())
    assert repository.get_review_batch(batch.id) is None
    assert repository.update_review_batch(batch.id, 0, "done", now) is None
    assert repository.get_word("leverage").review_count == 0
    repository.connection.close()


def callback(data, sender=123, chat_type="private"):
    return {
        "update_id": 999,
        "callback_query": {
            "id": "query",
            "from": {"id": sender},
            "data": data,
            "message": {"message_id": 77, "chat": {"id": 123, "type": chat_type}},
        },
    }


def service_fixture(tmp_path, size=20):
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    telegram = FakeTelegram()
    service = VocabularyService(
        repository=repository,
        gemini=FakeGemini(),
        telegram=telegram,
        owner_chat_id=123,
        review_size=size,
        timezone="Asia/Taipei",
    )
    return service, repository, telegram


def test_service_batch_flow_updates_original_message(tmp_path):
    service, repository, telegram = service_fixture(tmp_path)
    selected = service.send_review(force=True, delivery_key="manual")
    assert len(telegram.messages) == 1
    prompt = telegram.messages[0]
    assert "leverage" in prompt[1]
    assert "槓桿" not in prompt[1]
    reveal = prompt[2]["inline_keyboard"][0][0]["callback_data"]
    service.handle_update(callback(reveal))
    buttons = telegram.edits[-1][3]["inline_keyboard"]
    assert len(buttons) == len(selected) + 1
    assert all(word.review_count == 0 for word in repository.list_words())
    service.handle_update(callback(buttons[0][0]["callback_data"]))
    done = telegram.edits[-1][3]["inline_keyboard"][-1][0]["callback_data"]
    service.handle_update(callback(done))
    assert "已完成" in telegram.edits[-1][2]
    assert telegram.edits[-1][3] == {"inline_keyboard": []}
    assert {word.review_count for word in repository.list_words()} == {1}
    service.handle_update(callback(done))
    assert {word.review_count for word in repository.list_words()} == {1}
    repository.connection.close()


@pytest.mark.parametrize("sender,chat_type", [(456, "private"), (123, "group")])
def test_service_rejects_non_owner_or_group_callbacks(tmp_path, sender, chat_type):
    service, repository, telegram = service_fixture(tmp_path)
    service.send_review(force=True)
    data = telegram.messages[0][2]["inline_keyboard"][0][0]["callback_data"]
    service.handle_update(callback(data, sender, chat_type))
    batch_id = decode_batch_callback(data)[0]
    assert repository.get_review_batch(batch_id).stage == "prompt"
    assert not telegram.edits
    repository.connection.close()


def test_large_daily_selection_uses_groups_of_five_and_queue_survives_restart(tmp_path):
    service, repository, telegram = service_fixture(tmp_path)
    now = datetime.now(UTC)
    for index in range(11):
        item = StoredWord(word=f"term{index}", meanings_zh=["測試"], due_at=now)
        repository.connection.execute(
            "INSERT INTO words VALUES (?, ?)", (item.word, item.model_dump_json())
        )
    repository.connection.commit()
    queue = FakeReviewTaskQueue()
    service.review_task_queue = queue
    chosen = service.send_review(force=True, delivery_key="queued")
    assert len(queue.tasks) == (len(chosen) + 4) // 5
    assert not telegram.messages
    ids = [payload.batch_id for payload, _ in queue.tasks]
    assert len(ids) == len(set(ids))
    assert all(1 <= len(repository.get_review_batch(key).items) <= 5 for key in ids)
    restarted = SQLiteRepository(tmp_path / "words.sqlite3")
    service.repository = restarted
    for payload, _ in queue.tasks:
        service.send_review_card(payload)
    assert len(telegram.messages) == len(queue.tasks)
    assert all(word.review_count == 0 for word in restarted.list_words())
    restarted.connection.close()
    repository.connection.close()


def test_completed_or_cleared_queued_batch_is_skipped(tmp_path):
    service, repository, telegram = service_fixture(tmp_path)
    queue = FakeReviewTaskQueue()
    service.review_task_queue = queue
    service.send_review(force=True)
    payload = queue.tasks[0][0]
    now = datetime.now(UTC)
    repository.update_review_batch(payload.batch_id, 0, "reveal", now)
    repository.update_review_batch(payload.batch_id, 1, "done", now)
    service.send_review_card(payload)
    repository.clear_user_data()
    service.send_review_card(payload)
    assert not telegram.messages
    with pytest.raises(ValueError, match="owner"):
        service.send_review_card(payload.model_copy(update={"chat_id": 456}))
    repository.connection.close()


def test_display_failure_keeps_durable_state_and_old_callback_repairs_ui(tmp_path):
    service, repository, telegram = service_fixture(tmp_path)
    service.send_review(force=True)
    data = telegram.messages[0][2]["inline_keyboard"][0][0]["callback_data"]
    original_edit = telegram.edit_message

    def fail(*args, **kwargs):
        raise TelegramError("test failure")

    telegram.edit_message = fail
    service.handle_update(callback(data))
    batch_id = decode_batch_callback(data)[0]
    assert repository.get_review_batch(batch_id).stage == "revealed"
    telegram.edit_message = original_edit
    service.handle_update(callback(data))
    assert "完成這組" in telegram.edits[-1][3]["inline_keyboard"][-1][0]["text"]
    assert repository.get_review_batch(batch_id).revision == 1
    repository.connection.close()


def test_batch_rendering_escapes_and_bounds_payload_and_callbacks():
    now = datetime.now(UTC)
    items = [StoredWord(word="<&'😀" * 200, meanings_zh=["<&'😀" * 1000]) for _ in range(5)]
    batch = make_batch(items, "long", now)
    for stage in ("prompt", "revealed"):
        batch.stage = stage
        text, markup = render_review_batch(batch)
        assert "&lt;" in text and "&amp;" in text
        assert len(text.encode("utf-16-le")) // 2 < 4096
        for row in markup["inline_keyboard"]:
            for button in row:
                assert len(button["callback_data"].encode()) <= 64
                assert decode_batch_callback(button["callback_data"]) is not None


@pytest.mark.parametrize(
    "value",
    [
        "batch:x:0:done",
        "batch:" + "a" * 24 + ":-1:0",
        "batch:" + "a" * 24 + ":0:5",
        "batch:" + "a" * 24 + ":9999999999:done",
    ],
)
def test_malformed_callbacks_are_rejected(value):
    assert decode_batch_callback(value) is None


def test_telegram_edit_uses_html_and_accepts_already_rendered_message(monkeypatch):
    calls = []
    client = TelegramClient("test")

    def post(method, payload):
        calls.append((method, payload))
        raise TelegramError("Telegram editMessageText failed: message is not modified")

    monkeypatch.setattr(client, "_post", post)
    client.edit_message(123, 77, "<b>答案</b>", reply_markup={"inline_keyboard": []})
    assert calls[0][0] == "editMessageText"
    assert calls[0][1]["parse_mode"] == "HTML"
    assert calls[0][1]["message_id"] == 77


def test_deleted_word_is_skipped_without_recreation(store):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    store.update_review_batch(batch.id, 0, "reveal", now)
    if isinstance(store, SQLiteRepository):
        with store.connection:
            store.connection.execute("DELETE FROM words WHERE word = ?", ("leverage",))
    else:
        del store.data[("words", "leverage")]
    result = store.update_review_batch(batch.id, 1, "done", now)
    assert result.skipped_count == 1
    assert result.remembered_count == result.unfamiliar_count == 0
    assert store.get_word("leverage") is None


@pytest.mark.parametrize("store", ["firestore"], indirect=True)
def test_firestore_failed_completion_does_not_commit_staged_word_writes(store, monkeypatch):
    now = datetime.now(UTC)
    batch = create_batch(store, now)
    store.update_review_batch(batch.id, 0, "reveal", now)
    original = Transaction.set

    def failing_set(self, ref, value):
        if ref.path[0] == "review_batches":
            raise RuntimeError("simulated session write failure")
        original(self, ref, value)

    monkeypatch.setattr(Transaction, "set", failing_set)
    with pytest.raises(RuntimeError, match="session write failure"):
        store.update_review_batch(batch.id, 1, "done", now)
    assert store.get_review_batch(batch.id).stage == "revealed"
    assert store.get_word("leverage").review_count == 0


def test_batch_completion_survives_expired_callback_ack(tmp_path):
    service, repository, telegram = service_fixture(tmp_path)
    service.send_review(force=True)
    reveal = telegram.messages[0][2]["inline_keyboard"][0][0]["callback_data"]
    service.handle_update(callback(reveal))
    done = telegram.edits[-1][3]["inline_keyboard"][-1][0]["callback_data"]

    def fail_ack(*args, **kwargs):
        raise TelegramError("query is too old")

    telegram.answer_callback_query = fail_ack
    service.handle_update(callback(done))
    service.handle_update(callback(done))
    assert all(item.review_count == 1 for item in repository.list_words())
    assert telegram.edits[-1][3] == {"inline_keyboard": []}
    repository.connection.close()
