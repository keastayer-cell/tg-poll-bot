from datetime import datetime, timezone

from votes import add_manual_yes_vote, manual_vote_labels, remove_manual_yes_vote


def test_manual_vote_contains_audit_fields():
    state = {"manual_yes_voters": {}, "manual_yes_seq": 0}

    key = add_manual_yes_vote(
        state,
        "Иванов Иван",
        added_by_user_id=42,
        added_by_name="Stayer",
        source="plain_text",
        now=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
    )

    assert key == "manual:1"
    assert state["manual_yes_voters"][key] == {
        "label": "Иванов Иван",
        "added_by_user_id": 42,
        "added_by_name": "Stayer",
        "added_at": "2026-09-10T10:00:00+00:00",
        "source": "plain_text",
    }


def test_remove_by_name_is_case_insensitive():
    state = {"manual_yes_voters": {}, "manual_yes_seq": 0}
    add_manual_yes_vote(state, "Иванов Иван")
    add_manual_yes_vote(state, "Петров Петр")

    removed = remove_manual_yes_vote(state, "иванов иван")

    assert removed["label"] == "Иванов Иван"
    assert manual_vote_labels(state) == ["Петров Петр"]
