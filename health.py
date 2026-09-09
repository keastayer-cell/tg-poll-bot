from datetime import datetime, timezone
from typing import Optional

from storage import JsonStateRepository


class HealthReporter:
    def __init__(self, path: str):
        self.repository = JsonStateRepository(path)

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
        except Exception as error:
            report["error_type"] = type(error).__name__
            self.repository.save(report)
            return False

        report.update(
            {
                "status": "ok",
                "last_success_at": checked_at.isoformat(),
                "bot_id": bot_user.id,
            }
        )
        self.repository.save(report)
        return True
