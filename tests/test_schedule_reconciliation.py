import asyncio
from datetime import datetime

import bot_service as bot
from scheduling import SchedulerManager

from .fakes import FakeBot


def reset_schedule_state(monkeypatch):
    monkeypatch.setattr(bot.runtime, "schedule_config", dict(bot.DEFAULT_SCHEDULE))
    monkeypatch.setattr(bot.runtime, "polls", {})
    monkeypatch.setattr(bot.runtime, "current_poll_id", None)
    monkeypatch.setattr(bot.runtime, "last_poll_message_id", None)
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


def scheduler_manager():
    return SchedulerManager(
        enabled=True,
        timezone=bot.TIMEZONE,
        health_interval_seconds=60,
        schedule_config=bot.runtime.schedule_config,
        polls=bot.runtime.polls,
        current_poll_id=lambda: bot.runtime.current_poll_id,
        send_poll=bot.send_poll,
        check_deadline=bot.check_deadline,
        close_poll=bot.close_poll,
        remind_game=bot.remind_game,
        health_reporter=bot.health_reporter,
        admin_ids=[],
        instance_name="pytest",
        logger=bot.logger,
    )


def test_restart_after_poll_time_creates_missing_poll(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()

    asyncio.run(scheduler_manager().reconcile(fake_bot, datetime(2026, 9, 9, 10, 0)))

    assert bot.runtime.current_poll_id == "new-poll"
    assert bot.runtime.polls["new-poll"]["poll_date"] == "2026-09-09"


def test_restart_after_close_does_not_create_late_poll(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()

    asyncio.run(scheduler_manager().reconcile(fake_bot, datetime(2026, 9, 9, 20, 30)))

    assert bot.runtime.current_poll_id is None


def test_restart_sends_due_reminder_only_once(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()
    state = active_state(quorum=True)
    monkeypatch.setattr(bot.runtime, "polls", {"poll": state})
    monkeypatch.setattr(bot.runtime, "current_poll_id", "poll")

    manager = scheduler_manager()
    asyncio.run(manager.reconcile(fake_bot, datetime(2026, 9, 9, 19, 50)))
    asyncio.run(manager.reconcile(fake_bot, datetime(2026, 9, 9, 19, 55)))

    reminder_messages = [item for item in fake_bot.messages if item["chat_id"] == bot.CHAT_ID]
    assert len(reminder_messages) == 1
    assert state["sent_reminders"] == ["remind_wed"]


def test_restart_after_close_closes_existing_poll(monkeypatch):
    reset_schedule_state(monkeypatch)
    fake_bot = FakeBot()
    state = active_state()
    monkeypatch.setattr(bot.runtime, "polls", {"poll": state})
    monkeypatch.setattr(bot.runtime, "current_poll_id", "poll")

    asyncio.run(scheduler_manager().reconcile(fake_bot, datetime(2026, 9, 9, 20, 30)))

    assert fake_bot.stopped_polls == [{"chat_id": bot.CHAT_ID, "message_id": 100}]
    assert bot.runtime.current_poll_id is None
