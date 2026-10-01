import httpx
import pytest

from vocab_bot.repository import card_to_words
from vocab_bot.telegram import (
    HELP_TEXT,
    TelegramClient,
    TelegramError,
    clear_database_keyboard,
    render_card,
    render_question_answer,
    render_review_prompt,
    render_search_result,
    render_word_list,
    review_keyboard,
)

from .test_repository import make_card


def test_help_text_is_all_english_and_lists_every_command() -> None:
    assert not any("\u4e00" <= character <= "\u9fff" for character in HELP_TEXT)
    assert "<b>Commands</b>" in HELP_TEXT
    assert "/ask <code>question</code>" in HELP_TEXT
    assert "/search <code>word or phrase</code>" in HELP_TEXT
    for command in ("/help", "/ask", "/search", "/words", "/review", "/clear"):
        assert command in HELP_TEXT


def test_render_card_has_learning_sections_but_no_exam_labels() -> None:
    rendered = render_card(make_card())
    assert "[ˈlɛvərɪdʒ]" in rendered
    assert "用法" in rendered
    assert "例句" in rendered
    assert "相關詞彙" in rendered
    assert "TOEIC" not in rendered
    assert "IELTS" not in rendered
    assert "📘" not in rendered
    assert "我們善用資源" not in rendered
    assert "\n\n<b>相關詞彙</b>\n" in rendered


def test_render_card_omits_related_section_when_no_quality_words_remain() -> None:
    rendered = render_card(make_card().model_copy(update={"related_words": []}))

    assert "相關詞彙" not in rendered


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


def test_clear_database_keyboard_requires_confirmation() -> None:
    keyboard = clear_database_keyboard()
    buttons = keyboard["inline_keyboard"][0]
    assert [(button["text"], button["callback_data"]) for button in buttons] == [
        ("確認清空", "clear:confirm"),
        ("取消", "clear:cancel"),
    ]


def test_word_list_renders_all_words_without_examples() -> None:
    messages = render_word_list(card_to_words(make_card()))
    combined = "".join(messages)
    assert "共 4 個" in combined
    assert "leverage" in combined
    assert "utilize" in combined
    assert "We can leverage this tool." not in combined


def test_search_result_renders_the_stored_content() -> None:
    word = card_to_words(make_card())[0]

    rendered = render_search_result(word)

    assert "<b>leverage</b> [ˈlɛvərɪdʒ]" in rendered
    assert "<b>中文釋義</b>\n善用" in rendered
    assert "<b>用法</b>" in rendered
    assert "<b>常見搭配</b>" in rendered
    assert "We can leverage this tool." in rendered


def test_question_answer_escapes_gemini_output() -> None:
    rendered = render_question_answer("Use A < B & B > C")

    assert rendered == "Use A &lt; B &amp; B &gt; C"


def test_send_message_converts_simplified_chinese_before_delivery(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, *, json, timeout):
        captured.update(json)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)

    TelegramClient("secret-token").send_message(123, "这个软件使用数据库。")

    assert captured["text"] == "這個軟體使用資料庫。"


def test_callback_answer_converts_simplified_chinese_before_delivery(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, *, json, timeout):
        captured.update(json)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)

    TelegramClient("secret-token").answer_callback_query("callback-id", "已评分")

    assert captured["text"] == "已評分"


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
