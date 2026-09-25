from __future__ import annotations

import json

import httpx

from vocab_bot.models import VocabularyCard
from vocab_bot.word_rules import filter_related

SYSTEM_PROMPT = """You create precise vocabulary cards for a Taiwanese university student.
Return Traditional Chinese explanations and natural English examples.

For related_words, choose independent vocabulary that is semantically connected to the input
and is genuinely useful in TOEIC, IELTS, or everyday English. Do NOT label words as TOEIC,
IELTS, or Daily. Do NOT return grammatical forms or routine members of the same word family,
including plurals, tense forms, -ing forms, ordinary noun/verb/adjective/adverb derivations.
Prefer synonyms, antonyms, common contrasts, conceptually adjacent words, or words commonly
used in the same situation. A derivation is allowed only when its meaning is unusually distinct
and worth learning independently; then set exceptional_derivation=true and explain why.

Do not invent uncommon senses. Keep usage notes practical and concise. Return the headword in
lowercase and exactly 5 related words when possible."""


class GeminiError(RuntimeError):
    def __init__(self, message: str, *, code: str = "unknown") -> None:
        super().__init__(message)
        self.code = code


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def create_card(self, word: str) -> VocabularyCard:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )
        schema = VocabularyCard.model_json_schema()
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"Create a vocabulary card for: {word}"}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.25,
                "maxOutputTokens": 2500,
            },
        }
        try:
            response = httpx.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            card = VocabularyCard.model_validate(json.loads(text))
        except httpx.TimeoutException as exc:
            raise GeminiError("Gemini request timed out", code="timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise GeminiError(
                "Gemini returned an HTTP error",
                code=f"http_{exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiError("Gemini transport failed", code="transport") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GeminiError(
                "Gemini could not create a valid vocabulary card",
                code="invalid_response",
            ) from exc

        if card.word != word:
            raise GeminiError("Gemini returned a different headword", code="wrong_headword")
        filtered = filter_related(word, card.related_words)
        if len(filtered) < 3:
            raise GeminiError(
                "Gemini returned too few valid independent related words",
                code="too_few_related_words",
            )
        return card.model_copy(update={"related_words": filtered})
