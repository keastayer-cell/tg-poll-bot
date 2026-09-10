from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.error import TelegramError

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


class SchedulerManager:
    def __init__(
        self,
        *,
        enabled: bool,
        timezone: str,
        health_interval_seconds: int,
        schedule_config: dict,
        polls: dict,
        current_poll_id,
        send_poll,
        check_deadline,
        close_poll,
        remind_game,
        health_reporter,
        admin_ids: list[int],
        instance_name: str,
        logger,
    ):
        self.enabled = enabled
        self.timezone = timezone
        self.health_interval_seconds = health_interval_seconds
        self.schedule_config = schedule_config
        self.polls = polls
        self.current_poll_id = current_poll_id
        self.send_poll = send_poll
        self.check_deadline = check_deadline
        self.close_poll = close_poll
        self.remind_game = remind_game
        self.health_reporter = health_reporter
        self.admin_ids = admin_ids
        self.instance_name = instance_name
        self.logger = logger

    def reschedule(self, scheduler, bot) -> None:
        for job_id in (
            "job_poll",
            "job_deadline",
            "job_close",
            "job_remind_wed",
            "job_remind_sun",
        ):
            try:
                scheduler.remove_job(job_id)
            except JobLookupError:
                pass
        register_jobs(
            scheduler,
            bot,
            self.schedule_config,
            send_poll=self.send_poll,
            check_deadline=self.check_deadline,
            close_poll=self.close_poll,
            remind_game=self.remind_game,
        )
        self.logger.info("Расписание пересоздано: %s", self.schedule_config)

    async def reconcile(self, bot, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(ZoneInfo(self.timezone))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(self.timezone))
        poll_date = now.strftime("%Y-%m-%d")
        config = self.schedule_config
        poll_at = schedule_datetime(now, config["poll_hour"], config["poll_minute"])
        deadline_at = schedule_datetime(now, config["deadline_hour"], config["deadline_minute"])
        close_at = schedule_datetime(now, config["close_hour"], config["close_minute"])
        close_is_today = matches_schedule_day(now, config["close_days"])
        before_close = not close_is_today or now < close_at

        if matches_schedule_day(now, config["poll_days"]) and poll_at <= now and before_close:
            await self.send_poll(bot, poll_date=poll_date)

        poll_id = self.current_poll_id()
        state = self.polls.get(poll_id) if poll_id else None
        active_today = state is not None and state.get("poll_date") == poll_date
        if active_today and before_close:
            if matches_schedule_day(now, config["deadline_days"]) and deadline_at <= now:
                await self.check_deadline(bot)

            for reminder_key in ("remind_wed", "remind_sun"):
                reminder_at = schedule_datetime(
                    now,
                    config[f"{reminder_key}_hour"],
                    config[f"{reminder_key}_minute"],
                )
                if matches_schedule_day(now, config[f"{reminder_key}_days"]) and reminder_at <= now:
                    await self.remind_game(bot, reminder_key)

        if close_is_today and close_at <= now and state is not None:
            await self.close_poll(bot)

    async def check_health(self, application) -> None:
        scheduler = application.bot_data.get("scheduler")
        healthy = await self.health_reporter.probe(
            application.bot,
            instance_name=self.instance_name,
            scheduler_running=bool(scheduler and scheduler.running),
            active_poll_id=self.current_poll_id(),
        )
        if not healthy:
            self.logger.warning("Health-check Telegram API завершился ошибкой")
            if self.health_reporter.alert_failure:
                for admin_id in self.admin_ids:
                    try:
                        await application.bot.send_message(
                            chat_id=admin_id,
                            text=(
                                "⚠️ Бот несколько раз подряд не смог обратиться к Telegram API. "
                                "Проверьте сервис и сеть."
                            ),
                        )
                    except TelegramError as error:
                        self.logger.warning(
                            "Не удалось отправить health-алерт admin_id=%s: %s",
                            admin_id,
                            error,
                        )
        elif self.health_reporter.alert_recovery:
            for admin_id in self.admin_ids:
                try:
                    await application.bot.send_message(
                        chat_id=admin_id,
                        text="✅ Связь бота с Telegram API восстановлена.",
                    )
                except TelegramError as error:
                    self.logger.warning(
                        "Не удалось отправить health-восстановление admin_id=%s: %s",
                        admin_id,
                        error,
                    )

    async def start(self, application) -> None:
        if not self.enabled:
            self.logger.info("Планировщик отключен (ENABLE_SCHEDULER=0).")
            return
        scheduler = AsyncIOScheduler(timezone=self.timezone)
        self.reschedule(scheduler, application.bot)
        scheduler.add_job(
            self.check_health,
            "interval",
            id="job_health",
            seconds=self.health_interval_seconds,
            args=[application],
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        application.bot_data["scheduler"] = scheduler
        await self.check_health(application)
        await self.reconcile(application.bot)
        self.logger.info("Планировщик запущен.")

    async def shutdown(self, application) -> None:
        scheduler = application.bot_data.get("scheduler")
        if scheduler and scheduler.running:
            scheduler.shutdown()
