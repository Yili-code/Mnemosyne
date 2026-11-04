from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from google.cloud import firestore

from vocab_bot.batch_review import advance_batch, complete_batch, expire_unanswered, record_message
from vocab_bot.models import ReviewBatch, StoredWord


class SQLiteBatchStore:
    @contextmanager
    def batch_transaction(self):
        # Separate connections serialize writers across threads and processes. Reads must
        # happen after BEGIN IMMEDIATE so completion cannot commit a stale partial grade.
        connection = sqlite3.connect(self.batch_path, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_review_batch(self, batch: ReviewBatch) -> ReviewBatch:
        with self.batch_transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO review_batches(id, payload) VALUES (?, ?)",
                (batch.id, batch.model_dump_json()),
            )
            row = connection.execute(
                "SELECT payload FROM review_batches WHERE id = ?", (batch.id,)
            ).fetchone()
            return ReviewBatch.model_validate_json(row[0])

    def get_review_batch(self, batch_id: str) -> ReviewBatch | None:
        with self.batch_transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM review_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            return ReviewBatch.model_validate_json(row[0]) if row else None

    def record_review_message(
        self, batch_id: str, message_id: int, sent_at: datetime
    ) -> ReviewBatch | None:
        return self._change_review_message(batch_id, message_id, sent_at, expire=False)

    def expire_review_message(
        self, batch_id: str, message_id: int, now: datetime
    ) -> ReviewBatch | None:
        return self._change_review_message(batch_id, message_id, now, expire=True)

    def _change_review_message(self, batch_id, message_id, now, *, expire):
        with self.batch_transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM review_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                return None
            batch = ReviewBatch.model_validate_json(row[0])
            change = expire_unanswered if expire else record_message
            updated = change(batch, message_id, now)
            connection.execute(
                "UPDATE review_batches SET payload = ? WHERE id = ?",
                (updated.model_dump_json(), batch_id),
            )
            return updated

    def update_review_batch(
        self, batch_id: str, revision: int, action: str, now: datetime
    ) -> ReviewBatch | None:
        with self.batch_transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM review_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                return None
            original = ReviewBatch.model_validate_json(row[0])
            batch = advance_batch(original, revision, action, now)
            if batch.revision == original.revision:
                return batch
            if batch.stage == "completed":
                current = {}
                for item in batch.items:
                    row = connection.execute(
                        "SELECT payload FROM words WHERE word = ?", (item.word,)
                    ).fetchone()
                    if row:
                        current[item.word] = StoredWord.model_validate_json(row[0])
                for item in complete_batch(batch, current, now):
                    connection.execute(
                        "UPDATE words SET payload = ? WHERE word = ?",
                        (item.model_dump_json(), item.word),
                    )
            connection.execute(
                "UPDATE review_batches SET payload = ? WHERE id = ?",
                (batch.model_dump_json(), batch.id),
            )
            return batch


class FirestoreBatchStore:
    def create_review_batch(self, batch: ReviewBatch) -> ReviewBatch:
        ref = self.client.collection("review_batches").document(batch.id)
        transaction = self.client.transaction()

        @firestore.transactional
        def create(current_transaction):
            snapshot = ref.get(transaction=current_transaction)
            if snapshot.exists:
                return ReviewBatch.model_validate(snapshot.to_dict())
            current_transaction.set(ref, batch.model_dump(mode="json"))
            return batch

        return create(transaction)

    def get_review_batch(self, batch_id: str) -> ReviewBatch | None:
        snapshot = self.client.collection("review_batches").document(batch_id).get()
        return ReviewBatch.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def record_review_message(
        self, batch_id: str, message_id: int, sent_at: datetime
    ) -> ReviewBatch | None:
        return self._change_review_message(batch_id, message_id, sent_at, expire=False)

    def expire_review_message(
        self, batch_id: str, message_id: int, now: datetime
    ) -> ReviewBatch | None:
        return self._change_review_message(batch_id, message_id, now, expire=True)

    def _change_review_message(self, batch_id, message_id, now, *, expire):
        ref = self.client.collection("review_batches").document(batch_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def change_message(current_transaction):
            snapshot = ref.get(transaction=current_transaction)
            if not snapshot.exists:
                return None
            batch = ReviewBatch.model_validate(snapshot.to_dict())
            change = expire_unanswered if expire else record_message
            updated = change(batch, message_id, now)
            if updated != batch:
                current_transaction.set(ref, updated.model_dump(mode="json"))
            return updated

        return change_message(transaction)

    def update_review_batch(
        self, batch_id: str, revision: int, action: str, now: datetime
    ) -> ReviewBatch | None:
        ref = self.client.collection("review_batches").document(batch_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def update(current_transaction):
            snapshot = ref.get(transaction=current_transaction)
            if not snapshot.exists:
                return None
            original = ReviewBatch.model_validate(snapshot.to_dict())
            batch = advance_batch(original, revision, action, now)
            if batch.revision == original.revision:
                return batch
            if batch.stage == "completed":
                current = {}
                refs = {}
                # Firestore requires all reads before the first write.
                for item in batch.items:
                    word_ref = self.client.collection("words").document(item.word)
                    refs[item.word] = word_ref
                    word_snapshot = word_ref.get(transaction=current_transaction)
                    if word_snapshot.exists:
                        current[item.word] = StoredWord.model_validate(word_snapshot.to_dict())
                for item in complete_batch(batch, current, now):
                    current_transaction.set(refs[item.word], item.model_dump(mode="json"))
            current_transaction.set(ref, batch.model_dump(mode="json"))
            return batch

        return update(transaction)
