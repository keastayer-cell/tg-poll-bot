from dataclasses import dataclass
from typing import Literal, Optional, TypedDict


class ManualVote(TypedDict):
    label: str
    added_by_user_id: Optional[int]
    added_by_name: Optional[str]
    added_at: Optional[str]
    source: str


class PollState(TypedDict, total=False):
    yes_voters: dict[int, str]
    manual_yes_voters: dict[str, ManualVote]
    manual_yes_seq: int
    yes_count: int
    no_count: int
    last_total_yes_count: int
    last_removed_yes_label: Optional[str]
    notified_almost: bool
    notified_yes: bool
    notified_deadline: bool
    sent_reminders: list[str]
    poll_date: str
    message_id: int
    close_failed: bool


class ScheduleConfig(TypedDict):
    poll_hour: int
    poll_minute: int
    poll_days: str
    deadline_hour: int
    deadline_minute: int
    deadline_days: str
    close_hour: int
    close_minute: int
    close_days: str
    remind_wed_hour: int
    remind_wed_minute: int
    remind_wed_days: str
    remind_sun_hour: int
    remind_sun_minute: int
    remind_sun_days: str


class PendingAnnouncement(TypedDict):
    source_chat_id: int
    expires_at: float
    draft: Optional[str]


@dataclass
class BotSnapshot:
    polls: dict[str, PollState]
    current_poll_id: Optional[str]
    last_poll_message_id: Optional[int]
    schedule_config: ScheduleConfig

    def to_json(self, schema_version: int) -> dict:
        return {
            "schema_version": schema_version,
            "polls": self.polls,
            "current_poll_id": self.current_poll_id,
            "last_poll_message_id": self.last_poll_message_id,
            "schedule_config": self.schedule_config,
        }


def normalize_manual_vote(value) -> ManualVote:
    if isinstance(value, dict):
        return {
            "label": str(value.get("label", "Гость")),
            "added_by_user_id": value.get("added_by_user_id"),
            "added_by_name": value.get("added_by_name"),
            "added_at": value.get("added_at"),
            "source": value.get("source", "unknown"),
        }
    return {
        "label": str(value),
        "added_by_user_id": None,
        "added_by_name": None,
        "added_at": None,
        "source": "legacy",
    }


def new_poll_state(poll_date: str) -> PollState:
    return {
        "yes_voters": {},
        "manual_yes_voters": {},
        "manual_yes_seq": 0,
        "yes_count": 0,
        "no_count": 0,
        "last_total_yes_count": 0,
        "last_removed_yes_label": None,
        "notified_almost": False,
        "notified_yes": False,
        "notified_deadline": False,
        "sent_reminders": [],
        "poll_date": poll_date,
    }


def snapshot_from_json(
    data: dict,
    *,
    default_schedule: ScheduleConfig,
    supported_schema_version: int,
) -> BotSnapshot:
    schema_version = int(data.get("schema_version", 0))
    if schema_version > supported_schema_version:
        raise ValueError(
            f"Версия state.json {schema_version} новее поддерживаемой {supported_schema_version}"
        )
    if not isinstance(data.get("polls", {}), dict):
        raise ValueError("Поле polls в state.json должно быть объектом")
    if not isinstance(data.get("schedule_config", {}), dict):
        raise ValueError("Поле schedule_config в state.json должно быть объектом")

    polls: dict[str, PollState] = data.get("polls", {})
    for state in polls.values():
        state["yes_voters"] = {
            int(key): value for key, value in state.get("yes_voters", {}).items()
        }
        manual_votes = state.setdefault("manual_yes_voters", {})
        state["manual_yes_voters"] = {
            key: normalize_manual_vote(value) for key, value in manual_votes.items()
        }
        state["manual_yes_seq"] = int(state.get("manual_yes_seq", len(manual_votes)))
        state["yes_count"] = int(state.get("yes_count", len(state["yes_voters"])))
        state["no_count"] = int(state.get("no_count", 0))
        state["last_total_yes_count"] = int(
            state.get("last_total_yes_count", state["yes_count"] + len(manual_votes))
        )
        state.setdefault("last_removed_yes_label", None)
        state.setdefault("sent_reminders", [])

    current_poll_id = data.get("current_poll_id")
    last_poll_message_id = data.get("last_poll_message_id")
    if last_poll_message_id is None and current_poll_id in polls:
        last_poll_message_id = polls[current_poll_id].get("message_id")

    schedule_config = {**default_schedule, **data.get("schedule_config", {})}
    return BotSnapshot(
        polls=polls,
        current_poll_id=current_poll_id,
        last_poll_message_id=last_poll_message_id,
        schedule_config=schedule_config,
    )


@dataclass(frozen=True)
class NotificationEvent:
    audience: Literal["chat", "admins"]
    text: str
