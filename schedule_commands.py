from collections.abc import Callable

from scheduling import SETDAYS_KEYS, SETTIME_KEYS, VALID_DAYS


class ScheduleAdminCommands:
    def __init__(
        self,
        *,
        admin_ids: list[int],
        schedule_config: dict,
        save_state: Callable[[], None],
        reschedule_jobs: Callable,
    ):
        self.admin_ids = set(admin_ids)
        self.schedule_config = schedule_config
        self.save_state = save_state
        self.reschedule_jobs = reschedule_jobs

    def schedule_text(self) -> str:
        cfg = self.schedule_config
        return (
            "📅 *Текущее расписание:*\n"
            f"  `poll`        — опрос           {cfg['poll_days']}  {cfg['poll_hour']:02d}:{cfg['poll_minute']:02d}\n"
            f"  `deadline`    — дедлайн         {cfg['deadline_days']}  {cfg['deadline_hour']:02d}:{cfg['deadline_minute']:02d}\n"
            f"  `close`       — закрытие        {cfg['close_days']}  {cfg['close_hour']:02d}:{cfg['close_minute']:02d}\n"
            f"  `remind_wed`  — напомин. ср     {cfg['remind_wed_days']}  {cfg['remind_wed_hour']:02d}:{cfg['remind_wed_minute']:02d}\n"
            f"  `remind_sun`  — напомин. вс     {cfg['remind_sun_days']}  {cfg['remind_sun_hour']:02d}:{cfg['remind_sun_minute']:02d}\n\n"
            "Время: `/settime poll 08:30`\n"
            "Дни: `/setdays poll mon,wed,fri`"
        )

    def _apply_running_schedule(self, context) -> None:
        scheduler = context.application.bot_data.get("scheduler")
        if scheduler and scheduler.running:
            self.reschedule_jobs(scheduler, context.bot)

    async def settime(self, update, context) -> None:
        """Handle /settime [key] [HH:MM] for administrators."""
        if update.effective_user.id not in self.admin_ids:
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(self.schedule_text(), parse_mode="Markdown")
            return

        key = args[0].lower()
        if key not in SETTIME_KEYS:
            valid = ", ".join(f"`{item}`" for item in SETTIME_KEYS)
            await update.message.reply_text(
                f"Неизвестный ключ. Доступные: {valid}",
                parse_mode="Markdown",
            )
            return

        try:
            hour_text, minute_text = args[1].split(":")
            hour, minute = int(hour_text), int(minute_text)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            await update.message.reply_text(
                "Неверный формат. Пример: `/settime poll 08:30`",
                parse_mode="Markdown",
            )
            return

        hour_key, minute_key, label = SETTIME_KEYS[key]
        old_hour = self.schedule_config[hour_key]
        old_minute = self.schedule_config[minute_key]
        self.schedule_config[hour_key] = hour
        self.schedule_config[minute_key] = minute
        self.save_state()
        self._apply_running_schedule(context)

        await update.message.reply_text(
            f"✅ *{label}*: `{old_hour:02d}:{old_minute:02d}` → `{hour:02d}:{minute:02d}`\n\n"
            + self.schedule_text(),
            parse_mode="Markdown",
        )

    async def setdays(self, update, context) -> None:
        """Handle /setdays [key] [mon,tue,...] for administrators."""
        if update.effective_user.id not in self.admin_ids:
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(self.schedule_text(), parse_mode="Markdown")
            return

        key = args[0].lower()
        if key not in SETDAYS_KEYS:
            valid = ", ".join(f"`{item}`" for item in SETDAYS_KEYS)
            await update.message.reply_text(
                f"Неизвестный ключ. Доступные: {valid}",
                parse_mode="Markdown",
            )
            return

        parts = [day.strip() for day in args[1].lower().split(",") if day.strip()]
        invalid = [day for day in parts if day not in VALID_DAYS]
        if not parts or invalid:
            invalid_text = ",".join(invalid) if invalid else "(пусто)"
            await update.message.reply_text(
                f"Неверные дни: `{invalid_text}`.\nДопустимые: `mon tue wed thu fri sat sun`",
                parse_mode="Markdown",
            )
            return

        config_key = SETDAYS_KEYS[key]
        old_days = self.schedule_config[config_key]
        new_days = ",".join(parts)
        self.schedule_config[config_key] = new_days
        self.save_state()
        self._apply_running_schedule(context)

        await update.message.reply_text(
            f"✅ *{key}* дни: `{old_days}` → `{new_days}`\n\n" + self.schedule_text(),
            parse_mode="Markdown",
        )
