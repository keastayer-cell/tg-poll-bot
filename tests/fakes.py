from types import SimpleNamespace


class FakeBot:
    def __init__(self):
        self.messages = []
        self.pinned = []
        self.unpinned = []
        self.unpinned_all = []
        self.stopped_polls = []
        self.poll_message = SimpleNamespace(
            poll=SimpleNamespace(id="new-poll"),
            message_id=200,
        )

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=len(self.messages))

    async def send_poll(self, **kwargs):
        return self.poll_message

    async def pin_chat_message(self, **kwargs):
        self.pinned.append(kwargs)

    async def unpin_chat_message(self, **kwargs):
        self.unpinned.append(kwargs)

    async def unpin_all_chat_messages(self, **kwargs):
        self.unpinned_all.append(kwargs)

    async def stop_poll(self, **kwargs):
        self.stopped_polls.append(kwargs)


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})
        return SimpleNamespace(message_id=len(self.replies))


def make_update(text, user_id=42, first_name="Stayer", last_name=None, chat_id=None):
    message = FakeMessage(text)
    user = SimpleNamespace(
        id=user_id,
        first_name=first_name,
        last_name=last_name,
        username=None,
    )
    chat = SimpleNamespace(id=chat_id if chat_id is not None else -1001234567890)
    return SimpleNamespace(
        message=message,
        effective_message=message,
        effective_user=user,
        effective_chat=chat,
    )
