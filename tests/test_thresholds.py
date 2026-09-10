import asyncio

import bot_service as bot

from .fakes import FakeBot


def poll_state(previous, current, *, notified=True, label="Иванов Иван"):
    return {
        "yes_count": current,
        "yes_voters": {},
        "manual_yes_voters": {},
        "last_total_yes_count": previous,
        "last_removed_yes_label": label,
        "notified_yes": notified,
        "notified_almost": True,
        "notified_deadline": False,
    }


def run_notification(monkeypatch, state):
    fake_bot = FakeBot()
    monkeypatch.setattr(bot, "save_state", lambda: None)
    monkeypatch.setattr(bot, "ADMIN_IDS", [])
    asyncio.run(bot.maybe_send_threshold_notifications(fake_bot, "poll", state))
    return [item["text"] for item in fake_bot.messages]


def test_warns_when_vote_drops_but_quorum_remains(monkeypatch):
    messages = run_notification(monkeypatch, poll_state(12, 11))

    assert messages == ["Иванов Иван слился. Осталось 11 «ДА», нас пока хватает."]


def test_warns_when_quorum_is_lost(monkeypatch):
    state = poll_state(10, 9)

    messages = run_notification(monkeypatch, state)

    assert messages == ["Иванов Иван слился. Нас снова не хватает: 9 из 10."]
    assert state["notified_yes"] is False


def test_does_not_repeat_departure_warning_below_quorum(monkeypatch):
    messages = run_notification(monkeypatch, poll_state(9, 8, notified=False))

    assert messages == []


def test_announces_quorum_again_after_recovery(monkeypatch):
    state = poll_state(9, 10, notified=False)

    messages = run_notification(monkeypatch, state)

    assert messages == ["Ну все, епта, идем играть, готовьтесь 🔥"]
    assert state["notified_yes"] is True
