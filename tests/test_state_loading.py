import pytest

import bot
from storage import StateLoadError


class StaticRepository:
    recovered_from_backup = False

    def __init__(self, data):
        self.data = data

    def load(self):
        return self.data


def test_future_state_schema_is_rejected(monkeypatch):
    repository = StaticRepository(
        {
            "schema_version": bot.STATE_SCHEMA_VERSION + 1,
            "polls": {},
            "schedule_config": {},
        }
    )
    monkeypatch.setattr(bot, "state_repository", repository)

    with pytest.raises(StateLoadError, match="новее поддерживаемой"):
        bot.load_state()


def test_invalid_polls_shape_is_rejected(monkeypatch):
    repository = StaticRepository(
        {
            "schema_version": bot.STATE_SCHEMA_VERSION,
            "polls": [],
            "schedule_config": {},
        }
    )
    monkeypatch.setattr(bot, "state_repository", repository)

    with pytest.raises(StateLoadError, match="polls"):
        bot.load_state()
