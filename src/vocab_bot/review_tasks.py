from __future__ import annotations

import hashlib
import json
from typing import Protocol

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from vocab_bot.models import ReviewTaskPayload


class ReviewTaskQueue(Protocol):
    def enqueue(self, payload: ReviewTaskPayload, *, delivery_key: str) -> None: ...


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
        digest = hashlib.sha256(f"{delivery_key}:{payload.item.word}".encode()).hexdigest()[:32]
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
