class AdminHandlers:
    def __init__(self, *, announcements, schedule):
        self.announcements = announcements
        self.schedule = schedule

    async def announce(self, update, context) -> None:
        await self.announcements.start(update, context)

    async def cancel(self, update, context) -> None:
        await self.announcements.cancel(update, context)

    async def announcement_callback(self, update, context) -> None:
        await self.announcements.handle_callback(update, context)

    async def settime(self, update, context) -> None:
        await self.schedule.settime(update, context)

    async def setdays(self, update, context) -> None:
        await self.schedule.setdays(update, context)
