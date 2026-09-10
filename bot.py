import asyncio
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PollAnswerHandler,
    PollHandler,
    filters,
)

from announcements import AnnouncementManager
from config import load_settings
from handlers.polls import PollHandlers
from handlers.votes import VoteHandlers
from health import HealthReporter
from messages import admin_poll_started, deadline_warning, game_reminder, poll_instruction
from models import BotSnapshot, snapshot_from_json
from models import new_poll_state as build_poll_state
from poll_service import evaluate_threshold_transition
from schedule_commands import ScheduleAdminCommands
from scheduling import (
    DEFAULT_SCHEDULE,
    matches_schedule_day,
    register_jobs,
    schedule_datetime,
)
from storage import JsonStateRepository, StateLoadError
from votes import current_telegram_yes_count, current_yes_count

_BASE_DIR = str(Path(__file__).resolve().parent)
settings = load_settings(_BASE_DIR)
settings.data_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            str(settings.data_dir / "bot.log"),
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)
for noisy_logger in ("httpx", "httpcore", "telegram", "telegram.ext"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

TOKEN = settings.bot_token
CHAT_ID = settings.chat_id
ADMIN_IDS = list(settings.admin_ids)
TIMEZONE = settings.timezone
YES_THRESHOLD = settings.yes_threshold
POLL_QUESTION = settings.poll_question
ENABLE_SCHEDULER = settings.enable_scheduler
INSTANCE_NAME = settings.instance_name
ANNOUNCE_TTL_SECONDS = settings.announce_ttl_seconds
MAX_ANNOUNCEMENT_LENGTH = 3500
POLL_RECONCILE_DELAY_SECONDS = settings.poll_reconcile_delay_seconds

schedule_config: dict = dict(DEFAULT_SCHEDULE)

STATE_FILE = str(settings.data_dir / "state.json")
STATE_SCHEMA_VERSION = 2
state_repository = JsonStateRepository(STATE_FILE)
health_reporter = HealthReporter(str(settings.data_dir / "health.json"))

# Словарь: poll_id -> данные этого конкретного опроса
# {
#   poll_id: {
#       "yes_voters": {},  # текущие "ДА": {user_id: "Имя Фамилия"}
#       "yes_count": 0,
#       "no_count": 0,
#       "notified_almost": False,
#       "notified_yes": False,
#       "notified_deadline": False,
#   }
# }
polls: dict = {}

# poll_id последнего созданного опроса (для дедлайна 15:00)
current_poll_id: Optional[str] = None
last_poll_message_id: Optional[int] = None
announcement_manager = AnnouncementManager(
    admin_ids=ADMIN_IDS,
    target_chat_id=CHAT_ID,
    ttl_seconds=ANNOUNCE_TTL_SECONDS,
    max_length=MAX_ANNOUNCEMENT_LENGTH,
)


def current_poll_date() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def save_state():
    snapshot = BotSnapshot(
        polls=polls,
        current_poll_id=current_poll_id,
        last_poll_message_id=last_poll_message_id,
        schedule_config=schedule_config,
    )
    state_repository.save(snapshot.to_json(STATE_SCHEMA_VERSION))


def load_state():
    global polls, current_poll_id, last_poll_message_id, schedule_config
    data = state_repository.load()
    if data is None:
        return
    if state_repository.recovered_from_backup:
        logger.warning("Основной state.json повреждён, состояние восстановлено из резервной копии")

    try:
        snapshot = snapshot_from_json(
            data,
            default_schedule=DEFAULT_SCHEDULE,
            supported_schema_version=STATE_SCHEMA_VERSION,
        )
    except (TypeError, ValueError) as error:
        raise StateLoadError(str(error)) from error
    polls = snapshot.polls
    current_poll_id = snapshot.current_poll_id
    last_poll_message_id = snapshot.last_poll_message_id
    schedule_config = snapshot.schedule_config
    logger.info(
        "Состояние восстановлено: current_poll_id=%s, опросов=%d", current_poll_id, len(polls)
    )
    logger.info("Расписание из state.json: %s", schedule_config)


def new_poll_state(poll_date: Optional[str] = None) -> dict:
    return build_poll_state(poll_date or current_poll_date())


async def maybe_send_threshold_notifications(bot, poll_id: str, state: dict) -> None:
    yes_count = current_yes_count(state)
    events = evaluate_threshold_transition(
        state,
        yes_count=yes_count,
        threshold=YES_THRESHOLD,
    )
    for event in events:
        recipients = [CHAT_ID] if event.audience == "chat" else ADMIN_IDS
        for recipient in recipients:
            try:
                await bot.send_message(chat_id=recipient, text=event.text)
            except Exception as error:
                logger.warning(
                    "Не удалось отправить threshold-уведомление poll_id=%s, chat_id=%s: %s",
                    poll_id,
                    recipient,
                    error,
                )
    save_state()


async def reconcile_poll_decrease(bot, poll_id: str, expected_yes_count: int) -> None:
    await asyncio.sleep(POLL_RECONCILE_DELAY_SECONDS)
    state = polls.get(poll_id)
    if state is None:
        return
    if current_telegram_yes_count(state) != expected_yes_count:
        return
    await maybe_send_threshold_notifications(bot, poll_id, state)


async def send_poll(bot, poll_date: Optional[str] = None):
    global current_poll_id, last_poll_message_id

    target_date = poll_date or current_poll_date()
    active_state = polls.get(current_poll_id) if current_poll_id else None
    if active_state and active_state.get("poll_date") == target_date:
        logger.warning(
            "Пропускаю создание опроса: на сегодня уже есть активный poll_id=%s",
            current_poll_id,
        )
        return False

    previous_message_id = last_poll_message_id
    if previous_message_id is None and active_state:
        previous_message_id = active_state.get("message_id")

    message = await bot.send_poll(
        chat_id=CHAT_ID,
        question=POLL_QUESTION,
        options=["ДА", "Нет"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    poll_id = message.poll.id
    msg_id = message.message_id
    polls[poll_id] = new_poll_state(target_date)
    polls[poll_id]["message_id"] = msg_id
    current_poll_id = poll_id
    last_poll_message_id = msg_id
    save_state()
    logger.info("Опрос создан, poll_id=%s, message_id=%s", poll_id, msg_id)

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=poll_instruction(),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Не удалось отправить сообщение-инструкцию после создания опроса: %s", e)

    # Уведомляем админов о запуске
    date_str = datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=admin_poll_started(date_str, poll_id),
            )
        except Exception as e:
            logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)

    # Снимаем только предыдущий опрос, не затрагивая остальные закрепы группы.
    if previous_message_id and previous_message_id != msg_id:
        try:
            await bot.unpin_chat_message(
                chat_id=CHAT_ID,
                message_id=previous_message_id,
            )
            logger.info("Предыдущий опрос откреплён: message_id=%s", previous_message_id)
        except Exception as e:
            logger.warning("Не удалось открепить предыдущий опрос: %s", e)

    try:
        await bot.pin_chat_message(
            chat_id=CHAT_ID,
            message_id=msg_id,
            disable_notification=False,
        )
        logger.info("Опрос закреплён")
    except Exception as e:
        logger.warning("Не удалось закрепить опрос: %s", e)

    return True


async def check_deadline(bot):
    """Вызывается в 15:00 — проверяет последний созданный опрос."""
    if current_poll_id is None:
        return
    state = polls.get(current_poll_id)
    if state is None:
        return
    if state["notified_yes"]:
        return
    if not state["notified_deadline"]:
        state["notified_deadline"] = True
        save_state()
        yes_count = current_yes_count(state)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=deadline_warning(yes_count, YES_THRESHOLD),
                )
            except Exception as e:
                logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def remind_game(bot, reminder_key: str):
    """Напоминание об игре — только если набрано 10+ ДА."""
    if current_poll_id is None:
        return
    state = polls.get(current_poll_id)
    if state is None:
        return
    if not state["notified_yes"]:
        return
    sent_reminders = state.setdefault("sent_reminders", [])
    if reminder_key in sent_reminders:
        return
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=game_reminder(),
        )
        sent_reminders.append(reminder_key)
        save_state()
        logger.info("Напоминание об игре отправлено")
    except Exception as e:
        logger.warning("Не удалось отправить напоминание: %s", e)


