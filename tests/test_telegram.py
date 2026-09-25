from vocab_bot.repository import card_to_words
from vocab_bot.telegram import render_card, render_daily_review

from .test_repository import make_card


def test_render_card_has_learning_sections_but_no_exam_labels() -> None:
    rendered = render_card(make_card())
    assert "用法" in rendered
    assert "例句" in rendered
    assert "相關單字" in rendered
    assert "TOEIC" not in rendered
    assert "IELTS" not in rendered


def test_daily_review_renders_all_selected_words() -> None:
    messages = render_daily_review(card_to_words(make_card()), "2026-09-24")
    combined = "".join(messages)
    assert "leverage" in combined
    assert "utilize" in combined
