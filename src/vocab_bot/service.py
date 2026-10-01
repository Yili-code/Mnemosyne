from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from vocab_bot.gemini import GeminiClient, GeminiError
from vocab_bot.models import DailyDelivery, PendingWord, ReviewTaskPayload
from vocab_bot.repository import Repository
from vocab_bot.review_tasks import ReviewTaskQueue
from vocab_bot.spaced_repetition import (
    GRADE_LABELS,
    decode_review_callback,
    describe_interval,
)
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
from vocab_bot.word_rules import normalize_input

logger = logging.getLogger(__name__)

RETRY_DELAYS = (
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(days=1),
)


def retry_delay(attempt_count: int) -> timedelta:
    return RETRY_DELAYS[min(attempt_count - 1, len(RETRY_DELAYS) - 1)]


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
        review_task_queue: ReviewTaskQueue | None = None,
    ) -> None:
        self.repository = repository
        self.gemini = gemini
        self.telegram = telegram
        self.owner_chat_id = owner_chat_id
        self.review_size = review_size
        self.timezone = ZoneInfo(timezone)
        self.review_task_queue = review_task_queue

    def handle_update(self, update: dict) -> None:
        update_id = update.get("update_id")
        callback = update.get("callback_query")
        if isinstance(update_id, int) and isinstance(callback, dict):
            self._handle_callback(callback)
            return

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
        if stripped == "/ask" or stripped.startswith("/ask "):
            _, _, raw_question = stripped.partition(" ")
            question = " ".join(raw_question.split())
            if not question:
                self.telegram.send_message(
                    chat_id,
                    "請在 <code>/ask</code> 後輸入問題，例如：\n"
                    "<code>/ask What's the difference between assignment and homework?</code>",
                )
                return
            try:
                answer = self.gemini.answer_question(question)
            except GeminiError as exc:
                logger.warning("Gemini question failed code=%s", exc.code)
                self.telegram.send_message(chat_id, "Gemini 暫時無法回答，請稍後再試。")
                return
            self.telegram.send_message(chat_id, render_question_answer(answer))
            return
        if stripped == "/search" or stripped.startswith("/search "):
            _, _, query = stripped.partition(" ")
            word = normalize_input(query)
            if word is None:
                self.telegram.send_message(
                    chat_id,
                    "請輸入英文單字或片語，例如：<code>/search canonical record</code>。",
                )
                return
            stored = self.repository.get_word(word)
            if stored is None:
                self.telegram.send_message(
                    chat_id,
                    f"資料庫中找不到 <b>{word}</b>。此指令不會新增詞彙。",
                )
                return
            self.telegram.send_message(chat_id, render_search_result(stored))
            return
        if stripped == "/words":
            for response in render_word_list(self.repository.list_words()):
                self.telegram.send_message(chat_id, response)
            return
        if stripped == "/review":
            self.send_review(force=True, delivery_key=f"telegram-{update_id}")
            return
        if stripped == "/clear":
            count = len(self.repository.list_words())
            self.telegram.send_message(
                chat_id,
                f"即將永久刪除 <b>{count}</b> 個詞彙，以及複習、每日傳送與失敗重試狀態。"
                "此操作無法復原。",
                reply_markup=clear_database_keyboard(),
            )
            return

        word = normalize_input(stripped)
        if word is None:
            self.telegram.send_message(
                chat_id,
                "請傳送一個英文單字或片語，例如：<code>leverage</code> 或 "
                "<code>canonical record</code>。",
            )
            return

        self.telegram.send_message(chat_id, f"正在整理 <b>{word}</b>…")
        try:
            card = self.gemini.create_card(word)
        except GeminiError as exc:
            now = datetime.now(UTC)
            pending = PendingWord(
                word=word,
                chat_id=chat_id,
                attempt_count=1,
                last_error_code=exc.code,
                created_at=now,
                last_attempted_at=now,
                next_attempt_at=now + retry_delay(1),
            )
            self.repository.enqueue_retry(pending)
            logger.warning("Queued Gemini retry word=%s code=%s", word, exc.code)
            self.telegram.send_message(
                chat_id,
                f"Gemini 暫時無法產生可靠內容，已保存 <b>{word}</b> 並加入自動重試。"
                "成功後會自動傳回卡片，不需要重新送出。",
            )
            return
        self.repository.save_card(card)
        self.repository.delete_retry(word)
        self.telegram.send_message(chat_id, render_card(card))

    def _handle_callback(self, callback: dict) -> None:
        callback_id = callback.get("id")
        sender = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        data = callback.get("data")
        chat_id = chat.get("id")
        message_id = message.get("message_id")

        if (
            not isinstance(callback_id, str)
            or sender.get("id") != self.owner_chat_id
            or chat_id != self.owner_chat_id
            or chat.get("type") != "private"
            or not isinstance(data, str)
        ):
            return

        if data in {"clear:confirm", "clear:cancel"}:
            self._handle_clear_callback(
                callback_id=callback_id,
                chat_id=chat_id,
                message_id=message_id,
                confirmed=data == "clear:confirm",
            )
            return

        parsed = decode_review_callback(data)
        if parsed is None:
            self.telegram.answer_callback_query(callback_id, "無效的複習選項。")
            return

        word, grade = parsed
        reviewed = self.repository.grade_review(word, grade, datetime.now(UTC))
        if reviewed is None:
            self._finish_review_callback(
                callback_id=callback_id,
                chat_id=chat_id,
                message_id=message_id,
                text="這個詞彙已評分或尚未到期。",
            )
            return

        label = GRADE_LABELS[grade]
        interval = describe_interval(reviewed.interval_days)
        self._finish_review_callback(
            callback_id=callback_id,
            chat_id=chat_id,
            message_id=message_id,
            text=f"{label}：{interval}後可再次出現。",
        )

    def _handle_clear_callback(
        self,
        *,
        callback_id: str,
        chat_id: int,
        message_id: object,
        confirmed: bool,
    ) -> None:
        if not confirmed:
            self._finish_review_callback(
                callback_id=callback_id,
                chat_id=chat_id,
                message_id=message_id,
                text="已取消清空。",
            )
            return

        counts = self.repository.clear_user_data()
        self._finish_review_callback(
            callback_id=callback_id,
            chat_id=chat_id,
            message_id=message_id,
            text="資料庫已清空。",
        )
        try:
            self.telegram.send_message(
                chat_id,
                f"資料庫已清空：刪除 <b>{counts['words']}</b> 個詞彙、"
                f"<b>{counts['pending_words']}</b> 個待重試項目與 "
                f"<b>{counts['deliveries']}</b> 筆每日傳送紀錄。",
            )
        except TelegramError as exc:
            logger.warning("Clear-database confirmation message failed: %s", exc)

    def _finish_review_callback(
        self,
        *,
        callback_id: str,
        chat_id: int,
        message_id: object,
        text: str,
    ) -> None:
        # These are two independent Telegram side effects. An expired callback query
        # must not prevent the durable grade from being reflected in the message UI.
        if isinstance(message_id, int):
            try:
                self.telegram.remove_inline_keyboard(chat_id, message_id)
            except TelegramError as exc:
                logger.warning("Review keyboard removal failed: %s", exc)
        try:
            self.telegram.answer_callback_query(callback_id, text)
        except TelegramError as exc:
            logger.warning("Review callback acknowledgement failed: %s", exc)

    def retry_failed_word(self, *, now: datetime | None = None) -> dict[str, int]:
        attempted_at = now or datetime.now(UTC)
        pending = self.repository.claim_due_retry(attempted_at)
        if pending is None:
            return {"processed": 0, "succeeded": 0, "failed": 0}

        try:
            card = self.gemini.create_card(pending.word)
        except GeminiError as exc:
            attempt_count = pending.attempt_count + 1
            rescheduled = pending.model_copy(
                update={
                    "attempt_count": attempt_count,
                    "last_error_code": exc.code,
                    "last_attempted_at": attempted_at,
                    "next_attempt_at": attempted_at + retry_delay(attempt_count),
                }
            )
            self.repository.reschedule_retry(rescheduled)
            logger.warning(
                "Gemini retry failed word=%s code=%s attempt=%s",
                pending.word,
                exc.code,
                attempt_count,
            )
            return {"processed": 1, "succeeded": 0, "failed": 1}

        self.repository.save_card(card)
        self.repository.delete_retry(pending.word)
        logger.info("Gemini retry succeeded word=%s", pending.word)
        self.telegram.send_message(
            pending.chat_id,
            f"<b>{pending.word}</b> 自動重試成功，已寫入資料庫。",
        )
        self.telegram.send_message(pending.chat_id, render_card(card))
        return {"processed": 1, "succeeded": 1, "failed": 0}

    def send_review(
        self,
        *,
        force: bool = False,
        delivery_key: str | None = None,
    ) -> list[str]:
        now = datetime.now(UTC)
        local_date = now.astimezone(self.timezone).date().isoformat()
        previous = self.repository.get_delivery(local_date)
        if previous and not force:
            return previous.words

        chosen = self.repository.list_due_words(now, self.review_size)
        if not chosen:
            self.telegram.send_message(
                self.owner_chat_id,
                "目前沒有到期的詞彙。新的詞彙會依你的評分安排下次複習。",
            )
            return []

        batch_key = delivery_key or f"daily-{local_date}"
        for item in chosen:
            if self.review_task_queue is None:
                self.send_review_card(ReviewTaskPayload(chat_id=self.owner_chat_id, item=item))
            else:
                self.review_task_queue.enqueue(
                    ReviewTaskPayload(chat_id=self.owner_chat_id, item=item),
                    delivery_key=batch_key,
                )

        selected_words = [item.word for item in chosen]
        if not force:
            self.repository.save_delivery(DailyDelivery(date=local_date, words=selected_words))
        return selected_words

    def send_review_card(self, payload: ReviewTaskPayload) -> None:
        if payload.chat_id != self.owner_chat_id:
            raise ValueError("Review task chat does not match the configured owner")
        current = self.repository.get_word(payload.item.word)
        if current is None:
            logger.info("Skipped queued review for deleted word=%s", payload.item.word)
            return
        self.telegram.send_message(
            payload.chat_id,
            render_review_prompt(current),
            reply_markup=review_keyboard(current.word),
        )
