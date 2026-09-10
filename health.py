from datetime import datetime, timezone
from typing import Optional

from telegram.error import TelegramError

from storage import JsonStateRepository


class HealthReporter:
    def __init__(self, path: str, failure_threshold: int = 3):
        self.repository = JsonStateRepository(path)
        self.failure_threshold = failure_threshold
        self.consecutive_failures = 0
        self.alert_failure = False
        self.alert_recovery = False

    async def probe(
        self,
        bot,
        *,
        instance_name: str,
        scheduler_running: bool,
        active_poll_id: Optional[str],
        now: Optional[datetime] = None,
    ) -> bool:
        checked_at = now or datetime.now(timezone.utc)
        self.alert_failure = False
        self.alert_recovery = False
        previous = self.repository.load() or {}
        report = {
            "status": "error",
            "checked_at": checked_at.isoformat(),
            "last_success_at": previous.get("last_success_at"),
            "instance_name": instance_name,
            "scheduler_running": scheduler_running,
            "active_poll_id": active_poll_id,
        }

        try:
            bot_user = await bot.get_me()
        except TelegramError as error:
            self.consecutive_failures += 1
            if self.consecutive_failures == self.failure_threshold:
                self.alert_failure = True
            report["error_type"] = type(error).__name__
            report["consecutive_failures"] = self.consecutive_failures
            self.repository.save(report)
            return False

        if self.consecutive_failures >= self.failure_threshold:
            self.alert_recovery = True
        self.consecutive_failures = 0
        report.update(
            {
                "status": "ok",
                "last_success_at": checked_at.isoformat(),
                "bot_id": bot_user.id,
                "consecutive_failures": 0,
            }
        )
        self.repository.save(report)
        return True
