from dataclasses import dataclass
from typing import Literal, Optional, TypedDict


class ManualVote(TypedDict):
    label: str
    added_by_user_id: Optional[int]
    added_by_name: Optional[str]
    added_at: Optional[str]
    source: str


@dataclass(frozen=True)
class NotificationEvent:
    audience: Literal["chat", "admins"]
    text: str
