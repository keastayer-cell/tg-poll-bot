from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from models import ManualVote


def current_yes_count(state: dict) -> int:
    telegram_yes_count = int(state.get("yes_count", len(state.get("yes_voters", {}))))
    manual_yes_count = len(state.get("manual_yes_voters", {}))
    return telegram_yes_count + manual_yes_count


def current_telegram_yes_count(state: dict) -> int:
    return int(state.get("yes_count", len(state.get("yes_voters", {}))))


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


def manual_vote_label(value) -> str:
    return normalize_manual_vote(value)["label"]


def manual_vote_labels(state: dict) -> list[str]:
    return [manual_vote_label(value) for value in state.get("manual_yes_voters", {}).values()]


def add_manual_yes_vote(
    state: dict,
    label: str,
    *,
    added_by_user_id: Optional[int] = None,
    added_by_name: Optional[str] = None,
    source: str = "unknown",
    timezone: str = "Europe/Moscow",
    now: Optional[datetime] = None,
) -> str:
    next_seq = int(state.get("manual_yes_seq", 0)) + 1
    state["manual_yes_seq"] = next_seq
    manual_key = f"manual:{next_seq}"
    added_at = now or datetime.now(ZoneInfo(timezone))
    state.setdefault("manual_yes_voters", {})[manual_key] = {
        "label": label,
        "added_by_user_id": added_by_user_id,
        "added_by_name": added_by_name,
        "added_at": added_at.isoformat(),
        "source": source,
    }
    return manual_key


def remove_manual_yes_vote(state: dict, query: Optional[str] = None) -> Optional[ManualVote]:
    manual_yes_voters = state.get("manual_yes_voters", {})
    if not manual_yes_voters:
        return None
    manual_key = None
    if query:
        normalized_query = " ".join(query.split()).casefold()
        for key in reversed(manual_yes_voters):
            label = manual_vote_label(manual_yes_voters[key]).casefold()
            if key.casefold() == normalized_query or label == normalized_query:
                manual_key = key
                break
        if manual_key is None:
            return None
    else:
        manual_key = next(reversed(manual_yes_voters))
    return normalize_manual_vote(manual_yes_voters.pop(manual_key))
