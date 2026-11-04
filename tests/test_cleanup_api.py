from types import SimpleNamespace

from fastapi.testclient import TestClient

from vocab_bot import app as module


def test_cleanup_api_checks_secret_and_owner_before_deleting(monkeypatch):
    calls = []

    def cleanup(payload):
        if payload.chat_id != 123:
            raise ValueError("owner mismatch")
        calls.append(payload)
        return False

    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(cron_secret="test-secret"))
    monkeypatch.setattr(
        module, "get_service", lambda: SimpleNamespace(cleanup_review_message=cleanup)
    )
    client = TestClient(module.app)
    payload = {"chat_id": 123, "batch_id": "a" * 24, "message_id": 99}
    assert client.post("/tasks/cleanup-review", json=payload).status_code == 401
    assert not calls
    headers = {"X-Cron-Secret": "test-secret"}
    assert (
        client.post(
            "/tasks/cleanup-review", json={**payload, "chat_id": 999}, headers=headers
        ).status_code
        == 403
    )
    assert not calls
    assert client.post("/tasks/cleanup-review", json=payload, headers=headers).json() == {
        "ok": True,
        "deleted": False,
    }
    assert len(calls) == 1
