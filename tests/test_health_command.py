import json
from datetime import datetime, timedelta, timezone

from deploy.check_bot_health import check_health


def write_report(path, *, now, status="ok", scheduler_running=True):
    path.write_text(
        json.dumps(
            {
                "status": status,
                "last_success_at": now.isoformat(),
                "scheduler_running": scheduler_running,
            }
        ),
        encoding="utf-8",
    )


def test_fresh_health_report_passes(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "health.json"
    write_report(path, now=now - timedelta(seconds=30))

    healthy, message = check_health(path, max_age_seconds=180, now=now)

    assert healthy is True
    assert "бот отвечает" in message


def test_stale_health_report_fails(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "health.json"
    write_report(path, now=now - timedelta(minutes=10))

    healthy, message = check_health(path, max_age_seconds=180, now=now)

    assert healthy is False
    assert "секунд назад" in message


def test_error_status_fails_even_with_fresh_timestamp(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "health.json"
    write_report(path, now=now, status="error")

    healthy, message = check_health(path, max_age_seconds=180, now=now)

    assert healthy is False
    assert "статус" in message


def test_report_from_before_restart_is_rejected(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "health.json"
    write_report(path, now=now - timedelta(seconds=10))

    healthy, message = check_health(
        path,
        max_age_seconds=180,
        now=now,
        not_before=now - timedelta(seconds=5),
    )

    assert healthy is False
    assert "после запуска" in message
