from __future__ import annotations

import html
from collections.abc import Sequence

import httpx

from vocab_bot.models import StoredWord, VocabularyCard


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, timeout: float = 20.0) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    def send_message(self, chat_id: int, text: str) -> None:
        try:
            response = httpx.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise TelegramError("Telegram rejected the message")
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError("Telegram message delivery failed") from exc


def _phonetic(value: str) -> str:
    cleaned = value.strip().strip("/[] ")
    return f"[{html.escape(cleaned)}]" if cleaned else ""


def render_card(card: VocabularyCard) -> str:
    meanings = "；".join(html.escape(item) for item in card.meanings_zh)
    parts = ", ".join(html.escape(item) for item in card.part_of_speech)
    usage = "\n".join(html.escape(item) for item in card.usage_notes)
    collocations = "\n".join(html.escape(item) for item in card.collocations)
    examples = "\n\n".join(
        f"{index}. {html.escape(item.english)}\n{html.escape(item.chinese)}"
        for index, item in enumerate(card.examples, start=1)
    )
    related = "\n\n".join(
        f"<b>{html.escape(item.word)}</b> {_phonetic(item.kk_phonetic)}\n"
        f"{html.escape(item.meaning_zh)} · {html.escape(item.connection)}\n"
        f"<i>{html.escape(item.example.english)}</i>"
        for item in card.related_words
    )
    collocation_block = f"\n\n<b>常見搭配</b>\n{collocations}" if collocations else ""
    return (
        f"<b>{html.escape(card.word)}</b>\n"
        f"{_phonetic(card.kk_phonetic)} · <i>{parts}</i>\n\n"
        f"<b>中文釋義</b>\n{meanings}\n\n"
        f"<b>用法</b>\n{usage}{collocation_block}\n\n"
        f"<b>例句</b>\n{examples}\n\n"
        f"<b>相關單字</b>\n{related}"
    )


def render_daily_review(words: Sequence[StoredWord], date: str) -> list[str]:
    header = f"<b>Daily Review · {html.escape(date)}</b>\n今天複習 {len(words)} 個單字"
    lines = []
    for index, item in enumerate(words, start=1):
        meaning = "；".join(html.escape(value) for value in item.meanings_zh)
        phonetic = f" {_phonetic(item.kk_phonetic)}" if item.kk_phonetic else ""
        parts = ", ".join(html.escape(value) for value in item.part_of_speech)
        parts = parts or "詞性未標註"
        lines.append(
            f"<b>{index}. {html.escape(item.word)}</b>{phonetic} · <i>{parts}</i> · {meaning}"
        )

    return _chunk_lines(header, lines)


def render_word_list(words: Sequence[StoredWord]) -> list[str]:
    ordered = sorted(words, key=lambda item: item.word)
    header = f"<b>已儲存單字</b>\n共 {len(ordered)} 個"
    lines = []
    for index, item in enumerate(ordered, start=1):
        meaning = "；".join(html.escape(value) for value in item.meanings_zh)
        parts = ", ".join(html.escape(value) for value in item.part_of_speech)
        parts = parts or "詞性未標註"
        lines.append(f"<b>{index}. {html.escape(item.word)}</b> · <i>{parts}</i> · {meaning}")

    if not lines:
        return [f"{header}\n\n目前尚未儲存任何單字。"]
    return _chunk_lines(header, lines)


def _chunk_lines(header: str, lines: Sequence[str]) -> list[str]:

    # Telegram messages have a 4096-character ceiling. Chunk well below it.
    messages: list[str] = []
    current = header
    for line in lines:
        candidate = f"{current}\n\n{line}"
        if len(candidate) > 3500:
            messages.append(current)
            current = line
        else:
            current = candidate
    messages.append(current)
    return messages


HELP_TEXT = """<b>Mnemosyne</b>

直接傳送一個英文單字，我會回覆：
• 中文意思與實際用法
• 自然例句
• 常見搭配
• TOEIC、IELTS 或日常英文中實用的相關單字

普通複數、時態與常規衍生詞不會列入相關單字。

指令：
/help — 顯示說明
/stats — 查看已收藏的單字數量
/words — 列出所有已儲存單字
/review — 立即產生一輪 weighted review"""
