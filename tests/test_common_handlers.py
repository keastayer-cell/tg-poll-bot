import asyncio
from types import SimpleNamespace

import bot as bot

from .fakes import FakeBot, make_update


def test_non_admin_cannot_create_manual_poll(monkeypatch):
    calls = []

    async def send_poll(bot):
        calls.append(bot)
        return True

    monkeypatch.setattr(bot, "ADMIN_IDS", [42])
    monkeypatch.setattr(bot, "send_poll", send_poll)
    update = make_update("/poll", user_id=7)

    asyncio.run(bot.cmd_poll(update, SimpleNamespace(bot=FakeBot())))

    assert calls == []
    assert update.message.replies == []


def test_admin_receives_manual_poll_result(monkeypatch):
    async def send_poll(bot):
        return True

    monkeypatch.setattr(bot, "ADMIN_IDS", [42])
    monkeypatch.setattr(bot, "send_poll", send_poll)
    update = make_update("/poll", user_id=42)

    asyncio.run(bot.cmd_poll(update, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies[0]["text"] == "Опрос запущен вручную."
