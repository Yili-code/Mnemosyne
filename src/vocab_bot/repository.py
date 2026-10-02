from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from google.cloud import firestore

from vocab_bot.models import DailyDelivery, PendingWord, StoredWord, VocabularyCard
from vocab_bot.spaced_repetition import ReviewGrade, is_due, schedule_review, select_due_words


class Repository(Protocol):
    def claim_update(self, update_id: int) -> bool: ...

    def save_card(self, card: VocabularyCard) -> None: ...

    def list_words(self) -> list[StoredWord]: ...

    def get_word(self, word: str) -> StoredWord | None: ...

    def list_due_words(self, now: datetime, limit: int) -> list[StoredWord]: ...

    def grade_review(
        self, word: str, grade: ReviewGrade, reviewed_at: datetime
    ) -> StoredWord | None: ...

    def get_delivery(self, date: str) -> DailyDelivery | None: ...

    def save_delivery(self, delivery: DailyDelivery) -> None: ...

    def enqueue_retry(self, pending: PendingWord) -> None: ...

    def claim_due_retry(self, now: datetime) -> PendingWord | None: ...

    def reschedule_retry(self, pending: PendingWord) -> None: ...

    def delete_retry(self, word: str) -> None: ...

    def clear_user_data(self) -> dict[str, int]: ...


def card_to_words(card: VocabularyCard) -> list[StoredWord]:
    now = datetime.now(UTC)
    main = StoredWord(
        word=card.word,
        kk_phonetic=card.kk_phonetic,
        part_of_speech=card.part_of_speech,
        meanings_zh=card.meanings_zh,
        usage_notes=card.usage_notes,
        collocations=card.collocations,
        examples=card.examples,
        related_words=card.related_words,
        updated_at=now,
    )
    seeds = [
        StoredWord(
            word=item.word,
            kk_phonetic=item.kk_phonetic,
            part_of_speech=item.part_of_speech,
            meanings_zh=[item.meaning_zh],
            usage_notes=[item.connection],
            examples=[item.example],
            source_word=card.word,
            is_related_seed=True,
            created_at=now,
            updated_at=now,
        )
        for item in card.related_words
    ]
    return [main, *seeds]


