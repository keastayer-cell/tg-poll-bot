import asyncio
from datetime import datetime

import bot

from .fakes import FakeBot


def reset_schedule_state(monkeypatch):
    monkeypatch.setattr(bot, "schedule_config", dict(bot.DEFAULT_SCHEDULE))
    monkeypatch.setattr(bot, "polls", {})
    monkeypatch.setattr(bot, "current_poll_id", None)
    monkeypatch.setattr(bot, "last_poll_message_id", None)
    monkeypatch.setattr(bot, "ADMIN_IDS", [])
    monkeypatch.setattr(bot, "save_state", lambda: None)


def active_state(date="2026-09-09", *, quorum=False):
    return {
        "poll_date": date,
        "message_id": 100,
        "yes_voters": {},
        "manual_yes_voters": {},
        "yes_count": 10 if quorum else 3,
        "no_count": 0,
        "last_total_yes_count": 10 if quorum else 3,
        "last_removed_yes_label": None,
        "notified_almost": quorum,
        "notified_yes": quorum,
        "notified_deadline": False,
        "sent_reminders": [],
    }


def test_restart_after_poll_time_creates_missing_poll(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()

    asyncio.run(bot.reconcile_schedule(fake_bot, datetime(2026, 9, 9, 10, 0)))

    assert bot.current_poll_id == "new-poll"
    assert bot.polls["new-poll"]["poll_date"] == "2026-09-09"


def test_restart_after_close_does_not_create_late_poll(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()

    asyncio.run(bot.reconcile_schedule(fake_bot, datetime(2026, 9, 9, 20, 30)))

    assert bot.current_poll_id is None


def test_restart_sends_due_reminder_only_once(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()
    state = active_state(quorum=True)
    monkeypatch.setattr(bot, "polls", {"poll": state})
    monkeypatch.setattr(bot, "current_poll_id", "poll")

    asyncio.run(bot.reconcile_schedule(fake_bot, datetime(2026, 9, 9, 19, 50)))
    asyncio.run(bot.reconcile_schedule(fake_bot, datetime(2026, 9, 9, 19, 55)))

    reminder_messages = [item for item in fake_bot.messages if item["chat_id"] == bot.CHAT_ID]
    assert len(reminder_messages) == 1
    assert state["sent_reminders"] == ["remind_wed"]


def test_restart_after_close_closes_existing_poll(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()
    state = active_state()
    monkeypatch.setattr(bot, "polls", {"poll": state})
    monkeypatch.setattr(bot, "current_poll_id", "poll")

    asyncio.run(bot.reconcile_schedule(fake_bot, datetime(2026, 9, 9, 20, 30)))

    assert fake_bot.stopped_polls == [{"chat_id": bot.CHAT_ID, "message_id": 100}]
    assert bot.current_poll_id is None
