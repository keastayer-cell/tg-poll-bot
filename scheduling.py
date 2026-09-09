from datetime import datetime

DEFAULT_SCHEDULE = {
    "poll_hour": 9,
    "poll_minute": 50,
    "poll_days": "wed,sun",
    "deadline_hour": 15,
    "deadline_minute": 0,
    "deadline_days": "wed,sun",
    "close_hour": 20,
    "close_minute": 0,
    "close_days": "wed,sun",
    "remind_wed_hour": 19,
    "remind_wed_minute": 45,
    "remind_wed_days": "wed",
    "remind_sun_hour": 18,
    "remind_sun_minute": 15,
    "remind_sun_days": "sun",
}

SETTIME_KEYS = {
    "poll": ("poll_hour", "poll_minute", "опрос (ср/вс)"),
    "deadline": ("deadline_hour", "deadline_minute", "дедлайн (ср/вс)"),
    "close": ("close_hour", "close_minute", "закрытие опроса (ср/вс)"),
    "remind_wed": ("remind_wed_hour", "remind_wed_minute", "напоминание среда"),
    "remind_sun": ("remind_sun_hour", "remind_sun_minute", "напоминание воскресенье"),
}

VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

SETDAYS_KEYS = {
    "poll": "poll_days",
    "deadline": "deadline_days",
    "close": "close_days",
    "remind_wed": "remind_wed_days",
    "remind_sun": "remind_sun_days",
}


def schedule_datetime(now: datetime, hour: int, minute: int) -> datetime:
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def matches_schedule_day(now: datetime, configured_days: str) -> bool:
    current_day = now.strftime("%a").lower()[:3]
    return current_day in {day.strip() for day in configured_days.split(",")}


def register_jobs(
    scheduler,
    bot,
    config: dict,
    *,
    send_poll,
    check_deadline,
    close_poll,
    remind_game,
) -> None:
    jobs = [
        ("job_poll", send_poll, "poll", [bot]),
        ("job_deadline", check_deadline, "deadline", [bot]),
        ("job_close", close_poll, "close", [bot]),
        ("job_remind_wed", remind_game, "remind_wed", [bot, "remind_wed"]),
        ("job_remind_sun", remind_game, "remind_sun", [bot, "remind_sun"]),
    ]
    for job_id, callback, prefix, args in jobs:
        scheduler.add_job(
            callback,
            "cron",
            id=job_id,
            day_of_week=config[f"{prefix}_days"],
            hour=config[f"{prefix}_hour"],
            minute=config[f"{prefix}_minute"],
            args=args,
            misfire_grace_time=3600,
        )
