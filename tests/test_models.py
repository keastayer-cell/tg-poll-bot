import pytest

from models import BotSnapshot, new_poll_state, snapshot_from_json
from scheduling import DEFAULT_SCHEDULE


def test_legacy_snapshot_is_migrated_to_typed_runtime_shape():
    snapshot = snapshot_from_json(
        {
            "polls": {
                "poll": {
                    "yes_voters": {"42": "Иванов Иван"},
                    "manual_yes_voters": {"manual:1": "Старый гость"},
                    "message_id": 100,
                }
            },
            "current_poll_id": "poll",
            "schedule_config": {"poll_hour": 8},
        },
        default_schedule=DEFAULT_SCHEDULE,
        supported_schema_version=2,
    )

    state = snapshot.polls["poll"]
    assert state["yes_voters"] == {42: "Иванов Иван"}
    assert state["manual_yes_voters"]["manual:1"]["source"] == "legacy"
    assert snapshot.last_poll_message_id == 100
    assert snapshot.schedule_config["poll_hour"] == 8
    assert snapshot.schedule_config["close_hour"] == DEFAULT_SCHEDULE["close_hour"]


def test_snapshot_rejects_future_schema():
    with pytest.raises(ValueError, match="новее поддерживаемой"):
        snapshot_from_json(
            {"schema_version": 3},
            default_schedule=DEFAULT_SCHEDULE,
            supported_schema_version=2,
        )


def test_snapshot_serialization_keeps_explicit_schema_version():
    snapshot = BotSnapshot(
        polls={"poll": new_poll_state("2026-09-10")},
        current_poll_id="poll",
        last_poll_message_id=100,
        schedule_config=dict(DEFAULT_SCHEDULE),
    )

    serialized = snapshot.to_json(2)

    assert serialized["schema_version"] == 2
    assert serialized["polls"]["poll"]["poll_date"] == "2026-09-10"
