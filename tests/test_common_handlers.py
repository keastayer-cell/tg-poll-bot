import asyncio
import logging
from types import SimpleNamespace

from handlers.common import CommonHandlers

from .fakes import FakeBot, make_update


def test_non_admin_cannot_create_manual_poll():
    calls = []

    async def send_poll(bot):
        calls.append(bot)
        return True

    handlers = CommonHandlers(admin_ids=[42], send_poll=send_poll, logger=logging.getLogger())
    update = make_update("/poll", user_id=7)

    asyncio.run(handlers.poll(update, SimpleNamespace(bot=FakeBot())))

    assert calls == []
    assert update.message.replies == []


def test_admin_receives_manual_poll_result():
    async def send_poll(bot):
        return True

    handlers = CommonHandlers(admin_ids=[42], send_poll=send_poll, logger=logging.getLogger())
    update = make_update("/poll", user_id=42)

    asyncio.run(handlers.poll(update, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies[0]["text"] == "Опрос запущен вручную."
