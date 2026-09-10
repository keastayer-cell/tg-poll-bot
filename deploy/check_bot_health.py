import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def check_health(
    path: Path,
    *,
    max_age_seconds: int,
    now: Optional[datetime] = None,
    not_before: Optional[datetime] = None,
) -> tuple[bool, str]:
    if not path.exists():
        return False, f"health-файл не найден: {path}"

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        last_success = datetime.fromisoformat(report["last_success_at"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return False, f"health-файл повреждён: {type(error).__name__}"

    checked_at = now or datetime.now(timezone.utc)
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)
    if not_before is not None:
        if not_before.tzinfo is None:
            not_before = not_before.replace(tzinfo=timezone.utc)
        if last_success < not_before:
            return False, "бот ещё не записал heartbeat после запуска"
    age_seconds = (checked_at - last_success).total_seconds()

    if report.get("status") != "ok":
        return False, f"статус health-check: {report.get('status', 'unknown')}"
    if not report.get("scheduler_running"):
        return False, "планировщик не запущен"
    if age_seconds < 0 or age_seconds > max_age_seconds:
        return False, f"последний успешный запрос был {int(age_seconds)} секунд назад"
    return True, f"бот отвечает, heartbeat {int(age_seconds)} секунд назад"


def main() -> int:
    path = Path(os.getenv("BOT_HEALTH_FILE", "/opt/bot_tg/health.json"))
    try:
        max_age_seconds = int(os.getenv("BOT_HEALTH_MAX_AGE_SECONDS", "180"))
    except ValueError:
        print("BOT_HEALTH_MAX_AGE_SECONDS должен быть целым числом")
        return 2
    if max_age_seconds <= 0:
        print("BOT_HEALTH_MAX_AGE_SECONDS должен быть больше нуля")
        return 2
    not_before_value = os.getenv("BOT_HEALTH_NOT_BEFORE", "").strip()
    try:
        not_before = datetime.fromisoformat(not_before_value) if not_before_value else None
    except ValueError:
        print("BOT_HEALTH_NOT_BEFORE должен быть временем в ISO 8601")
        return 2
    healthy, message = check_health(
        path,
        max_age_seconds=max_age_seconds,
        not_before=not_before,
    )
    print(message)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