async def close_poll(bot):
    """Вызывается в 20:00 — закрывает опрос и чистит состояние."""
    global current_poll_id
    if current_poll_id is None:
        return
    state = polls.get(current_poll_id)
    if state is None:
        return
    # Закрываем опрос в Telegram
    msg_id = state.get("message_id")
    if msg_id:
        try:
            await bot.stop_poll(chat_id=CHAT_ID, message_id=msg_id)
            logger.info("Опрос poll_id=%s закрыт", current_poll_id)
        except Exception as e:
            logger.warning("Не удалось закрыть опрос: %s", e)
            state["close_failed"] = True
            save_state()
            return False
    # Чистим состояние
    polls.pop(current_poll_id, None)
    current_poll_id = None
    save_state()
    logger.info("Состояние очищено")
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бля, ты чо меня будишь, а братик 😅\n"
        "Я просто бот и делаю для уважаемых людей опрос.\n"
        "Отвали по брацки 🙂"
    )


async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной запуск опроса командой /poll (только для админа)."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    created = await send_poll(context.bot)
    if created:
        await update.message.reply_text("Опрос запущен вручную.")
    else:
        await update.message.reply_text("Сегодняшний активный опрос уже существует.")


def reschedule_jobs(scheduler, bot):
    """Пересоздаёт все cron-задания в планировщике по текущему schedule_config."""
    for job_id in ("job_poll", "job_deadline", "job_close", "job_remind_wed", "job_remind_sun"):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    register_jobs(
        scheduler,
        bot,
        schedule_config,
        send_poll=send_poll,
        check_deadline=check_deadline,
        close_poll=close_poll,
        remind_game=remind_game,
    )
    logger.info("Расписание пересоздано: %s", schedule_config)


