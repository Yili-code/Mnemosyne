from __future__ import annotations

import httpx

from vocab_bot.gemini import GeminiClient

from .test_repository import make_card


def test_create_card_uses_json_schema_field(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, *, params, json, timeout):
        captured.update(json)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": make_card()
                                    .model_copy(update={"word": "protestation"})
                                    .model_dump_json()
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    GeminiClient("test-key", "test-model").create_card("protestation")

    config = captured["generationConfig"]
    assert "responseJsonSchema" in config
    assert "responseSchema" not in config
    assert "$defs" in config["responseJsonSchema"]
