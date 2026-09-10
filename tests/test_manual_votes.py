import asyncio
from types import SimpleNamespace

from handlers.votes import VoteHandlers
from models import normalize_manual_vote
from votes import add_manual_yes_vote, manual_vote_labels, remove_manual_yes_vote

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


class FakeAnnouncementManager:
    async def handle_text(self, update, context):
        return False


def prepare_context():
    state = active_poll_state()
    fake_bot = FakeBot()
    polls = {"poll": state}

    async def notify_thresholds(bot, poll_id, current_state):
        return None

    handlers = VoteHandlers(
        admin_ids=[42],
        target_chat_id=-1001234567890,
        timezone="Europe/Moscow",
        threshold=10,
        polls=polls,
        current_poll_id=lambda: "poll",
        save_state=lambda: None,
        notify_thresholds=notify_thresholds,
        announcement_manager=FakeAnnouncementManager(),
    )
    return state, SimpleNamespace(bot=fake_bot), handlers


def test_plain_plus_one_uses_guest_from_sender_label():
    state, context, handlers = prepare_context()
    update = make_update("+1", first_name="Stayer")

    asyncio.run(handlers.plain_text(update, context))

    assert manual_vote_labels(state) == ["Гость от Stayer"]
    vote = next(iter(state["manual_yes_voters"].values()))
    assert vote["added_by_user_id"] == 42
    assert vote["added_by_name"] == "Stayer"
    assert vote["source"] == "plain_text"
    assert "Гость от Stayer" in update.message.replies[0]["text"]


def test_named_plus_one_remembers_entered_name():
    state, context, handlers = prepare_context()
    update = make_update("+1   Иванов   Иван")

    asyncio.run(handlers.plain_text(update, context))

    assert manual_vote_labels(state) == ["Иванов Иван"]
    assert "Иванов Иван" in update.message.replies[0]["text"]


def test_unrelated_text_is_ignored():
    state, context, handlers = prepare_context()
    update = make_update("Со мной будет +1")

    asyncio.run(handlers.plain_text(update, context))

    assert state["manual_yes_voters"] == {}
    assert update.message.replies == []


def test_legacy_manual_vote_is_normalized():
    assert normalize_manual_vote("Старый гость") == {
        "label": "Старый гость",
        "added_by_user_id": None,
        "added_by_name": None,
        "added_at": None,
        "source": "legacy",
    }


def test_specific_manual_vote_can_be_removed():
    state = active_poll_state()
    add_manual_yes_vote(state, "Иванов Иван")
    add_manual_yes_vote(state, "Петров Петр")

    removed = remove_manual_yes_vote(state, "Иванов Иван")

    assert removed["label"] == "Иванов Иван"
    assert manual_vote_labels(state) == ["Петров Петр"]