def preserve_learning_state(incoming: StoredWord, existing: StoredWord) -> None:
    incoming.created_at = existing.created_at
    incoming.review_count = existing.review_count
    incoming.lapse_count = existing.lapse_count
    incoming.interval_days = existing.interval_days
    incoming.ease_factor = existing.ease_factor
    incoming.last_reviewed_at = existing.last_reviewed_at
    incoming.due_at = existing.due_at


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS words (
                word TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS updates (
                update_id INTEGER PRIMARY KEY,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                date TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_words (
                word TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            """
        )

    def claim_update(self, update_id: int) -> bool:
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO updates(update_id, received_at) VALUES (?, ?)",
                    (update_id, datetime.now(UTC).isoformat()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def save_card(self, card: VocabularyCard) -> None:
        with self.connection:
            for incoming in card_to_words(card):
                row = self.connection.execute(
                    "SELECT payload FROM words WHERE word = ?", (incoming.word,)
                ).fetchone()
                if row:
                    existing = StoredWord.model_validate_json(row[0])
                    preserve_learning_state(incoming, existing)
                    if not incoming.is_related_seed or existing.is_related_seed:
                        value = incoming
                    else:
                        value = existing
                else:
                    value = incoming
                self.connection.execute(
                    "INSERT OR REPLACE INTO words(word, payload) VALUES (?, ?)",
                    (value.word, value.model_dump_json()),
                )

    def list_words(self) -> list[StoredWord]:
        rows = self.connection.execute("SELECT payload FROM words ORDER BY word").fetchall()
        return [StoredWord.model_validate_json(row[0]) for row in rows]

    def get_word(self, word: str) -> StoredWord | None:
        row = self.connection.execute(
            "SELECT payload FROM words WHERE word = ?", (word,)
        ).fetchone()
        return StoredWord.model_validate_json(row[0]) if row else None

    def list_due_words(self, now: datetime, limit: int) -> list[StoredWord]:
        return select_due_words(self.list_words(), now=now, limit=limit)

    def grade_review(
        self, word: str, grade: ReviewGrade, reviewed_at: datetime
    ) -> StoredWord | None:
        with self.connection:
            row = self.connection.execute(
                "SELECT payload FROM words WHERE word = ?", (word,)
            ).fetchone()
            if not row:
                return None
            item = StoredWord.model_validate_json(row[0])
            if not is_due(item, reviewed_at):
                return None
            if grade is ReviewGrade.EASY:
                self.connection.execute("DELETE FROM words WHERE word = ?", (word,))
                return item
            scheduled = schedule_review(item, grade, reviewed_at=reviewed_at)
            self.connection.execute(
                "UPDATE words SET payload = ? WHERE word = ?",
                (scheduled.model_dump_json(), word),
            )
            return scheduled

    def get_delivery(self, date: str) -> DailyDelivery | None:
        row = self.connection.execute(
            "SELECT payload FROM deliveries WHERE date = ?", (date,)
        ).fetchone()
        return DailyDelivery.model_validate_json(row[0]) if row else None

    def save_delivery(self, delivery: DailyDelivery) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO deliveries(date, payload) VALUES (?, ?)",
                (delivery.date, delivery.model_dump_json()),
            )

    def enqueue_retry(self, pending: PendingWord) -> None:
        row = self.connection.execute(
            "SELECT payload FROM pending_words WHERE word = ?", (pending.word,)
        ).fetchone()
        if row:
            existing = PendingWord.model_validate_json(row[0])
            pending.created_at = existing.created_at
            pending.attempt_count = max(existing.attempt_count, pending.attempt_count)
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO pending_words(word, payload) VALUES (?, ?)",
                (pending.word, pending.model_dump_json()),
            )

    def claim_due_retry(self, now: datetime) -> PendingWord | None:
        with self.connection:
            rows = self.connection.execute("SELECT payload FROM pending_words").fetchall()
            pending = sorted(
                (
                    PendingWord.model_validate_json(row[0])
                    for row in rows
                    if PendingWord.model_validate_json(row[0]).next_attempt_at <= now
                ),
                key=lambda item: item.next_attempt_at,
            )
            if not pending:
                return None
            claimed = pending[0].model_copy(update={"next_attempt_at": now + timedelta(minutes=5)})
            self.connection.execute(
                "UPDATE pending_words SET payload = ? WHERE word = ?",
                (claimed.model_dump_json(), claimed.word),
            )
            return claimed

    def reschedule_retry(self, pending: PendingWord) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO pending_words(word, payload) VALUES (?, ?)",
                (pending.word, pending.model_dump_json()),
            )

    def delete_retry(self, word: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM pending_words WHERE word = ?", (word,))

    def clear_user_data(self) -> dict[str, int]:
        with self.connection:
            counts = {
                "words": self.connection.execute("SELECT COUNT(*) FROM words").fetchone()[0],
                "pending_words": self.connection.execute(
                    "SELECT COUNT(*) FROM pending_words"
                ).fetchone()[0],
                "deliveries": self.connection.execute("SELECT COUNT(*) FROM deliveries").fetchone()[
                    0
                ],
            }
            self.connection.execute("DELETE FROM words")
            self.connection.execute("DELETE FROM pending_words")
            self.connection.execute("DELETE FROM deliveries")
        return counts


class FirestoreRepository:
    def __init__(self, project: str | None = None) -> None:
        self.client = firestore.Client(project=project)

    def claim_update(self, update_id: int) -> bool:
        ref = self.client.collection("telegram_updates").document(str(update_id))
        try:
            ref.create({"received_at": firestore.SERVER_TIMESTAMP})
            return True
        except Exception as exc:  # Google exposes AlreadyExists through transport layers.
            if exc.__class__.__name__ == "AlreadyExists":
                return False
            raise

    def save_card(self, card: VocabularyCard) -> None:
        batch = self.client.batch()
        for incoming in card_to_words(card):
            ref = self.client.collection("words").document(incoming.word)
            snapshot = ref.get()
            if snapshot.exists:
                existing = StoredWord.model_validate(snapshot.to_dict())
                preserve_learning_state(incoming, existing)
                if incoming.is_related_seed and not existing.is_related_seed:
                    continue
            batch.set(ref, incoming.model_dump(mode="json"))
        batch.commit()

    def list_words(self) -> list[StoredWord]:
        documents = self.client.collection("words").stream()
        return [StoredWord.model_validate(doc.to_dict()) for doc in documents]

    def get_word(self, word: str) -> StoredWord | None:
        snapshot = self.client.collection("words").document(word).get()
        return StoredWord.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def list_due_words(self, now: datetime, limit: int) -> list[StoredWord]:
        # Filtering in Python keeps older Firestore documents compatible because
        # records created before due_at existed have no queryable due_at field.
        return select_due_words(self.list_words(), now=now, limit=limit)

    def grade_review(
        self, word: str, grade: ReviewGrade, reviewed_at: datetime
    ) -> StoredWord | None:
        ref = self.client.collection("words").document(word)
        transaction = self.client.transaction()

        @firestore.transactional
        def grade_once(current_transaction):
            snapshot = ref.get(transaction=current_transaction)
            if not snapshot.exists:
                return None
            item = StoredWord.model_validate(snapshot.to_dict())
            if not is_due(item, reviewed_at):
                return None
            if grade is ReviewGrade.EASY:
                current_transaction.delete(ref)
                return item
            scheduled = schedule_review(item, grade, reviewed_at=reviewed_at)
            current_transaction.set(ref, scheduled.model_dump(mode="json"))
            return scheduled

        return grade_once(transaction)

    def get_delivery(self, date: str) -> DailyDelivery | None:
        snapshot = self.client.collection("daily_deliveries").document(date).get()
        return DailyDelivery.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def save_delivery(self, delivery: DailyDelivery) -> None:
        self.client.collection("daily_deliveries").document(delivery.date).set(
            delivery.model_dump(mode="json")
        )

    def enqueue_retry(self, pending: PendingWord) -> None:
        ref = self.client.collection("pending_words").document(pending.word)
        snapshot = ref.get()
        if snapshot.exists:
            existing = PendingWord.model_validate(snapshot.to_dict())
            pending.created_at = existing.created_at
            pending.attempt_count = max(existing.attempt_count, pending.attempt_count)
        ref.set(pending.model_dump(mode="json"))

    def claim_due_retry(self, now: datetime) -> PendingWord | None:
        query = (
            self.client.collection("pending_words")
            .where(filter=firestore.FieldFilter("next_attempt_at", "<=", now.isoformat()))
            .order_by("next_attempt_at")
            .limit(5)
        )
        for candidate in query.stream():
            ref = candidate.reference
            transaction = self.client.transaction()

            @firestore.transactional
            def claim(current_transaction, retry_ref=ref):
                snapshot = retry_ref.get(transaction=current_transaction)
                if not snapshot.exists:
                    return None
                pending = PendingWord.model_validate(snapshot.to_dict())
                if pending.next_attempt_at > now:
                    return None
                claimed = pending.model_copy(update={"next_attempt_at": now + timedelta(minutes=5)})
                current_transaction.set(retry_ref, claimed.model_dump(mode="json"))
                return claimed

            claimed = claim(transaction)
            if claimed is not None:
                return claimed
        return None

    def reschedule_retry(self, pending: PendingWord) -> None:
        self.client.collection("pending_words").document(pending.word).set(
            pending.model_dump(mode="json")
        )

    def delete_retry(self, word: str) -> None:
        self.client.collection("pending_words").document(word).delete()

    def clear_user_data(self) -> dict[str, int]:
        return {
            "words": self._delete_collection("words"),
            "pending_words": self._delete_collection("pending_words"),
            "deliveries": self._delete_collection("daily_deliveries"),
        }

    def _delete_collection(self, name: str) -> int:
        deleted = 0
        collection = self.client.collection(name)
        while True:
            documents = list(collection.limit(450).stream())
            if not documents:
                return deleted
            batch = self.client.batch()
            for document in documents:
                batch.delete(document.reference)
            batch.commit()
            deleted += len(documents)


def dump_words(words: Sequence[StoredWord]) -> str:
    """Useful for diagnostics without exposing secrets."""
    return json.dumps([word.model_dump(mode="json") for word in words], ensure_ascii=False)
