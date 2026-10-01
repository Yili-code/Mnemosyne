from __future__ import annotations

import html
from collections.abc import Sequence

import httpx

from vocab_bot.models import StoredWord, VocabularyCard
from vocab_bot.spaced_repetition import ReviewGrade, encode_review_callback


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, timeout: float = 20.0) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    def send_message(self, chat_id: int, text: str, *, reply_markup: dict | None = None) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            response = httpx.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not payload.get("ok"):
                raise TelegramError("Telegram rejected the message")
        except (httpx.HTTPError, ValueError):
            # httpx exceptions contain the request URL, which embeds the bot token.
            raise TelegramError("Telegram message delivery failed") from None

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        self._post(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text},
        )

    def remove_inline_keyboard(self, chat_id: int, message_id: int) -> None:
        self._post(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            },
        )

    def _post(self, method: str, payload: dict[str, object]) -> None:
        try:
            response = httpx.post(
                f"{self.base_url}/{method}",
                json=payload,
                timeout=self.timeout,
            )
            body = response.json()
            if response.is_error or not isinstance(body, dict) or not body.get("ok"):
                description = body.get("description") if isinstance(body, dict) else None
                detail = f": {description}" if isinstance(description, str) else ""
                raise TelegramError(f"Telegram {method} failed{detail}")
        except TelegramError:
            raise
        except (httpx.HTTPError, ValueError):
            # Suppress the provider exception so credentials never enter application logs.
            raise TelegramError(f"Telegram {method} failed") from None


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
        f"<b>相關詞彙</b>\n{related}"
    )


def render_review_prompt(item: StoredWord) -> str:
    meaning = "；".join(html.escape(value) for value in item.meanings_zh)
    phonetic = f" {_phonetic(item.kk_phonetic)}" if item.kk_phonetic else ""
    parts = ", ".join(html.escape(value) for value in item.part_of_speech)
    parts = parts or "詞性未標註"
    return f"<b>{html.escape(item.word)}</b>{phonetic}\n<i>{parts}</i> · {meaning}"


def render_search_result(item: StoredWord) -> str:
    phonetic = f" {_phonetic(item.kk_phonetic)}" if item.kk_phonetic else ""
    parts = ", ".join(html.escape(value) for value in item.part_of_speech)
    parts = parts or "詞性未標註"
    meanings = "；".join(html.escape(value) for value in item.meanings_zh)
    sections = [
        f"<b>{html.escape(item.word)}</b>{phonetic}\n<i>{parts}</i>",
        f"<b>中文釋義</b>\n{meanings}",
    ]
    if item.usage_notes:
        usage = "\n".join(html.escape(value) for value in item.usage_notes)
        sections.append(f"<b>用法</b>\n{usage}")
    if item.collocations:
        collocations = "\n".join(html.escape(value) for value in item.collocations)
        sections.append(f"<b>常見搭配</b>\n{collocations}")
    if item.examples:
        examples = "\n\n".join(
            f"{index}. {html.escape(example.english)}\n{html.escape(example.chinese)}"
            for index, example in enumerate(item.examples, start=1)
        )
        sections.append(f"<b>例句</b>\n{examples}")
    return "\n\n".join(sections)


def review_keyboard(word: str) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "Hard",
                    "callback_data": encode_review_callback(word, ReviewGrade.HARD),
                },
                {
                    "text": "Good",
                    "callback_data": encode_review_callback(word, ReviewGrade.GOOD),
                },
                {
                    "text": "Easy",
                    "callback_data": encode_review_callback(word, ReviewGrade.EASY),
                },
            ]
        ]
    }


def clear_database_keyboard() -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "確認清空", "callback_data": "clear:confirm"},
                {"text": "取消", "callback_data": "clear:cancel"},
            ]
        ]
    }


def render_word_list(words: Sequence[StoredWord]) -> list[str]:
    ordered = sorted(words, key=lambda item: item.word)
    header = f"<b>已儲存詞彙</b>\n共 {len(ordered)} 個"
    lines = []
    for index, item in enumerate(ordered, start=1):
        meaning = "；".join(html.escape(value) for value in item.meanings_zh)
        parts = ", ".join(html.escape(value) for value in item.part_of_speech)
        parts = parts or "詞性未標註"
        lines.append(f"<b>{index}. {html.escape(item.word)}</b> · <i>{parts}</i> · {meaning}")

    if not lines:
        return [f"{header}\n\n目前尚未儲存任何詞彙。"]
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
直接傳送一個英文單字或片語，我會回覆：
• 中文意思與實際用法
• 自然例句
• 常見搭配
• TOEIC、IELTS 或日常英文中實用的相關詞彙
(普通複數、時態與常規衍生詞不會列入相關詞彙)

指令：
/help — 顯示說明
/search canonical record — 搜尋已儲存詞彙，不新增資料
/words — 列出所有已儲存詞彙
/review — 複習目前到期的詞彙，並依記憶程度安排下次複習
/clear — 經過確認後清空所有學習資料"""
