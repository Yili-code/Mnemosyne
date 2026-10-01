from __future__ import annotations

from functools import lru_cache

from opencc import OpenCC


@lru_cache(maxsize=1)
def _converter() -> OpenCC:
    return OpenCC("s2twp")


def to_taiwan_traditional(text: str) -> str:
    """Convert user-visible text to Taiwan Traditional Chinese."""
    return _converter().convert(text)
