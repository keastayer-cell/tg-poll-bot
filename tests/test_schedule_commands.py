import asyncio
from types import SimpleNamespace

from schedule_commands import ScheduleAdminCommands
from scheduling import DEFAULT_SCHEDULE

from .fakes import FakeBot, make_update


def build_commands(*, scheduler_running=True):
    config = dict(DEFAULT_SCHEDULE)
    saved = []
    rescheduled = []
    commands = ScheduleAdminCommands(
        admin_ids=[42],
        schedule_config=config,
        save_state=lambda: saved.append(True),
        reschedule_jobs=lambda scheduler, bot: rescheduled.append((scheduler, bot)),
    )
    scheduler = SimpleNamespace(running=scheduler_running)
    context = SimpleNamespace(
        args=[],
        bot=FakeBot(),
        application=SimpleNamespace(bot_data={"scheduler": scheduler}),
    )
    return commands, config, context, saved, rescheduled


def test_settime_updates_config_and_running_scheduler():
    commands, config, context, saved, rescheduled = build_commands()
    context.args = ["poll", "08:30"]
    update = make_update("/settime poll 08:30")

    asyncio.run(commands.settime(update, context))

    assert (config["poll_hour"], config["poll_minute"]) == (8, 30)
    assert saved == [True]
    assert len(rescheduled) == 1
    assert "09:50" in update.message.replies[0]["text"]
    assert "08:30" in update.message.replies[0]["text"]


def test_settime_rejects_invalid_time_without_saving():
    commands, config, context, saved, rescheduled = build_commands()
    context.args = ["poll", "25:00"]
    update = make_update("/settime poll 25:00")

    asyncio.run(commands.settime(update, context))

    assert config["poll_hour"] == DEFAULT_SCHEDULE["poll_hour"]
    assert saved == []
    assert rescheduled == []
    assert "Неверный формат" in update.message.replies[0]["text"]


def test_setdays_normalizes_and_saves_valid_days():
    commands, config, context, saved, rescheduled = build_commands(scheduler_running=False)
    context.args = ["poll", "MON, wed,sun"]
    update = make_update("/setdays poll MON,wed,sun")

    asyncio.run(commands.setdays(update, context))

    assert config["poll_days"] == "mon,wed,sun"
    assert saved == [True]
    assert rescheduled == []


def test_non_admin_cannot_change_schedule():
    commands, config, context, saved, rescheduled = build_commands()
    context.args = ["poll", "08:30"]
    update = make_update("/settime poll 08:30", user_id=7)

    asyncio.run(commands.settime(update, context))

    assert config["poll_hour"] == DEFAULT_SCHEDULE["poll_hour"]
    assert saved == []
    assert rescheduled == []
    assert update.message.replies == []
