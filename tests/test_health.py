import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from health import HealthReporter


class HealthyBot:
    async def get_me(self):
        return SimpleNamespace(id=123)


class BrokenBot:
    async def get_me(self):
        raise ConnectionError("offline")


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
    assert report["error_type"] == "ConnectionError"
