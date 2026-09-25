from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from vocab_bot.gemini import GeminiClient, GeminiError
from vocab_bot.models import DailyDelivery
from vocab_bot.repository import Repository, weighted_sample
from vocab_bot.telegram import (
    HELP_TEXT,
    TelegramClient,
    render_card,
    render_daily_review,
)
from vocab_bot.word_rules import normalize_input


class VocabularyService:
    def __init__(
        self,
        *,
        repository: Repository,
        gemini: GeminiClient,
        telegram: TelegramClient,
        owner_chat_id: int,
        review_size: int,
        timezone: str,
    ) -> None:
        self.repository = repository
        self.gemini = gemini
        self.telegram = telegram
        self.owner_chat_id = owner_chat_id
        self.review_size = review_size
        self.timezone = ZoneInfo(timezone)

    def handle_update(self, update: dict) -> None:
        update_id = update.get("update_id")
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text")
        if not isinstance(update_id, int) or not isinstance(chat_id, int):
            return
        if chat_id != self.owner_chat_id or chat.get("type") != "private":
            return
        if not isinstance(text, str):
            return
        if not self.repository.claim_update(update_id):
            return

        stripped = text.strip()
        if stripped in {"/start", "/help"}:
            self.telegram.send_message(chat_id, HELP_TEXT)
            return
        if stripped == "/stats":
            count = len(self.repository.list_words())
            self.telegram.send_message(chat_id, f"目前資料庫共有 <b>{count}</b> 個單字。")
            return
        if stripped == "/review":
            self.send_review(force=True)
            return

        word = normalize_input(stripped)
        if word is None:
            self.telegram.send_message(
                chat_id,
                "請一次只傳送一個英文單字，例如：<code>leverage</code>。",
            )
            return

        self.telegram.send_message(chat_id, f"正在整理 <b>{word}</b>…")
        try:
            card = self.gemini.create_card(word)
        except GeminiError:
            self.telegram.send_message(
                chat_id,
                "Gemini 暫時無法產生可靠內容，這個單字尚未寫入資料庫，請稍後再試。",
            )
            return
        self.repository.save_card(card)
        self.telegram.send_message(chat_id, render_card(card))

    def send_review(self, *, force: bool = False) -> list[str]:
        now = datetime.now(UTC)
        local_date = now.astimezone(self.timezone).date().isoformat()
        previous = self.repository.get_delivery(local_date)
        if previous and not force:
            return previous.words

        all_words = self.repository.list_words()
        chosen = weighted_sample(all_words, min(self.review_size, len(all_words)), now=now)
        if not chosen:
            self.telegram.send_message(
                self.owner_chat_id,
                "今天還沒有可複習的單字。先傳一個英文單字給我吧。",
            )
            return []

        for message in render_daily_review(chosen, local_date):
            self.telegram.send_message(self.owner_chat_id, message)

        selected_words = [item.word for item in chosen]
        self.repository.mark_reviewed(selected_words, now)
        if not force:
            self.repository.save_delivery(DailyDelivery(date=local_date, words=selected_words))
        return selected_words
