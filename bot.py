import asyncio
import logging
import re
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
from health import HealthReporter
from messages import (
    admin_poll_started,
    compact_status,
    deadline_warning,
    detailed_status,
    game_reminder,
    poll_instruction,
)
from poll_service import evaluate_threshold_transition
from schedule_commands import ScheduleAdminCommands
from scheduling import (
    DEFAULT_SCHEDULE,
    matches_schedule_day,
    register_jobs,
    schedule_datetime,
)
from storage import JsonStateRepository, StateLoadError
from votes import (
    add_manual_yes_vote,
    current_telegram_yes_count,
    current_yes_count,
    normalize_manual_vote,
    remove_manual_yes_vote,
)

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
PLUS_ONE_PATTERN = re.compile(r"^\+1(?:\s+(.+))?$")
announcement_manager = AnnouncementManager(
    admin_ids=ADMIN_IDS,
    target_chat_id=CHAT_ID,
    ttl_seconds=ANNOUNCE_TTL_SECONDS,
    max_length=MAX_ANNOUNCEMENT_LENGTH,
)


def current_poll_date() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def save_state():
    state_repository.save(
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "polls": polls,
            "current_poll_id": current_poll_id,
            "last_poll_message_id": last_poll_message_id,
            "schedule_config": schedule_config,
        }
    )


def load_state():
    global polls, current_poll_id, last_poll_message_id, schedule_config
    data = state_repository.load()
    if data is None:
        return
    if state_repository.recovered_from_backup:
        logger.warning("Основной state.json повреждён, состояние восстановлено из резервной копии")

    schema_version = int(data.get("schema_version", 0))
    if schema_version > STATE_SCHEMA_VERSION:
        raise StateLoadError(
            f"Версия state.json {schema_version} новее поддерживаемой {STATE_SCHEMA_VERSION}"
        )
    if not isinstance(data.get("polls", {}), dict):
        raise StateLoadError("Поле polls в state.json должно быть объектом")
    if not isinstance(data.get("schedule_config", {}), dict):
        raise StateLoadError("Поле schedule_config в state.json должно быть объектом")

    polls = data.get("polls", {})
    current_poll_id = data.get("current_poll_id")
    last_poll_message_id = data.get("last_poll_message_id")
    if last_poll_message_id is None and current_poll_id in polls:
        last_poll_message_id = polls[current_poll_id].get("message_id")
    # yes_voters хранятся с int-ключами, JSON сохраняет их как строки.
    for state in polls.values():
        state["yes_voters"] = {int(k): v for k, v in state.get("yes_voters", {}).items()}
        state.setdefault("manual_yes_voters", {})
        state["manual_yes_voters"] = {
            key: normalize_manual_vote(value) for key, value in state["manual_yes_voters"].items()
        }
        state["manual_yes_seq"] = int(state.get("manual_yes_seq", len(state["manual_yes_voters"])))
        state["yes_count"] = int(state.get("yes_count", len(state["yes_voters"])))
        state["no_count"] = int(state.get("no_count", 0))
        state["last_total_yes_count"] = int(
            state.get("last_total_yes_count", state["yes_count"] + len(state["manual_yes_voters"]))
        )
        state.setdefault("last_removed_yes_label", None)
        state.setdefault("sent_reminders", [])
    # Загружаем сохранённое расписание, добавляя дефолты для новых ключей
    saved_cfg = data.get("schedule_config", {})
    schedule_config = {**DEFAULT_SCHEDULE, **saved_cfg}
    logger.info(
        "Состояние восстановлено: current_poll_id=%s, опросов=%d", current_poll_id, len(polls)
    )
    logger.info("Расписание из state.json: %s", schedule_config)


