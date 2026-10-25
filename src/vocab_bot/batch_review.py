from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta

from vocab_bot.models import ReviewBatch, StoredWord
from vocab_bot.spaced_repetition import ReviewGrade, is_due, schedule_review

BATCH_SIZE = 5
CALLBACK_PATTERN = re.compile(r"^batch:([a-f0-9]{24}):(\d{1,9}):(reveal|done|[0-4])$")


def make_batch(items: list[StoredWord], delivery_key: str, now: datetime) -> ReviewBatch:
    # Include learning state so a later review of the same expression has a new identity.
    identity = json.dumps(
        [delivery_key, [item.model_dump(mode="json") for item in items]], sort_keys=True
    )
    batch_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return ReviewBatch(id=batch_id, items=items, created_at=now, expires_at=now + timedelta(days=7))


def decode_batch_callback(value: str) -> tuple[str, int, str] | None:
    match = CALLBACK_PATTERN.fullmatch(value)
    return (match[1], int(match[2]), match[3]) if match else None


def advance_batch(batch: ReviewBatch, revision: int, action: str, now: datetime) -> ReviewBatch:
    result = batch.model_copy(deep=True)
    if batch.stage == "completed" or batch.expires_at <= now or batch.revision != revision:
        return result
    if action == "reveal" and batch.stage == "prompt":
        result.stage = "revealed"
    elif action == "done" and batch.stage == "revealed":
        result.stage = "completed"
    elif action in {"0", "1", "2", "3", "4"} and batch.stage == "revealed":
        index = int(action)
        if index >= len(batch.items):
            return result
        selected = set(batch.unfamiliar)
        if index in selected:
            selected.remove(index)
        else:
            selected.add(index)
        result.unfamiliar = sorted(selected)
    else:
        return result
    result.revision += 1
    return result


def complete_batch(
    batch: ReviewBatch, current_words: dict[str, StoredWord], now: datetime
) -> list[StoredWord]:
    scheduled = []
    for index, snapshot in enumerate(batch.items):
        current = current_words.get(snapshot.word)
        # A prior grade, deletion/recreation or card refresh invalidates this snapshot.
        if (
            current is None
            or not is_due(current, now)
            or any(
                getattr(current, field) != getattr(snapshot, field)
                for field in (
                    "created_at",
                    "updated_at",
                    "due_at",
                    "review_count",
                    "last_reviewed_at",
                )
            )
        ):
            batch.skipped_count += 1
            continue
        unfamiliar = index in batch.unfamiliar
        grade = ReviewGrade.AGAIN if unfamiliar else ReviewGrade.GOOD
        scheduled.append(schedule_review(current, grade, reviewed_at=now))
        if unfamiliar:
            batch.unfamiliar_count += 1
        else:
            batch.remembered_count += 1
    return scheduled
