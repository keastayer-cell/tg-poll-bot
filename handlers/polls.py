import logging
from collections.abc import Awaitable, Callable

from votes import current_telegram_yes_count


class PollHandlers:
    def __init__(
        self,
        *,
        polls: dict,
        save_state: Callable[[], None],
        notify_thresholds: Callable[[object, str, dict], Awaitable[None]],
        reconcile_decrease: Callable[[object, str, int], Awaitable[None]],
        logger: logging.Logger,
    ):
        self.polls = polls
        self.save_state = save_state
        self.notify_thresholds = notify_thresholds
        self.reconcile_decrease = reconcile_decrease
        self.logger = logger

    async def answer(self, update, context) -> None:
        answer = update.poll_answer
        poll_id = answer.poll_id
        user_id = answer.user.id
        self.logger.info(
            "Ответ: poll_id=%s, user_id=%s, options=%s",
            poll_id,
            user_id,
            answer.option_ids,
        )

        state = self.polls.get(poll_id)
        if state is None:
            self.logger.warning("poll_id=%s не найден, игнорирую", poll_id)
            return

        full_name = (answer.user.first_name or "") + (
            " " + answer.user.last_name if answer.user.last_name else ""
        )
        full_name = full_name.strip() or f"id{user_id}"
        if 0 in answer.option_ids:
            state["yes_voters"][user_id] = full_name
        else:
            removed_name = state["yes_voters"].pop(user_id, None)
            state["last_removed_yes_label"] = removed_name or full_name
        self.save_state()

        self.logger.info(
            "poll_id=%s, агрегированных «ДА»: %d, отслеженных имён: %d",
            poll_id,
            current_telegram_yes_count(state),
            len(state["yes_voters"]),
        )

    async def update(self, update, context) -> None:
        poll = update.poll
        state = self.polls.get(poll.id)
        if state is None:
            self.logger.warning("poll_id=%s не найден для poll update, игнорирую", poll.id)
            return

        yes_count = poll.options[0].voter_count if len(poll.options) > 0 else 0
        no_count = poll.options[1].voter_count if len(poll.options) > 1 else 0
        tracked_yes_count = len(state["yes_voters"])
        previous_yes_count = current_telegram_yes_count(state)
        state["yes_count"] = yes_count
        state["no_count"] = no_count

        if tracked_yes_count > yes_count:
            self.logger.warning(
                "poll_id=%s: tracked yes_voters=%d больше агрегированного yes_count=%d, ожидаю PollAnswer",
                poll.id,
                tracked_yes_count,
                yes_count,
            )

        self.save_state()
        self.logger.info(
            "poll_id=%s, poll update: yes=%d, no=%d, total=%d",
            poll.id,
            yes_count,
            no_count,
            poll.total_voter_count,
        )
        if yes_count < previous_yes_count:
            context.application.create_task(
                self.reconcile_decrease(context.bot, poll.id, yes_count),
                name=f"reconcile-poll-{poll.id}-{yes_count}",
            )
        else:
            await self.notify_thresholds(context.bot, poll.id, state)
