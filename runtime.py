import logging
from dataclasses import dataclass
from typing import Optional

from models import BotSnapshot, ScheduleConfig, snapshot_from_json
from storage import JsonStateRepository, StateLoadError


@dataclass
class BotRuntime:
    repository: JsonStateRepository
    default_schedule: ScheduleConfig
    logger: logging.Logger
    schema_version: int = 2

    def __post_init__(self) -> None:
        self.polls: dict = {}
        self.current_poll_id: Optional[str] = None
        self.last_poll_message_id: Optional[int] = None
        self.schedule_config: dict = dict(self.default_schedule)

    def snapshot(self) -> BotSnapshot:
        return BotSnapshot(
            polls=self.polls,
            current_poll_id=self.current_poll_id,
            last_poll_message_id=self.last_poll_message_id,
            schedule_config=self.schedule_config,
        )

    def save(self) -> None:
        self.repository.save(self.snapshot().to_json(self.schema_version))

    def load(self) -> None:
        data = self.repository.load()
        if data is None:
            return
        if self.repository.recovered_from_backup:
            self.logger.warning(
                "Основной state.json повреждён, состояние восстановлено из резервной копии"
            )
        try:
            snapshot = snapshot_from_json(
                data,
                default_schedule=self.default_schedule,
                supported_schema_version=self.schema_version,
            )
        except (TypeError, ValueError) as error:
            raise StateLoadError(str(error)) from error

        self.polls = snapshot.polls
        self.current_poll_id = snapshot.current_poll_id
        self.last_poll_message_id = snapshot.last_poll_message_id
        self.schedule_config = snapshot.schedule_config
        self.logger.info(
            "Состояние восстановлено: current_poll_id=%s, опросов=%d",
            self.current_poll_id,
            len(self.polls),
        )
        self.logger.info("Расписание из state.json: %s", self.schedule_config)
