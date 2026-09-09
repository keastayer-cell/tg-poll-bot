#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
ENV_PATH="$PROJECT_DIR/.env.stage"
PID_FILE="$PROJECT_DIR/.stage-bot.pid"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Локальное окружение не найдено. Сначала выполните: make setup" >&2
    exit 1
fi

if [[ ! -f "$ENV_PATH" ]]; then
    echo "Файл .env.stage не найден. Создайте его из .env.stage.example." >&2
    exit 1
fi

if [[ -f "$PID_FILE" ]]; then
    OLD_PID="$(cat "$PID_FILE")"
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stage-бот уже запущен, PID: $OLD_PID" >&2
        exit 1
    fi
    rm -f "$PID_FILE"
fi

echo "$$" > "$PID_FILE"
cd "$PROJECT_DIR"
exec env ENV_FILE=.env.stage "$PYTHON_BIN" bot.py
