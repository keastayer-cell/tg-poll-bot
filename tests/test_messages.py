from messages import compact_status, detailed_status, poll_instruction


def state(*, telegram_yes=3, tracked_names=None, manual_names=None, no=2):
    tracked_names = tracked_names or []
    manual_names = manual_names or []
    return {
        "yes_count": telegram_yes,
        "no_count": no,
        "yes_voters": {index: name for index, name in enumerate(tracked_names)},
        "manual_yes_voters": {
            str(index): {"label": name} for index, name in enumerate(manual_names)
        },
    }


def test_poll_instruction_emphasizes_named_guest_format():
    text = poll_instruction()

    assert "<b>+1 ФИО</b>" in text
    assert "<b>+1 Иванов Иван</b>" in text


def test_compact_status_combines_telegram_and_manual_votes():
    report = compact_status(
        state(telegram_yes=3, manual_names=["Иванов Иван", "Гость от Stayer"]),
        threshold=10,
    )

    assert report == "«ДА»: 3 + 2 вручную = 5 / 10\n«Нет»: 2"


def test_detailed_status_lists_names_and_warns_about_untracked_voters():
    report = detailed_status(
        state(
            telegram_yes=3,
            tracked_names=["Николай Туров"],
            manual_names=["Гость от Stayer"],
        ),
        threshold=10,
    )

    assert "1. Николай Туров" in report
    assert "Виртуальные +1:\n1. Гость от Stayer" in report
    assert "Список реальных имен может быть неполным" in report
