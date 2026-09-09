from poll_service import evaluate_threshold_transition


def state(previous, *, notified_yes=False, notified_almost=False, label=None):
    return {
        "last_total_yes_count": previous,
        "last_removed_yes_label": label,
        "notified_yes": notified_yes,
        "notified_almost": notified_almost,
    }


def test_jump_to_quorum_does_not_send_obsolete_almost_message():
    poll_state = state(8)

    events = evaluate_threshold_transition(poll_state, yes_count=10, threshold=10)

    assert [event.audience for event in events] == ["chat", "admins"]
    assert "еще 1" not in " ".join(event.text for event in events)


def test_transition_service_clears_consumed_removed_label():
    poll_state = state(10, notified_yes=True, notified_almost=True, label="Иванов")

    events = evaluate_threshold_transition(poll_state, yes_count=9, threshold=10)

    assert len(events) == 1
    assert "Иванов" in events[0].text
    assert poll_state["last_removed_yes_label"] is None
    assert poll_state["last_total_yes_count"] == 9
