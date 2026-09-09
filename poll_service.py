from messages import (
    admin_quorum_reached,
    almost_reached,
    quorum_lost,
    quorum_reached,
    vote_removed_with_quorum,
)
from models import NotificationEvent


def evaluate_threshold_transition(
    state: dict,
    *,
    yes_count: int,
    threshold: int,
) -> list[NotificationEvent]:
    previous_yes_count = int(state.get("last_total_yes_count", yes_count))
    events = []

    if yes_count < previous_yes_count and state.get("notified_yes", False):
        removed_label = state.get("last_removed_yes_label") or "Кто-то"
        if yes_count < threshold:
            state["notified_yes"] = False
            state["notified_almost"] = True
            events.append(
                NotificationEvent(
                    audience="chat",
                    text=quorum_lost(removed_label, yes_count, threshold),
                )
            )
        else:
            events.append(
                NotificationEvent(
                    audience="chat",
                    text=vote_removed_with_quorum(removed_label, yes_count),
                )
            )

    if yes_count == threshold - 1 and not state["notified_almost"] and not state["notified_yes"]:
        state["notified_almost"] = True
        events.append(NotificationEvent(audience="chat", text=almost_reached()))

    if yes_count >= threshold and not state["notified_yes"]:
        state["notified_yes"] = True
        events.extend(
            [
                NotificationEvent(audience="chat", text=quorum_reached()),
                NotificationEvent(audience="admins", text=admin_quorum_reached(threshold)),
            ]
        )

    state["last_total_yes_count"] = yes_count
    state["last_removed_yes_label"] = None
    return events
