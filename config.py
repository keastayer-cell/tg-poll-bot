import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class SettingsError(ValueError):
    """Raised when required application settings are missing or invalid."""


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise SettingsError(f"Обязательная переменная {key} не задана")
    return value


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw_value = env.get(key, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise SettingsError(f"Переменная {key} должна быть целым числом") from error
    if value <= 0:
        raise SettingsError(f"Переменная {key} должна быть больше нуля")
    return value


def _non_negative_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw_value = env.get(key, str(default))
    try:
        value = float(raw_value)
    except ValueError as error:
        raise SettingsError(f"Переменная {key} должна быть числом") from error
    if value < 0:
        raise SettingsError(f"Переменная {key} не может быть отрицательной")
    return value


@dataclass(frozen=True)
class Settings:
    bot_token: str
    chat_id: int
    admin_ids: tuple[int, ...]
    timezone: str
    yes_threshold: int
    poll_question: str
    enable_scheduler: bool
    instance_name: str
    log_max_bytes: int
    log_backup_count: int
    announce_ttl_seconds: int
    poll_reconcile_delay_seconds: float
    healthcheck_interval_seconds: int
    health_failure_threshold: int
    env_path: Path
    data_dir: Path
    proxy_url: Optional[str]


def load_settings(base_dir: str, environ: Optional[Mapping[str, str]] = None) -> Settings:
    base_path = Path(base_dir)
    if environ is None:
        env_file = os.getenv("ENV_FILE", ".env")
        env_path = base_path / env_file
        load_dotenv(env_path)
        env = os.environ
    else:
        env_file = environ.get("ENV_FILE", ".env")
        env_path = base_path / env_file
        env = environ

    try:
        chat_id = int(_required(env, "CHAT_ID"))
        primary_admin_id = int(_required(env, "ADMIN_ID"))
        extra_admin_ids = [
            int(value.strip())
            for value in env.get("EXTRA_ADMIN_IDS", "").split(",")
            if value.strip()
        ]
    except ValueError as error:
        raise SettingsError("CHAT_ID, ADMIN_ID и EXTRA_ADMIN_IDS должны содержать числа") from error

    timezone = env.get("TIMEZONE", "Europe/Moscow").strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise SettingsError(f"Неизвестный часовой пояс: {timezone}") from error

    poll_question = env.get("POLL_QUESTION", "Идете?").strip()
    if not poll_question:
        raise SettingsError("POLL_QUESTION не может быть пустым")

    admin_ids = tuple(dict.fromkeys([primary_admin_id, *extra_admin_ids]))
    scheduler_value = env.get("ENABLE_SCHEDULER", "1").strip().lower()
    data_dir_value = env.get("DATA_DIR", "").strip()
    data_dir = Path(data_dir_value).expanduser() if data_dir_value else base_path

    return Settings(
        bot_token=_required(env, "BOT_TOKEN"),
        chat_id=chat_id,
        admin_ids=admin_ids,
        timezone=timezone,
        yes_threshold=_positive_int(env, "YES_THRESHOLD", 10),
        poll_question=poll_question,
        enable_scheduler=scheduler_value not in {"0", "false", "no"},
        instance_name=env.get("INSTANCE_NAME", "prod").strip() or "prod",
        log_max_bytes=_positive_int(env, "LOG_MAX_BYTES", 5 * 1024 * 1024),
        log_backup_count=_positive_int(env, "LOG_BACKUP_COUNT", 3),
        announce_ttl_seconds=_positive_int(env, "ANNOUNCE_TTL_SECONDS", 300),
        poll_reconcile_delay_seconds=_non_negative_float(env, "POLL_RECONCILE_DELAY_SECONDS", 0.5),
        healthcheck_interval_seconds=_positive_int(env, "HEALTHCHECK_INTERVAL_SECONDS", 60),
        health_failure_threshold=_positive_int(env, "HEALTH_FAILURE_THRESHOLD", 3),
        env_path=env_path,
        data_dir=data_dir,
        proxy_url=env.get("HTTPS_PROXY") or env.get("https_proxy"),
    )
