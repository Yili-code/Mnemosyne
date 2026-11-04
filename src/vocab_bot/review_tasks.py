from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Protocol

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2
from google.protobuf.timestamp_pb2 import Timestamp

from vocab_bot.models import ReviewCleanupPayload, ReviewTaskPayload


class ReviewTaskQueue(Protocol):
    def enqueue(self, payload: ReviewTaskPayload, *, delivery_key: str) -> None: ...

    def enqueue_cleanup(self, payload: ReviewCleanupPayload, *, delete_at: datetime) -> None: ...


class CloudTasksReviewQueue:
    def __init__(
        self,
        *,
        project: str,
        location: str,
        queue: str,
        service_url: str,
        cron_secret: str,
    ) -> None:
        self.client = tasks_v2.CloudTasksClient()
        self.parent = self.client.queue_path(project, location, queue)
        self.endpoint = f"{service_url.rstrip('/')}/tasks/send-review-card"
        self.cron_secret = cron_secret

    def enqueue(self, payload: ReviewTaskPayload, *, delivery_key: str) -> None:
        identity = payload.batch_id or payload.item.word
        digest = hashlib.sha256(f"{delivery_key}:{identity}".encode()).hexdigest()[:32]
        task = tasks_v2.Task(
            name=f"{self.parent}/tasks/review-{digest}",
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=self.endpoint,
                headers={
                    "Content-Type": "application/json",
                    "X-Cron-Secret": self.cron_secret,
                },
                body=json.dumps(payload.model_dump(mode="json")).encode(),
            ),
        )
        try:
            self.client.create_task(parent=self.parent, task=task)
        except AlreadyExists:
            # A retried webhook or scheduler request should not duplicate a review card.
            return

    def enqueue_cleanup(self, payload: ReviewCleanupPayload, *, delete_at: datetime) -> None:
        identity = f"{payload.batch_id}:{payload.message_id}"
        digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
        scheduled = Timestamp()
        scheduled.FromDatetime(delete_at)
        task = tasks_v2.Task(
            name=f"{self.parent}/tasks/review-cleanup-{digest}",
            schedule_time=scheduled,
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=self.endpoint.rsplit("/", 1)[0] + "/cleanup-review",
                headers={"Content-Type": "application/json", "X-Cron-Secret": self.cron_secret},
                body=json.dumps(payload.model_dump(mode="json")).encode(),
            ),
        )
        try:
            self.client.create_task(parent=self.parent, task=task)
        except AlreadyExists:
            return
