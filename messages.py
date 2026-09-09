from votes import current_telegram_yes_count, current_yes_count, manual_vote_labels


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
