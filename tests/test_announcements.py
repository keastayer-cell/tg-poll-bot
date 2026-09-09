import asyncio
from types import SimpleNamespace

from announcements import AnnouncementManager

from .fakes import FakeBot, make_update


class FakeCallbackQuery:
    def __init__(self, data, chat_id):
        self.data = data
        self.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append({"text": text, **kwargs})

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, **kwargs})


def start_announcement(monkeypatch, source_chat_id=123):
    manager = AnnouncementManager(
        admin_ids=[42],
        target_chat_id=-1001234567890,
        clock=lambda: 100,
    )
    update = make_update("/announce", user_id=42, chat_id=source_chat_id)
    context = SimpleNamespace(bot=FakeBot())
    asyncio.run(manager.start(update, context))
    return manager, context


def test_text_from_another_chat_is_not_used_as_announcement(monkeypatch):
    manager, context = start_announcement(monkeypatch, source_chat_id=123)
    update = make_update("Личное сообщение", user_id=42, chat_id=456)

    asyncio.run(manager.handle_text(update, context))

    assert context.bot.messages == []
    assert manager.pending[42]["draft"] is None


def test_announcement_requires_preview_confirmation(monkeypatch):
    manager, context = start_announcement(monkeypatch, source_chat_id=123)
    update = make_update("Текст объявления", user_id=42, chat_id=123)

    asyncio.run(manager.handle_text(update, context))

    assert context.bot.messages == []
    assert manager.pending[42]["draft"] == "Текст объявления"
    assert "Предпросмотр объявления" in update.message.replies[0]["text"]
    assert update.message.replies[0]["reply_markup"] is not None


def test_confirmed_announcement_is_published(monkeypatch):
    manager, context = start_announcement(monkeypatch, source_chat_id=123)
    manager.pending[42]["draft"] = "Текст объявления"
    query = FakeCallbackQuery("announce:publish", chat_id=123)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=42),
    )

    asyncio.run(manager.handle_callback(update, context))

    assert context.bot.messages == [{"chat_id": -1001234567890, "text": "Текст объявления"}]
    assert 42 not in manager.pending
    assert query.edits[-1]["text"] == "Объявление опубликовано в рабочем чате."


def test_expired_announcement_is_not_accepted(monkeypatch):
    manager, context = start_announcement(monkeypatch, source_chat_id=123)
    manager.clock = lambda: 100 + manager.ttl_seconds + 1
    update = make_update("Просроченный текст", user_id=42, chat_id=123)

    asyncio.run(manager.handle_text(update, context))

    assert context.bot.messages == []
    assert 42 not in manager.pending
    assert "истекло" in update.message.replies[0]["text"]
