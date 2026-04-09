# tg-poll-bot

Telegram-бот для автоматического создания опросов в групповом чате.

## Версии

| Компонент | Версия |
|---|---|
| Python | 3.12.3 |
| python-telegram-bot | 20.7 |
| APScheduler | 3.10.4 |
| python-dotenv | 1.0.0 |

## История изменений

| Дата | Изменение |
|---|---|
| 2026-04-07 | Создан бот, запущен на Mac через launchd |
| 2026-04-08 | Перенесён на VPS (195.133.49.214), файлы в /opt/bot_tg/ |
| 2026-04-08 | Время опроса изменено на 09:50 МСК |
| 2026-04-08 | CHAT_ID изменён на новый чат |
| 2026-04-08 | Добавлено сохранение состояния в state.json (бот помнит голоса после перезапуска) |
| 2026-04-08 | Добавлено автоматическое закрытие опроса в 20:00 МСК |
| 2026-04-08 | Добавлено напоминание об игре (ср 19:45, вс 18:15) если набрано 10+ ДА |

## Что делает бот

- В **среду и воскресенье в 09:50 МСК** автоматически создаёт неанонимный опрос "Идете?" в чате
- Закрепляет опрос с уведомлением участников
- При **9 голосах "ДА"** пишет в чат: "Братики, еще 1 и идем 💪"
- При **10 голосах "ДА"** пишет в чат: "Ну все, епта, идем играть, готовьтесь 🔥"
- В **15:00 МСК** если порог не набран — уведомляет админов
- В **20:00 МСК** автоматически закрывает опрос и очищает состояние
- В **среду 19:45** и **воскресенье 18:15** МСК — если 10+ ДА — пишет в чат: "Мужчины, напоминаю что сегодня вы играете..."
- Сохраняет состояние в `state.json` — после перезапуска помнит все голоса
- Команды для админов: `/poll` (запуск вручную), `/status` (текущий счёт)
- Команда для всех: `/start`

## Структура файлов

```
/opt/bot_tg/
├── bot.py          # основной код бота
├── .env            # конфигурация (токен, chat_id и др.)
├── state.json      # состояние опросов (создаётся автоматически)
├── bot.log         # лог (создаётся автоматически)
└── README.md       # этот файл

/root/venv/         # виртуальное окружение Python
/etc/systemd/system/tg-poll-bot.service  # systemd сервис
```

## Конфигурация (.env)

```
BOT_TOKEN=<токен от @BotFather>
CHAT_ID=<id группового чата>
ADMIN_ID=<telegram id главного админа>
EXTRA_ADMIN_IDS=<telegram id доп. админов через запятую>
TIMEZONE=Europe/Moscow
YES_THRESHOLD=10
POLL_QUESTION=Идете?
```

## Развёртывание на VPS (Ubuntu 24.04)

### 1. Установить Python и venv
```bash
apt-get update
apt-get install -y python3 python3-venv
python3 -m venv /root/venv
```

### 2. Установить зависимости
```bash
/root/venv/bin/pip install python-telegram-bot==20.7 APScheduler==3.10.4 python-dotenv==1.0.0
```

### 3. Разместить файлы
```bash
mkdir -p /opt/bot_tg
# скопировать bot.py и .env в /opt/bot_tg/
```

### 4. Создать systemd сервис
```bash
cat > /etc/systemd/system/tg-poll-bot.service << 'EOF'
[Unit]
Description=Telegram Poll Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/bot_tg
ExecStart=/root/venv/bin/python /opt/bot_tg/bot.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/bot_tg/.env

[Install]
WantedBy=multi-user.target
EOF
```

### 5. Запустить сервис
```bash
systemctl daemon-reload
systemctl enable tg-poll-bot
systemctl start tg-poll-bot
systemctl status tg-poll-bot
```

### Полезные команды

```bash
# статус
systemctl status tg-poll-bot

# логи в реальном времени
journalctl -u tg-poll-bot -f

# перезапуск после изменений
systemctl restart tg-poll-bot

# остановить
systemctl stop tg-poll-bot

# отключить автозапуск
systemctl disable tg-poll-bot
```
