from time import monotonic
from typing import Callable, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

ANNOUNCE_PROMPT_TEXT = "Введите текст объявления следующим сообщением. Для отмены введите /cancel."


class AnnouncementManager:
    def __init__(
        self,
        *,
        admin_ids: list[int],
        target_chat_id: int,
        ttl_seconds: int = 300,
        max_length: int = 3500,
        clock: Callable[[], float] = monotonic,
    ):
        self.admin_ids = set(admin_ids)
        self.target_chat_id = target_chat_id
        self.ttl_seconds = ttl_seconds
        self.max_length = max_length
        self.clock = clock
        self.pending: dict[int, dict] = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        chat = update.effective_chat
        if user is None or chat is None or user.id not in self.admin_ids:
            return
        self.pending[user.id] = {
            "source_chat_id": chat.id,
            "expires_at": self.clock() + self.ttl_seconds,
            "draft": None,
        }
        await update.message.reply_text(ANNOUNCE_PROMPT_TEXT)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None or user.id not in self.admin_ids:
            return
        if self.pending.pop(user.id, None):
            await update.message.reply_text("Ввод объявления отменен.")
            return
        await update.message.reply_text("Сейчас нет активного ввода объявления.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        user = update.effective_user
        chat = update.effective_chat
        message = update.effective_message
        if user is None or chat is None or message is None:
            return False

        pending = self.pending.get(user.id)
        if pending is None:
            return False

        if pending.get("expires_at", 0) < self.clock():
            self.pending.pop(user.id, None)
            if chat.id == pending.get("source_chat_id"):
                await message.reply_text(
                    "Время ввода объявления истекло. Запустите /announce снова."
                )
                return True
            return False

        if chat.id != pending.get("source_chat_id"):
            return False

        text = (message.text or "").strip()
        if len(text) > self.max_length:
            await message.reply_text(
                f"Объявление слишком длинное. Максимум {self.max_length} символов."
            )
            return True

        pending["draft"] = text
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Опубликовать", callback_data="announce:publish"),
                    InlineKeyboardButton("Отмена", callback_data="announce:cancel"),
                ]
            ]
        )
        await message.reply_text(
            f"Предпросмотр объявления:\n\n{text}",
            reply_markup=keyboard,
        )
        return True

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = update.effective_user
        if query is None or user is None:
            return
        if user.id not in self.admin_ids:
            await query.answer("Недостаточно прав", show_alert=True)
            return

        pending = self.pending.get(user.id)
        if pending is None or pending.get("expires_at", 0) < self.clock():
            self.pending.pop(user.id, None)
            await query.answer()
            await query.edit_message_text("Время подтверждения объявления истекло.")
            return

        source_chat = query.message.chat if query.message else None
        if source_chat is None or source_chat.id != pending.get("source_chat_id"):
            await query.answer("Это подтверждение относится к другому чату", show_alert=True)
            return

        if query.data == "announce:cancel":
            self.pending.pop(user.id, None)
            await query.answer()
            await query.edit_message_text("Публикация объявления отменена.")
            return

        draft: Optional[str] = pending.get("draft")
        if query.data != "announce:publish" or not draft:
            await query.answer()
            await query.edit_message_text("Черновик объявления не найден.")
            self.pending.pop(user.id, None)
            return

        self.pending.pop(user.id, None)
        await query.answer()
        await context.bot.send_message(chat_id=self.target_chat_id, text=draft)
        await query.edit_message_text("Объявление опубликовано в рабочем чате.")
