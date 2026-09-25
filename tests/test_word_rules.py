from vocab_bot.models import Example, RelatedWord
from vocab_bot.word_rules import filter_related, looks_like_ordinary_derivation, normalize_input


def related(word: str, *, exceptional: bool = False, reason: str | None = None) -> RelatedWord:
    return RelatedWord(
        word=word,
        meaning_zh="測試",
        connection="語意相關",
        example=Example(english=f"This is {word}.", chinese="這是例句。"),
        exceptional_derivation=exceptional,
        exception_reason=reason,
    )


def test_normalize_accepts_one_word_only() -> None:
    assert normalize_input("  Leverage ") == "leverage"
    assert normalize_input("follow-up") == "follow-up"
    assert normalize_input("two words") is None
    assert normalize_input("word123") is None


def test_detects_common_inflections_and_derivations() -> None:
    assert looks_like_ordinary_derivation("manage", "managed")
    assert looks_like_ordinary_derivation("manage", "managing")
    assert looks_like_ordinary_derivation("happy", "happiness")
    assert not looks_like_ordinary_derivation("manage", "supervise")


def test_filter_removes_derivation_unless_exception_is_explained() -> None:
    values = [
        related("managed"),
        related("supervise"),
        related("management", exceptional=True, reason="意義已形成獨立商業概念"),
    ]
    result = filter_related("manage", values)
    assert [item.word for item in result] == ["supervise", "management"]
