import asyncio

from telegram.error import TelegramError

import bot_service as bot


class DeadlineBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class ClosingBot:
    async def stop_poll(self, **kwargs):
        raise TelegramError("Telegram unavailable")


def base_state():
    return {
        "yes_voters": {},
        "manual_yes_voters": {},
        "yes_count": 4,
        "no_count": 0,
        "notified_yes": False,
        "notified_almost": False,
        "notified_deadline": False,
        "message_id": 100,
    }


def test_deadline_flag_is_saved_before_notification(monkeypatch):
    state = base_state()
    saves = []
    fake_bot = DeadlineBot()
    monkeypatch.setattr(bot, "current_poll_id", "poll")
    monkeypatch.setattr(bot, "polls", {"poll": state})
    monkeypatch.setattr(bot, "ADMIN_IDS", [42])
    monkeypatch.setattr(bot, "save_state", lambda: saves.append(state["notified_deadline"]))

    asyncio.run(bot.check_deadline(fake_bot))

    assert saves == [True]
    assert len(fake_bot.messages) == 1


def test_failed_close_keeps_active_poll_for_retry(monkeypatch):
    state = base_state()
    polls = {"poll": state}
    monkeypatch.setattr(bot, "current_poll_id", "poll")
    monkeypatch.setattr(bot, "polls", polls)
    monkeypatch.setattr(bot, "save_state", lambda: None)

    closed = asyncio.run(bot.close_poll(ClosingBot()))

    assert closed is False
    assert bot.current_poll_id == "poll"
    assert polls["poll"]["close_failed"] is True
