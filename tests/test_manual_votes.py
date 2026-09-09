import asyncio
from types import SimpleNamespace

import bot
from votes import manual_vote_labels

from .fakes import FakeBot, make_update


def active_poll_state():
    return {
        "yes_voters": {},
        "manual_yes_voters": {},
        "manual_yes_seq": 0,
        "yes_count": 3,
        "no_count": 2,
        "last_total_yes_count": 3,
        "last_removed_yes_label": None,
        "notified_almost": False,
        "notified_yes": False,
        "notified_deadline": False,
    }


def prepare_context(monkeypatch):
    state = active_poll_state()
    fake_bot = FakeBot()
    monkeypatch.setattr(bot, "current_poll_id", "poll")
    monkeypatch.setattr(bot, "polls", {"poll": state})
    monkeypatch.setattr(bot, "save_state", lambda: None)
    monkeypatch.setattr(bot.announcement_manager, "pending", {})
    return state, SimpleNamespace(bot=fake_bot)


def test_plain_plus_one_uses_guest_from_sender_label(monkeypatch):
    state, context = prepare_context(monkeypatch)
    update = make_update("+1", first_name="Stayer")

    asyncio.run(bot.handle_admin_plain_text(update, context))

    assert manual_vote_labels(state) == ["Гость от Stayer"]
    vote = next(iter(state["manual_yes_voters"].values()))
    assert vote["added_by_user_id"] == 42
    assert vote["added_by_name"] == "Stayer"
    assert vote["source"] == "plain_text"
    assert "Гость от Stayer" in update.message.replies[0]["text"]


def test_named_plus_one_remembers_entered_name(monkeypatch):
    state, context = prepare_context(monkeypatch)
    update = make_update("+1   Иванов   Иван")

    asyncio.run(bot.handle_admin_plain_text(update, context))

    assert manual_vote_labels(state) == ["Иванов Иван"]
    assert "Иванов Иван" in update.message.replies[0]["text"]


def test_unrelated_text_is_ignored(monkeypatch):
    state, context = prepare_context(monkeypatch)
    update = make_update("Со мной будет +1")

    asyncio.run(bot.handle_admin_plain_text(update, context))

    assert state["manual_yes_voters"] == {}
    assert update.message.replies == []


def test_legacy_manual_vote_is_normalized():
    assert bot.normalize_manual_vote("Старый гость") == {
        "label": "Старый гость",
        "added_by_user_id": None,
        "added_by_name": None,
        "added_at": None,
        "source": "legacy",
    }


def test_specific_manual_vote_can_be_removed():
    state = active_poll_state()
    bot.add_manual_yes_vote(state, "Иванов Иван")
    bot.add_manual_yes_vote(state, "Петров Петр")

    removed = bot.remove_manual_yes_vote(state, "Иванов Иван")

    assert removed["label"] == "Иванов Иван"
    assert manual_vote_labels(state) == ["Петров Петр"]
