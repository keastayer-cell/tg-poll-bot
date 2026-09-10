import asyncio
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    PollHandler,
    filters,
)

from announcements import AnnouncementManager
from config import load_settings
from handlers.admin import AdminHandlers
from handlers.common import CommonHandlers
from handlers.polls import PollHandlers
from handlers.votes import VoteHandlers
from health import HealthReporter
from messages import admin_poll_started, deadline_warning, game_reminder, poll_instruction
from models import new_poll_state as build_poll_state
from poll_service import evaluate_threshold_transition
from runtime import BotRuntime
from schedule_commands import ScheduleAdminCommands
from scheduling import (
    DEFAULT_SCHEDULE,
    SchedulerManager,
)
from storage import JsonStateRepository
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

STATE_FILE = str(settings.data_dir / "state.json")
STATE_SCHEMA_VERSION = 2
runtime = BotRuntime(
    repository=JsonStateRepository(STATE_FILE),
    default_schedule=DEFAULT_SCHEDULE,
    logger=logger,
    schema_version=STATE_SCHEMA_VERSION,
)
health_reporter = HealthReporter(
    str(settings.data_dir / "health.json"),
    failure_threshold=settings.health_failure_threshold,
)

announcement_manager = AnnouncementManager(
    admin_ids=ADMIN_IDS,
    target_chat_id=CHAT_ID,
    ttl_seconds=ANNOUNCE_TTL_SECONDS,
    max_length=MAX_ANNOUNCEMENT_LENGTH,
)


def current_poll_date() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def save_state():
    runtime.save()


def load_state():
    runtime.load()


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
            except TelegramError as error:
                logger.warning(
                    "Не удалось отправить threshold-уведомление poll_id=%s, chat_id=%s: %s",
                    poll_id,
                    recipient,
                    error,
                )
    save_state()


async def reconcile_poll_decrease(bot, poll_id: str, expected_yes_count: int) -> None:
    await asyncio.sleep(POLL_RECONCILE_DELAY_SECONDS)
    state = runtime.polls.get(poll_id)
    if state is None:
        return
    if current_telegram_yes_count(state) != expected_yes_count:
        return
    await maybe_send_threshold_notifications(bot, poll_id, state)


async def send_poll(bot, poll_date: Optional[str] = None):
    target_date = poll_date or current_poll_date()
    active_state = runtime.polls.get(runtime.current_poll_id) if runtime.current_poll_id else None
    if active_state and active_state.get("poll_date") == target_date:
        logger.warning(
            "Пропускаю создание опроса: на сегодня уже есть активный poll_id=%s",
            runtime.current_poll_id,
        )
        return False

    previous_message_id = runtime.last_poll_message_id
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
    runtime.polls[poll_id] = new_poll_state(target_date)
    runtime.polls[poll_id]["message_id"] = msg_id
    runtime.current_poll_id = poll_id
    runtime.last_poll_message_id = msg_id
    save_state()
    logger.info("Опрос создан, poll_id=%s, message_id=%s", poll_id, msg_id)

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=poll_instruction(),
            parse_mode="HTML",
        )
    except TelegramError as e:
        logger.warning("Не удалось отправить сообщение-инструкцию после создания опроса: %s", e)

    # Уведомляем админов о запуске
    date_str = datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=admin_poll_started(date_str, poll_id),
            )
        except TelegramError as e:
            logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)

    # Снимаем только предыдущий опрос, не затрагивая остальные закрепы группы.
    if previous_message_id and previous_message_id != msg_id:
        try:
            await bot.unpin_chat_message(
                chat_id=CHAT_ID,
                message_id=previous_message_id,
            )
            logger.info("Предыдущий опрос откреплён: message_id=%s", previous_message_id)
        except TelegramError as e:
            logger.warning("Не удалось открепить предыдущий опрос: %s", e)

    try:
        await bot.pin_chat_message(
            chat_id=CHAT_ID,
            message_id=msg_id,
            disable_notification=False,
        )
        logger.info("Опрос закреплён")
    except TelegramError as e:
        logger.warning("Не удалось закрепить опрос: %s", e)

    return True


