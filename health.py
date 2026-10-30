from datetime import datetime, timezone
from typing import Optional

from telegram.error import TelegramError

from storage import JsonStateRepository


class HealthReporter:
    def __init__(
        self,
        path: str,
        failure_threshold: int = 3,
        recovery_threshold: int = 3,
        notification_cooldown_seconds: int = 3600,
    ):
        self.repository = JsonStateRepository(path)
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.notification_cooldown_seconds = notification_cooldown_seconds
        previous = self.repository.load() or {}
        self.consecutive_failures = previous.get("consecutive_failures", 0)
        self.consecutive_successes = previous.get("consecutive_successes", 0)
        self.alert_failure = False
        self.alert_recovery = False
        self.last_error_type = None

    def notification_due(
        self, admin_id: int, *, recovery: bool = False, now: Optional[datetime] = None
    ) -> bool:
        report = self.repository.load() or {}
        notification = report.get("notifications", {}).get(str(admin_id), {})
        if recovery and not notification.get("failure_delivered"):
            return False
        key = "recovery_attempt_at" if recovery else "failure_attempt_at"
        last_attempt = notification.get(key)
        if not last_attempt:
            return True
        elapsed = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(last_attempt)
        return elapsed.total_seconds() >= self.notification_cooldown_seconds

    def record_notification(
        self,
        admin_id: int,
        *,
        recovery: bool = False,
        delivered: bool = False,
        now: Optional[datetime] = None,
    ) -> None:
        report = self.repository.load() or {}
        notification = report.setdefault("notifications", {}).setdefault(str(admin_id), {})
        key = "recovery_attempt_at" if recovery else "failure_attempt_at"
        if delivered:
            notification["failure_delivered"] = not recovery
        else:
            # Persist before sending: even a timeout must not trigger a retry storm.
            notification[key] = (now or datetime.now(timezone.utc)).isoformat()
        self.repository.save(report)

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
            "notifications": previous.get("notifications", {}),
        }

        try:
            bot_user = await bot.get_me()
        except TelegramError as error:
            self.last_error_type = type(error).__name__
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            if self.consecutive_failures >= self.failure_threshold:
                self.alert_failure = True
            report["error_type"] = type(error).__name__
            report["consecutive_failures"] = self.consecutive_failures
            report["consecutive_successes"] = 0
            self.repository.save(report)
            return False

        self.consecutive_successes += 1
        self.last_error_type = None
        if self.consecutive_successes >= self.recovery_threshold:
            self.alert_recovery = True
        self.consecutive_failures = 0
        report.update(
            {
                "status": "ok",
                "last_success_at": checked_at.isoformat(),
                "bot_id": bot_user.id,
                "consecutive_failures": 0,
                "consecutive_successes": self.consecutive_successes,
            }
        )
        self.repository.save(report)
        return True
