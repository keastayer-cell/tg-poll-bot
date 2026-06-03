import os
import json
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    PollAnswerHandler,
    PollHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.getenv("ENV_FILE", ".env")
ENV_PATH = os.path.join(_BASE_DIR, ENV_FILE)
load_dotenv(ENV_PATH)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(_BASE_DIR, "bot.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
ADMIN_ID = int(os.environ["ADMIN_ID"])
ADMIN_IDS = [ADMIN_ID] + [
    int(x.strip()) for x in os.getenv("EXTRA_ADMIN_IDS", "").split(",") if x.strip()
]
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
YES_THRESHOLD = int(os.getenv("YES_THRESHOLD", "10"))
POLL_QUESTION = os.getenv("POLL_QUESTION", "Идете?")
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "1").lower() not in {"0", "false", "no"}
INSTANCE_NAME = os.getenv("INSTANCE_NAME", "prod")

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
schedule_config: dict = dict(DEFAULT_SCHEDULE)

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

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


def current_poll_date() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"polls": polls, "current_poll_id": current_poll_id, "schedule_config": schedule_config},
                f, ensure_ascii=False,
            )
    except Exception as e:
        logger.warning("Не удалось сохранить состояние: %s", e)


def load_state():
    global polls, current_poll_id, schedule_config
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        polls = data.get("polls", {})
        current_poll_id = data.get("current_poll_id")
        # yes_voters хранятся с int-ключами, JSON сохраняет их как строки.
        for state in polls.values():
            state["yes_voters"] = {
                int(k): v for k, v in state.get("yes_voters", {}).items()
            }
            state.setdefault("manual_yes_voters", {})
            state["manual_yes_seq"] = int(
                state.get("manual_yes_seq", len(state["manual_yes_voters"]))
            )
            state["yes_count"] = int(state.get("yes_count", len(state["yes_voters"])))
            state["no_count"] = int(state.get("no_count", 0))
        # Загружаем сохранённое расписание, добавляя дефолты для новых ключей
        saved_cfg = data.get("schedule_config", {})
        schedule_config = {**DEFAULT_SCHEDULE, **saved_cfg}
        logger.info("Состояние восстановлено: current_poll_id=%s, опросов=%d", current_poll_id, len(polls))
        logger.info("Расписание из state.json: %s", schedule_config)
    except Exception as e:
        logger.warning("Не удалось загрузить состояние: %s", e)


def new_poll_state() -> dict:
    return {
        "yes_voters": {},  # текущие "ДА": {user_id: "Имя Фамилия"}
        "manual_yes_voters": {},  # виртуальные +1: {manual_key: "Имя"}
        "manual_yes_seq": 0,
        "yes_count": 0,
        "no_count": 0,
        "notified_almost": False,
        "notified_yes": False,
        "notified_deadline": False,
        "poll_date": current_poll_date(),
    }


def current_yes_count(state: dict) -> int:
    telegram_yes_count = int(state.get("yes_count", len(state.get("yes_voters", {}))))
    manual_yes_count = len(state.get("manual_yes_voters", {}))
    return telegram_yes_count + manual_yes_count


def current_telegram_yes_count(state: dict) -> int:
    return int(state.get("yes_count", len(state.get("yes_voters", {}))))


def add_manual_yes_vote(state: dict, label: str) -> str:
    next_seq = int(state.get("manual_yes_seq", 0)) + 1
    state["manual_yes_seq"] = next_seq
    manual_key = f"manual:{next_seq}"
    state.setdefault("manual_yes_voters", {})[manual_key] = label
    return manual_key


def remove_last_manual_yes_vote(state: dict) -> Optional[str]:
    manual_yes_voters = state.get("manual_yes_voters", {})
    if not manual_yes_voters:
        return None
    manual_key = next(reversed(manual_yes_voters))
    return manual_yes_voters.pop(manual_key, None)


