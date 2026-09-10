# Releases

## Unreleased — reliability refactor

- Preserve other pinned messages when creating a poll.
- Scope `/announce` drafts to an administrator and source chat, with preview,
  confirmation and expiration.
- Store poll state atomically with backup recovery and schema migration.
- Reconcile Telegram `Poll` and `PollAnswer` ordering before departure alerts.
- Record named virtual votes with author, timestamp and source.
- Recover missed scheduled actions and deduplicate reminders after restart.
- Split configuration, models, storage, scheduling, handlers, messages and
  application entry points into modules.
- Add application heartbeat, repeated-failure alerts and recovery notices.
- Add versioned deployment with fresh-heartbeat verification and rollback.
- Add CI, workflow validation, pinned Actions, Dependabot and coverage gate.

Move this section to a dated version only after stage verification and the
controlled production rollout.
