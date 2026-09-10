import asyncio

import bot_service as bot

from .fakes import FakeBot


def test_new_poll_unpins_only_previous_poll(monkeypatch):
    fake_bot = FakeBot()
    previous_state = {
        "poll_date": "2000-01-01",
        "message_id": 100,
    }
    monkeypatch.setattr(bot.runtime, "polls", {"old-poll": previous_state})
    monkeypatch.setattr(bot.runtime, "current_poll_id", "old-poll")
    monkeypatch.setattr(bot, "ADMIN_IDS", [])
    monkeypatch.setattr(bot, "save_state", lambda: None)

    created = asyncio.run(bot.send_poll(fake_bot))

    assert created is True
    assert fake_bot.unpinned == [{"chat_id": bot.CHAT_ID, "message_id": 100}]
    assert fake_bot.unpinned_all == []
    assert fake_bot.pinned == [
        {
            "chat_id": bot.CHAT_ID,
            "message_id": 200,
            "disable_notification": False,
        }
    ]