async def maybe_send_threshold_notifications(bot, poll_id: str, state: dict) -> None:
    yes_count = current_yes_count(state)

    if yes_count >= YES_THRESHOLD - 1 and not state["notified_almost"] and not state["notified_yes"]:
        state["notified_almost"] = True
        save_state()
        await bot.send_message(
            chat_id=CHAT_ID,
            text="Братики, еще 1 и идем 💪",
        )

    if yes_count >= YES_THRESHOLD and not state["notified_yes"]:
        state["notified_yes"] = True
        save_state()
        await bot.send_message(
            chat_id=CHAT_ID,
            text="Ну все, епта, идем играть, готовьтесь 🔥",
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"✅ Набрано {YES_THRESHOLD} «ДА»! Все идут.",
                )
            except Exception as e:
                logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def send_poll(bot):
    global current_poll_id

    active_state = polls.get(current_poll_id) if current_poll_id else None
    if active_state and active_state.get("poll_date") == current_poll_date():
        logger.warning(
            "Пропускаю создание опроса: на сегодня уже есть активный poll_id=%s",
            current_poll_id,
        )
        return False

    message = await bot.send_poll(
        chat_id=CHAT_ID,
        question=POLL_QUESTION,
        options=["ДА", "Нет"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    poll_id = message.poll.id
    msg_id = message.message_id
    polls[poll_id] = new_poll_state()
    polls[poll_id]["message_id"] = msg_id
    current_poll_id = poll_id
    save_state()
    logger.info("Опрос создан, poll_id=%s, message_id=%s", poll_id, msg_id)

    # Уведомляем админов о запуске
    date_str = datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    f"📋 Я запустил опрос \"{date_str}\".\n"
                    f"ID опроса: {poll_id}\n\n"
                    f"Я буду сообщать Вам о его результатах."
                ),
            )
        except Exception as e:
            logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)

    # Сначала очищаем старые закрепы, потом закрепляем новый опрос с уведомлением.
    try:
        await bot.unpin_all_chat_messages(chat_id=CHAT_ID)
        logger.info("Старые закрепы очищены")
    except Exception as e:
        logger.warning("Не удалось очистить закрепы: %s", e)

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
        yes_count = current_yes_count(state)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"⚠️ 15:00 — в опросе только {yes_count} «ДА» "
                        f"из {YES_THRESHOLD} нужных."
                    ),
                )
            except Exception as e:
                logger.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def remind_game(bot):
    """Напоминание об игре — только если набрано 10+ ДА."""
    if current_poll_id is None:
        return
    state = polls.get(current_poll_id)
    if state is None:
        return
    if not state["notified_yes"]:
        return
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="Мужчины, напоминаю что сегодня вы играете. Всем приятной игры и без травм 🏃",
        )
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
    # Чистим состояние
    polls.pop(current_poll_id, None)
    current_poll_id = None
    save_state()
    logger.info("Состояние очищено")


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = answer.user.id

    logger.info(
        "Ответ: poll_id=%s, user_id=%s, options=%s",
        poll_id, user_id, answer.option_ids,
    )

    state = polls.get(poll_id)
    if state is None:
        logger.warning("poll_id=%s не найден, игнорирую", poll_id)
        return

    # option_ids[0] = "ДА", option_ids[1] = "Нет"
    full_name = (answer.user.first_name or "") + (" " + answer.user.last_name if answer.user.last_name else "")
    full_name = full_name.strip() or f"id{user_id}"
    if 0 in answer.option_ids:
        state["yes_voters"][user_id] = full_name
    else:
        state["yes_voters"].pop(user_id, None)
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

    state["yes_count"] = yes_count
    state["no_count"] = no_count

    # Если poll_answer для какого-то голоса был пропущен, сохраняем корректный счёт из Telegram.
    # Список имён остаётся best-effort и может быть короче агрегированного счёта.
    if tracked_yes_count > yes_count:
        logger.warning(
            "poll_id=%s: tracked yes_voters=%d больше агрегированного yes_count=%d, очищаю список имен",
            poll.id,
            tracked_yes_count,
            yes_count,
        )
        state["yes_voters"] = {}

    save_state()
    logger.info(
        "poll_id=%s, poll update: yes=%d, no=%d, total=%d",
        poll.id,
        yes_count,
        no_count,
        poll.total_voter_count,
    )
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
    """Текущий счёт опроса командой /status (только для админа)."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if current_poll_id is None or current_poll_id not in polls:
        await update.message.reply_text("Нет активного опроса.")
        return
    state = polls[current_poll_id]
    yes_count = current_yes_count(state)
    telegram_yes_count = current_telegram_yes_count(state)
    manual_names = list(state.get("manual_yes_voters", {}).values())
    manual_yes_count = len(manual_names)
    no_count = int(state.get("no_count", 0))
    real_names = list(state["yes_voters"].values())
    sections = []
    if real_names:
        sections.append("Реальные «ДА»:\n" + "\n".join(f"{i+1}. {n}" for i, n in enumerate(real_names)))
    if manual_names:
        sections.append("Виртуальные "+"+1"+":\n" + "\n".join(f"{i+1}. {n}" for i, n in enumerate(manual_names)))
    names_text = "\n\n".join(sections) if sections else "—"
    tracked_hint = ""
    if len(real_names) != telegram_yes_count:
        tracked_hint = "\n\nСписок реальных имен может быть неполным: счёт берётся из самого опроса Telegram."
    await update.message.reply_text(
        f"«ДА»: {telegram_yes_count} + {manual_yes_count} вручную = {yes_count} / {YES_THRESHOLD}\n"
        f"«Нет»: {no_count}\n\n{names_text}{tracked_hint}"
    )


async def cmd_plus1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавляет виртуальный +1 к текущему опросу (только для админа)."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if current_poll_id is None or current_poll_id not in polls:
        await update.message.reply_text("Нет активного опроса.")
        return

    state = polls[current_poll_id]
    label = " ".join(context.args).strip() or f"+1 от админа #{int(state.get('manual_yes_seq', 0)) + 1}"
    add_manual_yes_vote(state, label)
    save_state()
    await maybe_send_threshold_notifications(context.bot, current_poll_id, state)

    total_yes = current_yes_count(state)
    manual_yes_count = len(state.get("manual_yes_voters", {}))
    await update.message.reply_text(
        f"Добавил виртуальный +1: {label}\n"
        f"Теперь «ДА»: {total_yes} (из них вручную: {manual_yes_count})."
    )


async def cmd_minus1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Убирает последний виртуальный +1 из текущего опроса (только для админа)."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if current_poll_id is None or current_poll_id not in polls:
        await update.message.reply_text("Нет активного опроса.")
        return

    state = polls[current_poll_id]
    removed_label = remove_last_manual_yes_vote(state)
    if removed_label is None:
        await update.message.reply_text("Виртуальных +1 сейчас нет.")
        return

    save_state()
    total_yes = current_yes_count(state)
    manual_yes_count = len(state.get("manual_yes_voters", {}))
    await update.message.reply_text(
        f"Убрал виртуальный +1: {removed_label}\n"
        f"Теперь «ДА»: {total_yes} (из них вручную: {manual_yes_count})."
    )


def reschedule_jobs(scheduler, bot):
    """Пересоздаёт все cron-задания в планировщике по текущему schedule_config."""
    for job_id in ("job_poll", "job_deadline", "job_close", "job_remind_wed", "job_remind_sun"):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    cfg = schedule_config
    scheduler.add_job(
        send_poll, "cron", id="job_poll",
        day_of_week=cfg["poll_days"],
        hour=cfg["poll_hour"], minute=cfg["poll_minute"],
        args=[bot], misfire_grace_time=3600,
    )
    scheduler.add_job(
        check_deadline, "cron", id="job_deadline",
        day_of_week=cfg["deadline_days"],
        hour=cfg["deadline_hour"], minute=cfg["deadline_minute"],
        args=[bot], misfire_grace_time=3600,
    )
    scheduler.add_job(
        close_poll, "cron", id="job_close",
        day_of_week=cfg["close_days"],
        hour=cfg["close_hour"], minute=cfg["close_minute"],
        args=[bot], misfire_grace_time=3600,
    )
    scheduler.add_job(
        remind_game, "cron", id="job_remind_wed",
        day_of_week=cfg["remind_wed_days"],
        hour=cfg["remind_wed_hour"], minute=cfg["remind_wed_minute"],
        args=[bot], misfire_grace_time=3600,
    )
    scheduler.add_job(
        remind_game, "cron", id="job_remind_sun",
        day_of_week=cfg["remind_sun_days"],
        hour=cfg["remind_sun_hour"], minute=cfg["remind_sun_minute"],
        args=[bot], misfire_grace_time=3600,
    )
    logger.info("Расписание пересоздано: %s", cfg)


async def post_init(application: Application):
    if not ENABLE_SCHEDULER:
        logger.info("Планировщик отключен (ENABLE_SCHEDULER=0).")
        return

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    reschedule_jobs(scheduler, application.bot)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Планировщик запущен.")


SETTIME_KEYS = {
    "poll":        ("poll_hour",        "poll_minute",        "опрос (ср/вс)"),
    "deadline":    ("deadline_hour",    "deadline_minute",    "дедлайн (ср/вс)"),
    "close":       ("close_hour",       "close_minute",       "закрытие опроса (ср/вс)"),
    "remind_wed":  ("remind_wed_hour",  "remind_wed_minute",  "напоминание среда"),
    "remind_sun":  ("remind_sun_hour",  "remind_sun_minute",  "напоминание воскресенье"),
}


def _schedule_text() -> str:
    cfg = schedule_config
    return (
        "📅 *Текущее расписание:*\n"
        f"  `poll`        — опрос           {cfg['poll_days']}  {cfg['poll_hour']:02d}:{cfg['poll_minute']:02d}\n"
        f"  `deadline`    — дедлайн         {cfg['deadline_days']}  {cfg['deadline_hour']:02d}:{cfg['deadline_minute']:02d}\n"
        f"  `close`       — закрытие        {cfg['close_days']}  {cfg['close_hour']:02d}:{cfg['close_minute']:02d}\n"
        f"  `remind_wed`  — напомин. ср     {cfg['remind_wed_days']}  {cfg['remind_wed_hour']:02d}:{cfg['remind_wed_minute']:02d}\n"
        f"  `remind_sun`  — напомин. вс     {cfg['remind_sun_days']}  {cfg['remind_sun_hour']:02d}:{cfg['remind_sun_minute']:02d}\n\n"
        "Время: `/settime poll 08:30`\n"
        "Дни: `/setdays poll mon,wed,fri`"
    )


async def cmd_settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменяет время расписания прямо из бота. /settime [ключ] [ЧЧ:ММ]"""
    if update.effective_user.id not in ADMIN_IDS:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(_schedule_text(), parse_mode="Markdown")
        return

    key = args[0].lower()
    if key not in SETTIME_KEYS:
        valid = ", ".join(f"`{k}`" for k in SETTIME_KEYS)
        await update.message.reply_text(
            f"Неизвестный ключ. Доступные: {valid}", parse_mode="Markdown"
        )
        return

    try:
        h_str, m_str = args[1].split(":")
        hour, minute = int(h_str), int(m_str)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        await update.message.reply_text(
            "Неверный формат. Пример: `/settime poll 08:30`", parse_mode="Markdown"
        )
        return

    hour_key, minute_key, label = SETTIME_KEYS[key]
    old_h = schedule_config[hour_key]
    old_m = schedule_config[minute_key]
    schedule_config[hour_key] = hour
    schedule_config[minute_key] = minute
    save_state()

    scheduler = context.application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        reschedule_jobs(scheduler, context.bot)

    await update.message.reply_text(
        f"✅ *{label}*: `{old_h:02d}:{old_m:02d}` → `{hour:02d}:{minute:02d}`\n\n"
        + _schedule_text(),
        parse_mode="Markdown",
    )


VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

SETDAYS_KEYS = {
    "poll":       "poll_days",
    "deadline":   "deadline_days",
    "close":      "close_days",
    "remind_wed": "remind_wed_days",
    "remind_sun": "remind_sun_days",
}


async def cmd_setdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменяет дни недели расписания. /setdays [ключ] [mon,tue,...]"""
    if update.effective_user.id not in ADMIN_IDS:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(_schedule_text(), parse_mode="Markdown")
        return

    key = args[0].lower()
    if key not in SETDAYS_KEYS:
        valid = ", ".join(f"`{k}`" for k in SETDAYS_KEYS)
        await update.message.reply_text(
            f"Неизвестный ключ. Доступные: {valid}", parse_mode="Markdown"
        )
        return

    raw = args[1].lower()
    parts = [d.strip() for d in raw.split(",") if d.strip()]
    invalid = [d for d in parts if d not in VALID_DAYS]
    if not parts or invalid:
        await update.message.reply_text(
            f"Неверные дни: `{',' .join(invalid) if invalid else '(пусто)'}`.\n"
            "Допустимые: `mon tue wed thu fri sat sun`",
            parse_mode="Markdown",
        )
        return

    cfg_key = SETDAYS_KEYS[key]
    old_days = schedule_config[cfg_key]
    new_days = ",".join(parts)
    schedule_config[cfg_key] = new_days
    save_state()

    scheduler = context.application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        reschedule_jobs(scheduler, context.bot)

    await update.message.reply_text(
        f"✅ *{key}* дни: `{old_days}` → `{new_days}`\n\n" + _schedule_text(),
        parse_mode="Markdown",
    )


async def post_shutdown(application: Application):
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown()


def main():
    logger.info("Запуск экземпляра '%s' с env-файлом: %s", INSTANCE_NAME, ENV_PATH)
    load_state()
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    builder = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
    )
    if proxy_url:
        builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
        logger.info(f"Используется прокси: {proxy_url}")
    app = builder.build()
    app.add_handler(PollHandler(handle_poll_update))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("plus1", cmd_plus1))
    app.add_handler(CommandHandler("minus1", cmd_minus1))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("setdays", cmd_setdays))

    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=["poll", "poll_answer", "message"])


if __name__ == "__main__":
    main()
