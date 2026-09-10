class CommonHandlers:
    def __init__(self, *, admin_ids: list[int], send_poll, logger):
        self.admin_ids = set(admin_ids)
        self.send_poll = send_poll
        self.logger = logger

    async def start(self, update, context) -> None:
        await update.message.reply_text(
            "Бля, ты чо меня будишь, а братик 😅\n"
            "Я просто бот и делаю для уважаемых людей опрос.\n"
            "Отвали по брацки 🙂"
        )

    async def poll(self, update, context) -> None:
        if update.effective_user.id not in self.admin_ids:
            return
        created = await self.send_poll(context.bot)
        message = (
            "Опрос запущен вручную." if created else "Сегодняшний активный опрос уже существует."
        )
        await update.message.reply_text(message)

    async def error(self, update, context) -> None:
        error = context.error
        self.logger.error(
            "Необработанная ошибка при обработке Telegram update=%r",
            update,
            exc_info=(type(error), error, error.__traceback__) if error else None,
        )
