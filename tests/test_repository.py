from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random

from vocab_bot.models import Example, RelatedWord, StoredWord, VocabularyCard
from vocab_bot.repository import SQLiteRepository, weighted_sample


def make_card() -> VocabularyCard:
    example = Example(english="We can leverage this tool.", chinese="我們可以善用這項工具。")
    return VocabularyCard(
        word="leverage",
        part_of_speech=["verb"],
        meanings_zh=["善用"],
        usage_notes=["常用於商業與科技情境"],
        collocations=["leverage technology"],
        examples=[example, Example(english="They leverage data.", chinese="他們善用資料。")],
        related_words=[
            RelatedWord(
                word=word,
                meaning_zh=meaning,
                connection="在相似情境中使用",
                example=Example(english=f"We {word} resources.", chinese="我們善用資源。"),
            )
            for word, meaning in [
                ("utilize", "利用"),
                ("optimize", "最佳化"),
                ("advantage", "優勢"),
            ]
        ],
    )


def test_sqlite_saves_headword_and_related_words(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    repository.save_card(make_card())
    words = {item.word: item for item in repository.list_words()}
    assert set(words) == {"leverage", "utilize", "optimize", "advantage"}
    assert words["utilize"].is_related_seed is True
    assert words["utilize"].source_word == "leverage"


def test_claim_update_is_idempotent(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "words.sqlite3")
    assert repository.claim_update(42) is True
    assert repository.claim_update(42) is False


def test_weighted_review_favors_new_and_overdue_words() -> None:
    now = datetime.now(UTC)
    new = StoredWord(word="new", meanings_zh=["新"])
    familiar = StoredWord(
        word="familiar",
        meanings_zh=["熟悉"],
        review_count=20,
        last_reviewed_at=now - timedelta(hours=1),
    )
    counts = {"new": 0, "familiar": 0}
    rng = Random(7)
    for _ in range(500):
        chosen = weighted_sample([new, familiar], 1, now=now, rng=rng)[0]
        counts[chosen.word] += 1
    assert counts["new"] > counts["familiar"] * 2
