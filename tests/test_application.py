import asyncio
import runpy
from pathlib import Path

from app import bot
from app.bot import build_application


def test_application_can_be_built_without_network_access():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        application = build_application()
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert len(application.handlers[0]) == 13
    assert len(application.error_handlers) == 1


def test_config_and_state_stay_outside_application_package():
    project_root = Path(__file__).resolve().parents[1]

    assert bot.settings.env_path == project_root / ".env"
    assert Path(bot.STATE_FILE) == project_root / "state.json"


def test_module_entrypoint_calls_bot_main(monkeypatch):
    calls = []
    monkeypatch.setattr(bot, "main", lambda: calls.append(True))

    runpy.run_module("app", run_name="__main__")

    assert calls == [True]
