# Production deployment

The target layout keeps mutable data separate from versioned application code:

```text
/opt/bot_tg/
├── current -> releases/<release-id>
├── releases/
│   └── <release-id>/
└── shared/
    ├── .env
    ├── state.json
    ├── health.json
    └── bot.log
```

`install_release.sh` prepares a new virtual environment before changing `current`.
After the switch it restarts the service and waits for a fresh application
heartbeat. If the new release does not become healthy, it restores the previous
symlink and restarts that version. After a successful release it keeps the five
newest release directories by default (`BOT_RELEASES_TO_KEEP` changes the limit).

Before using release deployment for the first time:

1. Back up the existing `/opt/bot_tg` directory and stop the bot service.
2. Create the `tg-poll-bot` system user plus `releases`, `shared` and `incoming`
   directories under `/opt/bot_tg`.
3. Copy the currently working application into `releases/bootstrap`, excluding
   `.env`, state, logs, caches and its old virtual environment.
4. Create `releases/bootstrap/venv` and install its `requirements.txt`.
5. Move `.env`, `state.json` and existing logs into `shared`. Set their owner to
   `tg-poll-bot:tg-poll-bot`; secrets and state must have mode `600`.
6. Create `current` as a symlink to `/opt/bot_tg/releases/bootstrap`.
7. Install `tg-poll-bot.service`, run `systemctl daemon-reload`, start it and
   verify both systemd status and the application health-check.
8. Preserve the pre-migration backup until the migrated service has handled a
   complete poll cycle.
9. Create the GitHub `production` environment and place the deploy secrets in it.

The release workflow must not run before this bootstrap is complete: the
installer intentionally requires an existing healthy `current` target so every
deployment has something to roll back to.

Create an archive with repository files at its root, upload it to the server,
then run:

```bash
sudo ./deploy/install_release.sh release.tar.gz <commit-sha>
```

Useful checks:

```bash
systemctl is-active tg-poll-bot
journalctl -u tg-poll-bot -n 100 --no-pager
/opt/bot_tg/current/venv/bin/python /opt/bot_tg/current/deploy/check_bot_health.py
```
