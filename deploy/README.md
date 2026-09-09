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
symlink and restarts that version.

Before using release deployment for the first time:

1. Create the `tg-poll-bot` system user and `/opt/bot_tg/shared`.
2. Move `.env`, `state.json` and existing logs into `shared`.
3. Set their owner to `tg-poll-bot:tg-poll-bot` and mode to `600`.
4. Install `tg-poll-bot.service`, reload systemd and verify the service manually.
5. Preserve the previous installation until the migrated service has handled a
   complete poll cycle.

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
