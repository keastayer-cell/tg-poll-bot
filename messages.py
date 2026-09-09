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
