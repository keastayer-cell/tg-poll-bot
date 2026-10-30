import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram.error import TelegramError

from health import HealthReporter
from scheduling import SchedulerManager


class HealthyBot:
    async def get_me(self):
        return SimpleNamespace(id=123)


class BrokenBot:
    async def get_me(self):
        raise TelegramError("offline")


def test_successful_probe_records_last_success(tmp_path):
    reporter = HealthReporter(str(tmp_path / "health.json"))
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)

    healthy = asyncio.run(
        reporter.probe(
            HealthyBot(),
            instance_name="test",
            scheduler_running=True,
            active_poll_id="poll",
            now=now,
        )
    )

    report = reporter.repository.load()
    assert healthy is True
    assert report["status"] == "ok"
    assert report["last_success_at"] == "2026-09-10T12:00:00+00:00"
    assert report["bot_id"] == 123


def test_failed_probe_preserves_previous_success_time(tmp_path):
    reporter = HealthReporter(str(tmp_path / "health.json"))
    first = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    second = datetime(2026, 9, 10, 12, 1, tzinfo=timezone.utc)
    asyncio.run(
        reporter.probe(
            HealthyBot(),
            instance_name="test",
            scheduler_running=True,
            active_poll_id=None,
            now=first,
        )
    )

    healthy = asyncio.run(
        reporter.probe(
            BrokenBot(),
            instance_name="test",
            scheduler_running=True,
            active_poll_id=None,
            now=second,
        )
    )

    report = reporter.repository.load()
    assert healthy is False
    assert report["status"] == "error"
    assert report["last_success_at"] == "2026-09-10T12:00:00+00:00"
    assert report["error_type"] == "TelegramError"


def test_alerts_only_after_repeated_failures_and_then_on_recovery(tmp_path):
    reporter = HealthReporter(str(tmp_path / "health.json"), failure_threshold=2)

    asyncio.run(
        reporter.probe(
            BrokenBot(), instance_name="test", scheduler_running=True, active_poll_id=None
        )
    )
    assert reporter.alert_failure is False

    asyncio.run(
        reporter.probe(
            BrokenBot(), instance_name="test", scheduler_running=True, active_poll_id=None
        )
    )
    assert reporter.alert_failure is True

    for expected in (False, False, True):
        asyncio.run(
            reporter.probe(
                HealthyBot(), instance_name="test", scheduler_running=True, active_poll_id=None
            )
        )
        assert reporter.alert_recovery is expected


def test_notification_cooldown_and_delivery_survive_restart(tmp_path):
    path = str(tmp_path / "health.json")
    now = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
    reporter = HealthReporter(path)
    reporter.record_notification(1, now=now)
    restored = HealthReporter(path)
    assert not restored.notification_due(1, now=now + timedelta(minutes=59))
    assert restored.notification_due(1, now=now + timedelta(hours=1))
    assert restored.notification_due(2, now=now)
    assert not restored.notification_due(1, recovery=True, now=now)
    restored.record_notification(1, delivered=True)
    assert HealthReporter(path).notification_due(1, recovery=True, now=now)
    restored.record_notification(1, recovery=True, now=now)
    assert not HealthReporter(path).notification_due(1, recovery=True, now=now)
    restored.record_notification(1, recovery=True, delivered=True)
    assert not HealthReporter(path).notification_due(1, recovery=True, now=now + timedelta(hours=2))


def test_recovery_requires_uninterrupted_successes_across_restart(tmp_path):
    async def scenario():
        path = str(tmp_path / "health.json")
        reporter = HealthReporter(path, failure_threshold=1)
        for healthy in (False, True, True, False, True):
            await reporter.probe(
                HealthyBot() if healthy else BrokenBot(),
                instance_name="test",
                scheduler_running=True,
                active_poll_id=None,
            )
            assert not reporter.alert_recovery
        reporter = HealthReporter(path, failure_threshold=1)
        for expected in (False, True):
            await reporter.probe(
                HealthyBot(), instance_name="test", scheduler_running=True, active_poll_id=None
            )
            assert reporter.alert_recovery is expected

    asyncio.run(scenario())


def test_scheduler_notifies_only_warned_admin_and_suppresses_flapping(tmp_path):
    class Bot:
        healthy = False

        def __init__(self):
            self.sent = []
            self.attempts = []

        async def get_me(self):
            if not self.healthy:
                raise TelegramError("offline")
            return SimpleNamespace(id=123)

        async def send_message(self, *, chat_id, text):
            self.attempts.append((chat_id, text))
            if chat_id == 2:
                raise TelegramError("delivery failed")
            self.sent.append((chat_id, text))

    async def scenario():
        reporter = HealthReporter(str(tmp_path / "health.json"))
        bot = Bot()
        application = SimpleNamespace(bot=bot, bot_data={})
        manager = SimpleNamespace(
            health_reporter=reporter,
            instance_name="test",
            current_poll_id=lambda: None,
            admin_ids=[1, 2],
            logger=logging.getLogger(__name__),
        )
        for _ in range(6):
            await SchedulerManager.check_health(manager, application)
        assert len(bot.attempts) == 2
        assert len(bot.sent) == 1
        bot.healthy = True
        for _ in range(2):
            await SchedulerManager.check_health(manager, application)
            assert len(bot.sent) == 1
        await SchedulerManager.check_health(manager, application)
        assert len(bot.sent) == 2
        assert bot.sent[-1] == (1, "✅ Связь бота с Telegram API восстановлена.")
        # Further successes and another outage within an hour must stay silent.
        for healthy in (True, False, False, False, True, True, True):
            bot.healthy = healthy
            await SchedulerManager.check_health(manager, application)
        assert len(bot.sent) == 2
        assert len(bot.attempts) == 3

    asyncio.run(scenario())