def new_poll_state(poll_date: Optional[str] = None) -> dict:
    return {
        "yes_voters": {},  # текущие "ДА": {user_id: "Имя Фамилия"}
        "manual_yes_voters": {},  # виртуальные +1: {manual_key: "Имя"}
        "manual_yes_seq": 0,
        "yes_count": 0,
        "no_count": 0,
        "last_total_yes_count": 0,
        "last_removed_yes_label": None,
        "notified_almost": False,
        "notified_yes": False,
        "notified_deadline": False,
        "sent_reminders": [],
        "poll_date": poll_date or current_poll_date(),
    }


def display_name(user) -> str:
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    full_name = full_name.strip()
    if full_name:
        return full_name
    if getattr(user, "username", None):
        return f"@{user.username}"
    return f"id{user.id}"


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


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = answer.user.id

    logger.info(
        "Ответ: poll_id=%s, user_id=%s, options=%s",
        poll_id,
        user_id,
        answer.option_ids,
    )

    state = polls.get(poll_id)
    if state is None:
        logger.warning("poll_id=%s не найден, игнорирую", poll_id)
        return

    # option_ids[0] = "ДА", option_ids[1] = "Нет"
    full_name = (answer.user.first_name or "") + (
        " " + answer.user.last_name if answer.user.last_name else ""
    )
    full_name = full_name.strip() or f"id{user_id}"
    if 0 in answer.option_ids:
        state["yes_voters"][user_id] = full_name
    else:
        removed_name = state["yes_voters"].pop(user_id, None)
        state["last_removed_yes_label"] = removed_name or full_name
    save_state()

    yes_count = current_yes_count(state)
    logger.info(
        "poll_id=%s, агрегированных «ДА»: %d, текущих отслеженных «ДА»: %d, tracked_voters=%s",
        poll_id,
        yes_count,
        len(state["yes_voters"]),
        list(state["yes_voters"].values()),
    )