async def reconcile_schedule(bot, now: Optional[datetime] = None) -> None:
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo(TIMEZONE))
    poll_date = now.strftime("%Y-%m-%d")
    cfg = schedule_config

    poll_at = schedule_datetime(now, cfg["poll_hour"], cfg["poll_minute"])
    deadline_at = schedule_datetime(now, cfg["deadline_hour"], cfg["deadline_minute"])
    close_at = schedule_datetime(now, cfg["close_hour"], cfg["close_minute"])
    close_is_today = matches_schedule_day(now, cfg["close_days"])
    before_close = not close_is_today or now < close_at

    if matches_schedule_day(now, cfg["poll_days"]) and poll_at <= now and before_close:
        await send_poll(bot, poll_date=poll_date)

    state = polls.get(current_poll_id) if current_poll_id else None
    active_today = state is not None and state.get("poll_date") == poll_date
    if active_today and before_close:
        if matches_schedule_day(now, cfg["deadline_days"]) and deadline_at <= now:
            await check_deadline(bot)

        for reminder_key in ("remind_wed", "remind_sun"):
            reminder_at = schedule_datetime(
                now,
                cfg[f"{reminder_key}_hour"],
                cfg[f"{reminder_key}_minute"],
            )
            if matches_schedule_day(now, cfg[f"{reminder_key}_days"]) and reminder_at <= now:
                await remind_game(bot, reminder_key)

    if close_is_today and close_at <= now and state is not None:
        await close_poll(bot)


async def check_bot_health(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    scheduler_running = bool(scheduler and scheduler.running)
    healthy = await health_reporter.probe(
        application.bot,
        instance_name=INSTANCE_NAME,
        scheduler_running=scheduler_running,
        active_poll_id=current_poll_id,
    )
    if not healthy:
        logger.warning("Health-check Telegram API завершился ошибкой")


async def post_init(application: Application):
    if not ENABLE_SCHEDULER:
        logger.info("Планировщик отключен (ENABLE_SCHEDULER=0).")
        return

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    reschedule_jobs(scheduler, application.bot)
    scheduler.add_job(
        check_bot_health,
        "interval",
        id="job_health",
        seconds=settings.healthcheck_interval_seconds,
        args=[application],
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    await check_bot_health(application)
    await reconcile_schedule(application.bot)
    logger.info("Планировщик запущен.")


async def post_shutdown(application: Application):
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown()


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(
        "Необработанная ошибка при обработке Telegram update=%r",
        update,
        exc_info=context.error,
    )


def main():
    logger.info("Запуск экземпляра '%s' с env-файлом: %s", INSTANCE_NAME, settings.env_path)
    load_state()
    builder = Application.builder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown)
    if settings.proxy_url:
        builder = builder.proxy(settings.proxy_url).get_updates_proxy(settings.proxy_url)
        logger.info("Используется прокси")
    app = builder.build()
    poll_handlers = PollHandlers(
        polls=polls,
        save_state=save_state,
        notify_thresholds=maybe_send_threshold_notifications,
        reconcile_decrease=reconcile_poll_decrease,
        logger=logger,
    )
    vote_handlers = VoteHandlers(
        admin_ids=ADMIN_IDS,
        target_chat_id=CHAT_ID,
        timezone=TIMEZONE,
        threshold=YES_THRESHOLD,
        polls=polls,
        current_poll_id=lambda: current_poll_id,
        save_state=save_state,
        notify_thresholds=maybe_send_threshold_notifications,
        announcement_manager=announcement_manager,
    )
    schedule_commands = ScheduleAdminCommands(
        admin_ids=ADMIN_IDS,
        schedule_config=schedule_config,
        save_state=save_state,
        reschedule_jobs=reschedule_jobs,
    )
    app.add_handler(PollHandler(poll_handlers.update))
    app.add_handler(PollAnswerHandler(poll_handlers.answer))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("status", vote_handlers.status))
    app.add_handler(CommandHandler("announce", announcement_manager.start))
    app.add_handler(CommandHandler("cancel", announcement_manager.cancel))
    app.add_handler(CommandHandler("plus1", vote_handlers.plus1))
    app.add_handler(CommandHandler("minus1", vote_handlers.minus1))
    app.add_handler(CommandHandler("settime", schedule_commands.settime))
    app.add_handler(CommandHandler("setdays", schedule_commands.setdays))
    app.add_handler(
        CallbackQueryHandler(announcement_manager.handle_callback, pattern=r"^announce:")
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, vote_handlers.plain_text))
    app.add_error_handler(handle_error)

    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=["poll", "poll_answer", "message", "callback_query"])


if __name__ == "__main__":
    main()
