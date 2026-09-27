import httpx
import pytest

from vocab_bot.repository import card_to_words
from vocab_bot.telegram import (
    TelegramClient,
    TelegramError,
    render_card,
    render_review_prompt,
    render_word_list,
    review_keyboard,
)

from .test_repository import make_card


def test_render_card_has_learning_sections_but_no_exam_labels() -> None:
    rendered = render_card(make_card())
    assert "[ˈlɛvərɪdʒ]" in rendered
    assert "用法" in rendered
    assert "例句" in rendered
    assert "相關單字" in rendered
    assert "TOEIC" not in rendered
    assert "IELTS" not in rendered
    assert "📘" not in rendered
    assert "我們善用資源" not in rendered
    assert "\n\n<b>相關單字</b>\n" in rendered


def test_review_prompt_has_grade_buttons_but_no_example() -> None:
    word = card_to_words(make_card())[0]
    rendered = render_review_prompt(word)
    keyboard = review_keyboard(word.word)
    assert rendered == "<b>leverage</b> [ˈlɛvərɪdʒ]\n<i>verb</i> · 善用"
    assert "We can leverage this tool." not in rendered
    assert "Daily Review" not in rendered
    assert "你記得" not in rendered
    assert [button["text"] for button in keyboard["inline_keyboard"][0]] == [
        "Hard",
        "Good",
        "Easy",
    ]


def test_word_list_renders_all_words_without_examples() -> None:
    messages = render_word_list(card_to_words(make_card()))
    combined = "".join(messages)
    assert "共 4 個" in combined
    assert "leverage" in combined
    assert "utilize" in combined
    assert "We can leverage this tool." not in combined


def test_telegram_error_suppresses_the_token_bearing_provider_exception(monkeypatch) -> None:
    request = httpx.Request("POST", "https://api.telegram.org/botsecret-token/sendMessage")
    response = httpx.Response(500, request=request)

    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError("provider failed", request=request, response=response)

    monkeypatch.setattr(httpx, "post", fail)

    with pytest.raises(TelegramError) as captured:
        TelegramClient("secret-token").send_message(123, "test")

    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