async def handle_poll_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll = update.poll
    state = polls.get(poll.id)
    if state is None:
        logger.warning("poll_id=%s не найден для poll update, игнорирую", poll.id)
        return

    yes_count = poll.options[0].voter_count if len(poll.options) > 0 else 0
    no_count = poll.options[1].voter_count if len(poll.options) > 1 else 0
    tracked_yes_count = len(state["yes_voters"])
    previous_yes_count = current_telegram_yes_count(state)

    state["yes_count"] = yes_count
    state["no_count"] = no_count

    # Poll и PollAnswer могут прийти в разном порядке. Не очищаем известные имена,
    # пока отдельное PollAnswer-обновление может ещё находиться в очереди.
    if tracked_yes_count > yes_count:
        logger.warning(
            "poll_id=%s: tracked yes_voters=%d больше агрегированного yes_count=%d, ожидаю PollAnswer",
            poll.id,
            tracked_yes_count,
            yes_count,
        )

    save_state()
    logger.info(
        "poll_id=%s, poll update: yes=%d, no=%d, total=%d",
        poll.id,
        yes_count,
        no_count,
        poll.total_voter_count,
    )
    if yes_count < previous_yes_count:
        context.application.create_task(
            reconcile_poll_decrease(context.bot, poll.id, yes_count),
            name=f"reconcile-poll-{poll.id}-{yes_count}",
        )
    else:
        await maybe_send_threshold_notifications(context.bot, poll.id, state)


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


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Текущий счёт опроса командой /status (доступно всем)."""
    if current_poll_id is None or current_poll_id not in polls:
        await update.message.reply_text("Нет активного опроса.")
        return
    await update.message.reply_text(detailed_status(polls[current_poll_id], YES_THRESHOLD))


async def add_manual_yes_from_text(
    update: Update,
    label: str,
    context: ContextTypes.DEFAULT_TYPE,
    confirmation_text: Optional[str] = None,
    source: str = "plain_text",
):
    if current_poll_id is None or current_poll_id not in polls:
        await update.message.reply_text("Нет активного опроса.")
        return

    state = polls[current_poll_id]
    user = update.effective_user
    add_manual_yes_vote(
        state,
        label,
        added_by_user_id=user.id if user else None,
        added_by_name=display_name(user) if user else None,
        source=source,
        timezone=TIMEZONE,
    )
    save_state()
    await maybe_send_threshold_notifications(context.bot, current_poll_id, state)

    reply_lines = []
    if confirmation_text:
        reply_lines.append(confirmation_text)
    else:
        reply_lines.append(f"Добавил виртуальный +1: {label}")
    reply_lines.append(compact_status(state, YES_THRESHOLD))
    await update.message.reply_text("\n".join(reply_lines))


async def remove_manual_yes_from_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: Optional[str] = None,
):
    if current_poll_id is None or current_poll_id not in polls:
        await update.message.reply_text("Нет активного опроса.")
        return

    state = polls[current_poll_id]
    removed_vote = remove_manual_yes_vote(state, query)
    if removed_vote is None:
        message = f"Виртуальный +1 «{query}» не найден." if query else "Виртуальных +1 сейчас нет."
        await update.message.reply_text(message)
        return
    removed_label = removed_vote["label"]
    state["last_removed_yes_label"] = removed_label

    save_state()
    total_yes = current_yes_count(state)
    manual_yes_count = len(state.get("manual_yes_voters", {}))
    await update.message.reply_text(
        f"Убрал виртуальный +1: {removed_label}\n"
        f"Теперь «ДА»: {total_yes} (из них вручную: {manual_yes_count})."
    )
    await maybe_send_threshold_notifications(context.bot, current_poll_id, state)


async def cmd_plus1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавляет виртуальный +1 к текущему опросу (только для админа)."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if current_poll_id is None or current_poll_id not in polls:
        await update.message.reply_text("Нет активного опроса.")
        return
    state = polls[current_poll_id]
    label = (
        " ".join(context.args).strip() or f"+1 от админа #{int(state.get('manual_yes_seq', 0)) + 1}"
    )
    await add_manual_yes_from_text(update, label, context, source="admin_command")


async def cmd_minus1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Убирает последний виртуальный +1 из текущего опроса (только для админа)."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    query = " ".join(context.args).strip() or None
    await remove_manual_yes_from_text(update, context, query)


async def handle_admin_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return

    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    if await announcement_manager.handle_text(update, context):
        return

    if chat.id != CHAT_ID:
        return

    plus_match = PLUS_ONE_PATTERN.fullmatch(text)
    if plus_match:
        author_name = display_name(user)
        guest_name = plus_match.group(1)
        label = " ".join(guest_name.split()) if guest_name else f"Гость от {author_name}"
        confirmation_text = (
            f"Виртуальный +1 для {label} засчитан."
            if guest_name
            else f"Виртуальный +1 «{label}» засчитан."
        )
        await add_manual_yes_from_text(
            update,
            label,
            context,
            confirmation_text=confirmation_text,
        )
        return

    if text == "-1" and user.id in ADMIN_IDS:
        await remove_manual_yes_from_text(update, context)


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
    schedule_commands = ScheduleAdminCommands(
        admin_ids=ADMIN_IDS,
        schedule_config=schedule_config,
        save_state=save_state,
        reschedule_jobs=reschedule_jobs,
    )
    app.add_handler(PollHandler(handle_poll_update))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("announce", announcement_manager.start))
    app.add_handler(CommandHandler("cancel", announcement_manager.cancel))
    app.add_handler(CommandHandler("plus1", cmd_plus1))
    app.add_handler(CommandHandler("minus1", cmd_minus1))
    app.add_handler(CommandHandler("settime", schedule_commands.settime))
    app.add_handler(CommandHandler("setdays", schedule_commands.setdays))
    app.add_handler(
        CallbackQueryHandler(announcement_manager.handle_callback, pattern=r"^announce:")
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_plain_text))
    app.add_error_handler(handle_error)

    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=["poll", "poll_answer", "message", "callback_query"])


if __name__ == "__main__":
    main()
