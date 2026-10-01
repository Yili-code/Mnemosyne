from __future__ import annotations

import httpx

from vocab_bot.gemini import QUESTION_SYSTEM_PROMPT, SYSTEM_PROMPT, GeminiClient
from vocab_bot.models import RelatedWord

from .test_repository import make_card


def test_prompts_forbid_simplified_chinese() -> None:
    for prompt in (SYSTEM_PROMPT, QUESTION_SYSTEM_PROMPT):
        assert "Never output" in prompt
        assert "Simplified Chinese" in prompt


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
    related_schema = config["responseJsonSchema"]["properties"]["related_words"]
    assert related_schema["maxItems"] == 3
    assert "minItems" not in related_schema


def test_create_card_preserves_a_multi_word_term(monkeypatch) -> None:
    term = "canonical record"

    def fake_post(url, *, params, json, timeout):
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
                                    .model_copy(update={"word": term})
                                    .model_dump_json()
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    card = GeminiClient("test-key", "test-model").create_card(term)

    assert card.word == term


def test_create_card_accepts_fewer_than_three_quality_related_words(monkeypatch) -> None:
    card = make_card()
    one_related_word: list[RelatedWord] = card.related_words[:1]

    def fake_post(url, *, params, json, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": card.model_copy(
                                        update={"related_words": one_related_word}
                                    ).model_dump_json()
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = GeminiClient("test-key", "test-model").create_card("leverage")

    assert [item.word for item in result.related_words] == ["utilize"]


def test_answer_question_uses_structured_output(monkeypatch) -> None:
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
                                    "text": '{"answer":"An assignment is a specific task; '
                                    'homework is work done outside class."}'
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    answer = GeminiClient("test-key", "test-model").answer_question(
        "What's the difference between assignment and homework?"
    )

    assert answer.startswith("An assignment")
    assert captured["contents"][0]["parts"][0]["text"].startswith("What's the difference")
    assert "responseJsonSchema" in captured["generationConfig"]
