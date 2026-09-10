import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from models import ManualVote, NotificationEvent, normalize_manual_vote

PLUS_ONE_PATTERN = re.compile(r"^\+1(?:\s+(.+))?$")


def display_user_name(user) -> str:
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    full_name = full_name.strip()
    if full_name:
        return full_name
    if getattr(user, "username", None):
        return f"@{user.username}"
    return f"id{user.id}"


def parse_plus_one(text: str, author_name: str) -> Optional[str]:
    match = PLUS_ONE_PATTERN.fullmatch(text.strip())
    if match is None:
        return None
    guest_name = match.group(1)
    if guest_name:
        return " ".join(guest_name.split())
    return f"Гость от {author_name}"


def current_yes_count(state: dict) -> int:
    telegram_yes_count = int(state.get("yes_count", len(state.get("yes_voters", {}))))
    manual_yes_count = len(state.get("manual_yes_voters", {}))
    return telegram_yes_count + manual_yes_count


def current_telegram_yes_count(state: dict) -> int:
    return int(state.get("yes_count", len(state.get("yes_voters", {}))))


def manual_vote_label(value) -> str:
    return normalize_manual_vote(value)["label"]


def manual_vote_labels(state: dict) -> list[str]:
    return [manual_vote_label(value) for value in state.get("manual_yes_voters", {}).values()]


def add_manual_yes_vote(
    state: dict,
    label: str,
    *,
    added_by_user_id: Optional[int] = None,
    added_by_name: Optional[str] = None,
    source: str = "unknown",
    timezone: str = "Europe/Moscow",
    now: Optional[datetime] = None,
) -> str:
    next_seq = int(state.get("manual_yes_seq", 0)) + 1
    state["manual_yes_seq"] = next_seq
    manual_key = f"manual:{next_seq}"
    added_at = now or datetime.now(ZoneInfo(timezone))
    state.setdefault("manual_yes_voters", {})[manual_key] = {
        "label": label,
        "added_by_user_id": added_by_user_id,
        "added_by_name": added_by_name,
        "added_at": added_at.isoformat(),
        "source": source,
    }
    return manual_key


def remove_manual_yes_vote(state: dict, query: Optional[str] = None) -> Optional[ManualVote]:
    manual_yes_voters = state.get("manual_yes_voters", {})
    if not manual_yes_voters:
        return None
    manual_key = None
    if query:
        normalized_query = " ".join(query.split()).casefold()
        for key in reversed(manual_yes_voters):
            label = manual_vote_label(manual_yes_voters[key]).casefold()
            if key.casefold() == normalized_query or label == normalized_query:
                manual_key = key
                break
        if manual_key is None:
            return None
    else:
        manual_key = next(reversed(manual_yes_voters))
    return normalize_manual_vote(manual_yes_voters.pop(manual_key))


def almost_reached() -> str:
    return "Братики, еще 1 и идем 💪"


def quorum_reached() -> str:
    return "Ну все, епта, идем играть, готовьтесь 🔥"


def admin_quorum_reached(threshold: int) -> str:
    return f"✅ Набрано {threshold} «ДА»! Все идут."


def vote_removed_with_quorum(label: str, yes_count: int) -> str:
    return f"{label} слился. Осталось {yes_count} «ДА», нас пока хватает."


def quorum_lost(label: str, yes_count: int, threshold: int) -> str:
    return f"{label} слился. Нас снова не хватает: {yes_count} из {threshold}."


def evaluate_threshold_transition(
    state: dict, *, yes_count: int, threshold: int
) -> list[NotificationEvent]:
    previous_yes_count = int(state.get("last_total_yes_count", yes_count))
    events = []
    if yes_count < previous_yes_count and state.get("notified_yes", False):
        removed_label = state.get("last_removed_yes_label") or "Кто-то"
        if yes_count < threshold:
            state["notified_yes"] = False
            state["notified_almost"] = True
            events.append(
                NotificationEvent("chat", quorum_lost(removed_label, yes_count, threshold))
            )
        else:
            events.append(
                NotificationEvent("chat", vote_removed_with_quorum(removed_label, yes_count))
            )
    if yes_count == threshold - 1 and not state["notified_almost"] and not state["notified_yes"]:
        state["notified_almost"] = True
        events.append(NotificationEvent("chat", almost_reached()))
    if yes_count >= threshold and not state["notified_yes"]:
        state["notified_yes"] = True
        events.extend(
            [
                NotificationEvent("chat", quorum_reached()),
                NotificationEvent("admins", admin_quorum_reached(threshold)),
            ]
        )
    state["last_total_yes_count"] = yes_count
    state["last_removed_yes_label"] = None
    return events


def poll_instruction() -> str:
    return (
        "Я создал опрос — проголосуйте.\n\n"
        "Если хотите пригласить человека на игру, напишите в чат:\n"
        "<b>+1 ФИО</b>\n\n"
        "Например: <b>+1 Иванов Иван</b>\n\n"
        "Обязательно укажите имя приглашённого, чтобы всем было понятно, кого добавили."
    )


def admin_poll_started(date_text: str, poll_id: str) -> str:
    return (
        f'📋 Я запустил опрос "{date_text}".\n'
        f"ID опроса: {poll_id}\n\n"
        "Я буду сообщать Вам о его результатах."
    )


def deadline_warning(yes_count: int, threshold: int) -> str:
    return f"⚠️ 15:00 — в опросе только {yes_count} «ДА» из {threshold} нужных."


def game_reminder() -> str:
    return "Мужчины, напоминаю что сегодня вы играете. Всем приятной игры и без травм 🏃"


def compact_status(state: dict, threshold: int) -> str:
    yes_count = current_yes_count(state)
    telegram_yes_count = current_telegram_yes_count(state)
    manual_yes_count = len(state.get("manual_yes_voters", {}))
    no_count = int(state.get("no_count", 0))
    return (
        f"«ДА»: {telegram_yes_count} + {manual_yes_count} вручную = {yes_count} / {threshold}\n"
        f"«Нет»: {no_count}"
    )


def detailed_status(state: dict, threshold: int) -> str:
    telegram_yes_count = current_telegram_yes_count(state)
    manual_names = manual_vote_labels(state)
    real_names = list(state.get("yes_voters", {}).values())
    sections = []
    if real_names:
        sections.append(
            "Реальные «ДА»:\n"
            + "\n".join(f"{index + 1}. {name}" for index, name in enumerate(real_names))
        )
    if manual_names:
        sections.append(
            "Виртуальные +1:\n"
            + "\n".join(f"{index + 1}. {name}" for index, name in enumerate(manual_names))
        )
    names_text = "\n\n".join(sections) if sections else "—"
    tracked_hint = ""
    if len(real_names) != telegram_yes_count:
        tracked_hint = (
            "\n\nСписок реальных имен может быть неполным: счёт берётся из самого опроса Telegram."
        )
    return f"{compact_status(state, threshold)}\n\n{names_text}{tracked_hint}"
