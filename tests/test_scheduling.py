import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scheduling import DEFAULT_SCHEDULE, SchedulerManager, matches_schedule_day, schedule_datetime


def test_matches_configured_weekday():
    wednesday = datetime(2026, 9, 9, 10, 0)

    assert matches_schedule_day(wednesday, "wed,sun") is True
    assert matches_schedule_day(wednesday, "mon,fri") is False


def test_schedule_datetime_replaces_only_time():
    now = datetime(2026, 9, 9, 10, 23, 45, 100)

    assert schedule_datetime(now, 15, 30) == datetime(2026, 9, 9, 15, 30)


def test_health_check_frequency_and_changed_poll_days():
    timezone = ZoneInfo("Europe/Moscow")
    scheduler = AsyncIOScheduler(timezone=timezone)
    application = object()
    manager = SchedulerManager(
        enabled=True,
        timezone="Europe/Moscow",
        schedule_config=dict(DEFAULT_SCHEDULE),
        polls={},
        current_poll_id=lambda: None,
        send_poll=lambda *_args: None,
        check_deadline=lambda *_args: None,
        close_poll=lambda *_args: None,
        remind_game=lambda *_args: None,
        health_reporter=None,
        admin_ids=[],
        instance_name="test",
        logger=logging.getLogger(__name__),
    )
    manager.health_application = application
    manager.reschedule(scheduler, None)

    def fire_times(date):
        start = datetime.fromisoformat(date).replace(tzinfo=timezone)
        end = start + timedelta(days=1)
        times = []
        for job in scheduler.get_jobs():
            if not job.id.startswith("job_health"):
                continue
            previous = None
            now = start
            while True:
                fire = job.trigger.get_next_fire_time(previous, now)
                if fire is None or fire >= end:
                    break
                times.append(fire)
                previous, now = fire, fire + timedelta(microseconds=1)
        return sorted(times)

    friday = fire_times("2026-10-30")
    sunday = fire_times("2026-11-01")
    assert len(friday) == 24
    assert {time.minute for time in friday} == {0}
    assert len(sunday) == len(set(sunday)) == 96
    assert {time.minute for time in sunday} == {0, 15, 30, 45}

    manager.schedule_config["poll_days"] = "fri"
    manager.reschedule(scheduler, None)
    # Pending jobs are replaced when the scheduler starts; start paused to apply replacements.
    import asyncio

    loop = asyncio.new_event_loop()
    scheduler.configure(event_loop=loop, timezone=timezone)
    try:
        scheduler.start(paused=True)
        assert len(fire_times("2026-10-30")) == 96
        assert len(fire_times("2026-11-01")) == 24
        assert len([job for job in scheduler.get_jobs() if job.id.startswith("job_health")]) == 2
    finally:
        scheduler.shutdown()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
