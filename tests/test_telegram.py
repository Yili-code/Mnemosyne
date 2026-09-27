from vocab_bot.repository import card_to_words
from vocab_bot.telegram import render_card, render_review_prompt, render_word_list, review_keyboard

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
    rendered = render_review_prompt(word, index=1, total=4, date="2026-09-24")
    keyboard = review_keyboard(word.word)
    assert "leverage" in rendered
    assert "<i>verb</i> · 善用" in rendered
    assert "We can leverage this tool." not in rendered
    assert [button["text"] for button in keyboard["inline_keyboard"][0]] == [
        "Again",
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
