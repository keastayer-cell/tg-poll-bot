from collections.abc import Awaitable, Callable
from typing import Optional

from votes import (
    add_manual_yes_vote,
    compact_status,
    current_yes_count,
    detailed_status,
    display_user_name,
    parse_plus_one,
    remove_manual_yes_vote,
)


class VoteHandlers:
    def __init__(
        self,
        *,
        admin_ids: list[int],
        target_chat_id: int,
        timezone: str,
        threshold: int,
        polls: dict,
        current_poll_id: Callable[[], Optional[str]],
        save_state: Callable[[], None],
        notify_thresholds: Callable[[object, str, dict], Awaitable[None]],
        announcement_manager,
    ):
        self.admin_ids = set(admin_ids)
        self.target_chat_id = target_chat_id
        self.timezone = timezone
        self.threshold = threshold
        self.polls = polls
        self.current_poll_id = current_poll_id
        self.save_state = save_state
        self.notify_thresholds = notify_thresholds
        self.announcement_manager = announcement_manager

    def _active(self) -> tuple[Optional[str], Optional[dict]]:
        poll_id = self.current_poll_id()
        return poll_id, self.polls.get(poll_id) if poll_id else None

    async def status(self, update, context) -> None:
        _, state = self._active()
        if state is None:
            await update.message.reply_text("Нет активного опроса.")
            return
        await update.message.reply_text(detailed_status(state, self.threshold))

    async def add(
        self,
        update,
        label: str,
        context,
        confirmation_text: Optional[str] = None,
        source: str = "plain_text",
    ) -> None:
        poll_id, state = self._active()
        if poll_id is None or state is None:
            await update.message.reply_text("Нет активного опроса.")
            return

        user = update.effective_user
        add_manual_yes_vote(
            state,
            label,
            added_by_user_id=user.id if user else None,
            added_by_name=display_user_name(user) if user else None,
            source=source,
            timezone=self.timezone,
        )
        self.save_state()
        await self.notify_thresholds(context.bot, poll_id, state)

        reply_lines = [confirmation_text or f"Добавил виртуальный +1: {label}"]
        reply_lines.append(compact_status(state, self.threshold))
        await update.message.reply_text("\n".join(reply_lines))

    async def remove(self, update, context, query: Optional[str] = None) -> None:
        poll_id, state = self._active()
        if poll_id is None or state is None:
            await update.message.reply_text("Нет активного опроса.")
            return

        removed_vote = remove_manual_yes_vote(state, query)
        if removed_vote is None:
            message = (
                f"Виртуальный +1 «{query}» не найден." if query else "Виртуальных +1 сейчас нет."
            )
            await update.message.reply_text(message)
            return

        removed_label = removed_vote["label"]
        state["last_removed_yes_label"] = removed_label
        self.save_state()
        total_yes = current_yes_count(state)
        manual_yes_count = len(state.get("manual_yes_voters", {}))
        await update.message.reply_text(
            f"Убрал виртуальный +1: {removed_label}\n"
            f"Теперь «ДА»: {total_yes} (из них вручную: {manual_yes_count})."
        )
        await self.notify_thresholds(context.bot, poll_id, state)

    async def plus1(self, update, context) -> None:
        if update.effective_user.id not in self.admin_ids:
            return
        _, state = self._active()
        if state is None:
            await update.message.reply_text("Нет активного опроса.")
            return
        label = " ".join(context.args).strip() or (
            f"+1 от админа #{int(state.get('manual_yes_seq', 0)) + 1}"
        )
        await self.add(update, label, context, source="admin_command")

    async def minus1(self, update, context) -> None:
        if update.effective_user.id not in self.admin_ids:
            return
        query = " ".join(context.args).strip() or None
        await self.remove(update, context, query)

    async def plain_text(self, update, context) -> None:
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        if message is None or user is None or chat is None:
            return

        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            return
        if await self.announcement_manager.handle_text(update, context):
            return
        if chat.id != self.target_chat_id:
            return

        label = parse_plus_one(text, display_user_name(user))
        if label is not None:
            has_guest_name = text != "+1"
            confirmation = (
                f"Виртуальный +1 для {label} засчитан."
                if has_guest_name
                else f"Виртуальный +1 «{label}» засчитан."
            )
            await self.add(update, label, context, confirmation_text=confirmation)
            return

        if text == "-1" and user.id in self.admin_ids:
            await self.remove(update, context)
