import asyncio
from types import SimpleNamespace

import bot_service as bot
from handlers.polls import PollHandlers

from .fakes import FakeBot


class FakeApplication:
    def __init__(self):
        self.tasks = []

    def create_task(self, coroutine, **kwargs):
        self.tasks.append(coroutine)


def poll_state():
    return {
        "yes_voters": {42: "Иванов Иван"},
        "manual_yes_voters": {},
        "manual_yes_seq": 0,
        "yes_count": 10,
        "no_count": 0,
        "last_total_yes_count": 10,
        "last_removed_yes_label": None,
        "notified_almost": True,
        "notified_yes": True,
        "notified_deadline": False,
    }


def poll_update(yes_count):
    return SimpleNamespace(
        poll=SimpleNamespace(
            id="poll",
            options=[SimpleNamespace(voter_count=yes_count), SimpleNamespace(voter_count=1)],
            total_voter_count=yes_count + 1,
        )
    )


def poll_answer():
    return SimpleNamespace(
        poll_answer=SimpleNamespace(
            poll_id="poll",
            user=SimpleNamespace(id=42, first_name="Иванов", last_name="Иван"),
            option_ids=[1],
        )
    )


def prepare(monkeypatch):
    state = poll_state()
    fake_bot = FakeBot()
    application = FakeApplication()
    context = SimpleNamespace(bot=fake_bot, application=application)
    monkeypatch.setattr(bot, "polls", {"poll": state})
    monkeypatch.setattr(bot, "save_state", lambda: None)
    monkeypatch.setattr(bot, "POLL_RECONCILE_DELAY_SECONDS", 0)
    handlers = PollHandlers(
        polls=bot.polls,
        save_state=bot.save_state,
        notify_thresholds=bot.maybe_send_threshold_notifications,
        reconcile_decrease=bot.reconcile_poll_decrease,
        logger=bot.logger,
    )
    return state, fake_bot, application, context, handlers


async def run_scheduled_tasks(application):
    for coroutine in application.tasks:
        await coroutine


def assert_named_quorum_warning(fake_bot):
    assert [message["text"] for message in fake_bot.messages] == [
        "Иванов Иван слился. Нас снова не хватает: 9 из 10."
    ]


def test_poll_then_poll_answer_keeps_departing_name(monkeypatch):
    state, fake_bot, application, context, handlers = prepare(monkeypatch)

    asyncio.run(handlers.update(poll_update(9), context))
    assert state["yes_voters"] == {42: "Иванов Иван"}
    asyncio.run(handlers.answer(poll_answer(), context))
    asyncio.run(run_scheduled_tasks(application))

    assert_named_quorum_warning(fake_bot)
    assert state["yes_voters"] == {}


def test_poll_answer_then_poll_keeps_departing_name(monkeypatch):
    state, fake_bot, application, context, handlers = prepare(monkeypatch)

    asyncio.run(handlers.answer(poll_answer(), context))
    asyncio.run(handlers.update(poll_update(9), context))
    asyncio.run(run_scheduled_tasks(application))

    assert_named_quorum_warning(fake_bot)
    assert state["yes_voters"] == {}
