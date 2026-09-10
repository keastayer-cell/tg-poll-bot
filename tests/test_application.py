import asyncio

from bot_service import build_application


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