async def check_deadline(bot):
    """Вызывается в 15:00 — проверяет последний созданный опрос."""
    if runtime.current_poll_id is None:
        return
    state = runtime.polls.get(runtime.current_poll_id)
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
            except TelegramError as e:
                logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def remind_game(bot, reminder_key: str):
    """Напоминание об игре — только если набрано 10+ ДА."""
    if runtime.current_poll_id is None:
        return
    state = runtime.polls.get(runtime.current_poll_id)
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
    except TelegramError as e:
        logger.warning("Не удалось отправить напоминание: %s", e)


async def close_poll(bot):
    """Вызывается в 20:00 — закрывает опрос и чистит состояние."""
    if runtime.current_poll_id is None:
        return
    state = runtime.polls.get(runtime.current_poll_id)
    if state is None:
        return
    # Закрываем опрос в Telegram
    msg_id = state.get("message_id")
    if msg_id:
        try:
            await bot.stop_poll(chat_id=CHAT_ID, message_id=msg_id)
            logger.info("Опрос poll_id=%s закрыт", runtime.current_poll_id)
        except TelegramError as e:
            logger.warning("Не удалось закрыть опрос: %s", e)
            state["close_failed"] = True
            save_state()
            return False
    # Чистим состояние
    runtime.polls.pop(runtime.current_poll_id, None)
    runtime.current_poll_id = None
    save_state()
    logger.info("Состояние очищено")
    return True


def build_application() -> Application:
    scheduler_manager = SchedulerManager(
        enabled=ENABLE_SCHEDULER,
        timezone=TIMEZONE,
        health_interval_seconds=settings.healthcheck_interval_seconds,
        schedule_config=runtime.schedule_config,
        polls=runtime.polls,
        current_poll_id=lambda: runtime.current_poll_id,
        send_poll=send_poll,
        check_deadline=check_deadline,
        close_poll=close_poll,
        remind_game=remind_game,
        health_reporter=health_reporter,
        admin_ids=ADMIN_IDS,
        instance_name=INSTANCE_NAME,
        logger=logger,
    )
    builder = (
        Application.builder()
        .token(TOKEN)
        .post_init(scheduler_manager.start)
        .post_shutdown(scheduler_manager.shutdown)
    )
    if settings.proxy_url:
        builder = builder.proxy(settings.proxy_url).get_updates_proxy(settings.proxy_url)
        logger.info("Используется прокси")
    app = builder.build()
    poll_handlers = PollHandlers(
        polls=runtime.polls,
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
        polls=runtime.polls,
        current_poll_id=lambda: runtime.current_poll_id,
        save_state=save_state,
        notify_thresholds=maybe_send_threshold_notifications,
        announcement_manager=announcement_manager,
    )
    schedule_commands = ScheduleAdminCommands(
        admin_ids=ADMIN_IDS,
        schedule_config=runtime.schedule_config,
        save_state=save_state,
        reschedule_jobs=scheduler_manager.reschedule,
    )
    common_handlers = CommonHandlers(
        admin_ids=ADMIN_IDS,
        send_poll=send_poll,
        logger=logger,
    )
    admin_handlers = AdminHandlers(
        announcements=announcement_manager,
        schedule=schedule_commands,
    )
    app.add_handler(PollHandler(poll_handlers.update))
    app.add_handler(PollAnswerHandler(poll_handlers.answer))
    app.add_handler(CommandHandler("start", common_handlers.start))
    app.add_handler(CommandHandler("poll", common_handlers.poll))
    app.add_handler(CommandHandler("status", vote_handlers.status))
    app.add_handler(CommandHandler("announce", admin_handlers.announce))
    app.add_handler(CommandHandler("cancel", admin_handlers.cancel))
    app.add_handler(CommandHandler("plus1", vote_handlers.plus1))
    app.add_handler(CommandHandler("minus1", vote_handlers.minus1))
    app.add_handler(CommandHandler("settime", admin_handlers.settime))
    app.add_handler(CommandHandler("setdays", admin_handlers.setdays))
    app.add_handler(
        CallbackQueryHandler(admin_handlers.announcement_callback, pattern=r"^announce:")
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, vote_handlers.plain_text))
    app.add_error_handler(common_handlers.error)
    return app


def main():
    logger.info("Запуск экземпляра '%s' с env-файлом: %s", INSTANCE_NAME, settings.env_path)
    load_state()
    app = build_application()

    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=["poll", "poll_answer", "message", "callback_query"])


if __name__ == "__main__":
    main()
