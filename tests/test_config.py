import pytest

from config import SettingsError, load_settings


def valid_env():
    return {
        "BOT_TOKEN": "123:test",
        "CHAT_ID": "-100123",
        "ADMIN_ID": "42",
        "EXTRA_ADMIN_IDS": "42, 43",
        "TIMEZONE": "Europe/Moscow",
        "YES_THRESHOLD": "10",
    }


def test_settings_are_validated_and_admins_are_deduplicated(tmp_path):
    settings = load_settings(str(tmp_path), valid_env())

    assert settings.chat_id == -100123
    assert settings.admin_ids == (42, 43)
    assert settings.yes_threshold == 10
    assert settings.enable_scheduler is True
    assert settings.data_dir == tmp_path


def test_missing_token_has_clear_error(tmp_path):
    env = valid_env()
    env.pop("BOT_TOKEN")

    with pytest.raises(SettingsError, match="BOT_TOKEN"):
        load_settings(str(tmp_path), env)


def test_invalid_timezone_is_rejected(tmp_path):
    env = valid_env()
    env["TIMEZONE"] = "Mars/Olympus"

    with pytest.raises(SettingsError, match="часовой пояс"):
        load_settings(str(tmp_path), env)


def test_non_positive_threshold_is_rejected(tmp_path):
    env = valid_env()
    env["YES_THRESHOLD"] = "0"

    with pytest.raises(SettingsError, match="YES_THRESHOLD"):
        load_settings(str(tmp_path), env)
