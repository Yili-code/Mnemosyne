from __future__ import annotations

import re

from vocab_bot.models import RelatedWord

WORD_PATTERN = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)?$")


def normalize_input(text: str) -> str | None:
    candidate = text.strip().lower()
    if not candidate or len(candidate) > 50 or not WORD_PATTERN.fullmatch(candidate):
        return None
    return candidate


def looks_like_ordinary_derivation(headword: str, candidate: str) -> bool:
    """Conservative filter for obvious inflections and routine derivations.

    Gemini makes the semantic decision; this catches common leaks such as
    manage/managed/managing/management without pretending to be a full stemmer.
    """
    head = re.sub(r"[^a-z]", "", headword.lower())
    other = re.sub(r"[^a-z]", "", candidate.lower())
    if head == other:
        return True

    variants = {
        head + suffix
        for suffix in ("s", "es", "ed", "ing", "er", "ers", "ly", "ness", "ment", "tion")
    }
    if head.endswith("e"):
        variants.update({head[:-1] + "ing", head + "d"})
    if head.endswith("y"):
        variants.update({head[:-1] + "ies", head[:-1] + "ied", head[:-1] + "iness"})
    return other in variants


def filter_related(headword: str, related: list[RelatedWord]) -> list[RelatedWord]:
    accepted: list[RelatedWord] = []
    seen = {headword.lower()}
    for item in related:
        if item.word in seen:
            continue
        if looks_like_ordinary_derivation(headword, item.word) and not (
            item.exceptional_derivation and item.exception_reason
        ):
            continue
        seen.add(item.word)
        accepted.append(item)
    return accepted
