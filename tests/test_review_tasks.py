import json

from google.api_core.exceptions import AlreadyExists

from vocab_bot.models import ReviewTaskPayload
from vocab_bot.repository import card_to_words
from vocab_bot.review_tasks import CloudTasksReviewQueue

from .test_repository import make_card


class FakeCloudTasksClient:
    def __init__(self, *, already_exists: bool = False) -> None:
        self.already_exists = already_exists
        self.created = []

    def queue_path(self, project: str, location: str, queue: str) -> str:
        return f"projects/{project}/locations/{location}/queues/{queue}"

    def create_task(self, *, parent: str, task) -> None:
        if self.already_exists:
            raise AlreadyExists("duplicate")
        self.created.append((parent, task))


def make_queue(monkeypatch, client: FakeCloudTasksClient) -> CloudTasksReviewQueue:
    monkeypatch.setattr(
        "vocab_bot.review_tasks.tasks_v2.CloudTasksClient",
        lambda: client,
    )
    return CloudTasksReviewQueue(
        project="project-id",
        location="asia-east1",
        queue="mnemosyne-review",
        service_url="https://example.run.app/",
        cron_secret="secret-value",
    )


def test_cloud_tasks_queue_builds_a_protected_worker_request(monkeypatch) -> None:
    client = FakeCloudTasksClient()
    queue = make_queue(monkeypatch, client)
    payload = ReviewTaskPayload(chat_id=123, item=card_to_words(make_card())[0])

    queue.enqueue(payload, delivery_key="telegram-321")

    parent, task = client.created[0]
    assert parent.endswith("/queues/mnemosyne-review")
    assert task.name.startswith(f"{parent}/tasks/review-")
    assert task.http_request.url == "https://example.run.app/tasks/send-review-card"
    assert task.http_request.headers["X-Cron-Secret"] == "secret-value"
    assert json.loads(task.http_request.body)["item"]["word"] == "leverage"


def test_cloud_tasks_queue_treats_a_duplicate_task_as_success(monkeypatch) -> None:
    queue = make_queue(monkeypatch, FakeCloudTasksClient(already_exists=True))
    payload = ReviewTaskPayload(chat_id=123, item=card_to_words(make_card())[0])

    queue.enqueue(payload, delivery_key="telegram-321")
