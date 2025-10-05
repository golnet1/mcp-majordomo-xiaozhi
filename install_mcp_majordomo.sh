#!/bin/bash
set -e

echo "==============================================="
echo " Установка системы управления MajorDoMo через MCP"
echo "==============================================="

# === 1. Запрос данных у пользователя ===

# MajorDoMo URL
read -p "IP или домен MajorDoMo (например, http://127.0.0.1): " MAJORDOMO_URL

# MCP_ENDPOINT
echo
echo "=== Настройка MCP-эндпоинта ==="
echo "Это WebSocket-адрес, по которому ИИ (xiaozhi) подключается к вашей системе."
echo "Формат: wss://api.xiaozhi.me/mcp/?token=ВАШ_ТОКЕН"
echo "Где взять:"
echo "1. Зарегистрируйтесь на https://xiaozhi.me"
echo "2. Создайте агента и получите токен в настройках"
echo "3. Скопируйте полный URL из настроек агента"
echo
read -p "MCP_ENDPOINT (оставьте пустым, если не используете xiaozhi): " MCP_ENDPOINT

# Telegram-бот
echo
echo "=== Настройка Telegram-бота ==="
echo "1. Откройте Telegram и найдите @BotFather"
echo "2. Нажмите /start → /newbot"
echo "3. Введите имя бота (например, HomeControlBot)"
echo "4. Получите токен вида: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
echo
read -p "TELEGRAM_BOT_TOKEN: " TELEGRAM_BOT_TOKEN

if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    echo "5. Напишите своему боту любое сообщение"
    echo "6. Перейдите по ссылке: https://api.telegram.org/botВАШ_ТОКЕН/getUpdates"
    echo "7. Найдите в ответе ваш 'id' (например, \"id\": 123456789)"
    read -p "TELEGRAM_CHAT_ID: " TELEGRAM_CHAT_ID
    read -p "Пароль для команд в Telegram (например, secret123): " TELEGRAM_AUTH_PASSWORD
fi

# Веб-панель
echo
echo "=== Настройка веб-панели ==="
read -p "Логин для веб-панели (по умолчанию: admin): " WEB_USER
WEB_USER=${WEB_USER:-admin}
read -s -p "Пароль для веб-панели: " WEB_PASS
echo

if [ -z "$WEB_PASS" ]; then
    echo "Ошибка: пароль не может быть пустым"
    exit 1
fi

# === 2. Создание директорий ===
INSTALL_DIR="/opt/mcp-bridge"
LOGS_DIR="$INSTALL_DIR/logs"
mkdir -p "$LOGS_DIR"
chown -R $(whoami):$(whoami) "$INSTALL_DIR"

# === 3. Установка зависимостей ===
echo "Установка Python-зависимостей..."
pip3 install --user flask requests python-telegram-bot fastmcp python-dotenv

# === 4. Скачивание .py файлов с GitHub ===
echo "Скачивание файлов с GitHub..."
GITHUB_URL="https://raw.githubusercontent.com/golnet1/mcp-majordomo-xiaozhi/main"

# Список файлов для скачивания
PY_FILES=(
    "mcp_pipe.py"
    "mcp-majordomo-xiaozhi.py"
    "web_panel.py"
    "scheduler.py"
    "telegram_bot.py"
    "action_logger.py"
	"log_rotator.py"
    "check_update.py"
)

for file in "${PY_FILES[@]}"; do
    if curl --output /dev/null --silent --head --fail "$GITHUB_URL/$file"; then
        curl -s -L "$GITHUB_URL/$file" -o "$INSTALL_DIR/$file"
        chmod +x "$INSTALL_DIR/$file"
        echo "  $file — успешно"
    else
        echo "  $file — не найден в репозитории"
    fi
done

# === 5. Создание .env файла ===
cat > "$INSTALL_DIR/.env" << EOF
# MajorDoMo
MAJORDOMO_URL=$MAJORDOMO_URL

# MCP
MCP_ENDPOINT=$MCP_ENDPOINT

# Веб-панель
WEB_PANEL_USER=$WEB_USER
WEB_PANEL_PASS=$WEB_PASS

# Telegram-бот
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
TELEGRAM_AUTH_PASSWORD=$TELEGRAM_AUTH_PASSWORD

# Общие настройки
LOG_LEVEL=INFO
EOF
chmod 600 "$INSTALL_DIR/.env"

# === 6. Создание конфигурационных файлов ===

cat > "$INSTALL_DIR/mcp_config.json.json" << 'EOF'
{
  "mcpServers": {
    "majordomo-xiaozhi": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp-majordomo-xiaozhi"]
    },
    "remote-sse-server": {
      "type": "sse",
      "url": "https://api.example.com/sse",
      "disabled": true
    },
    "remote-http-server": {
      "type": "http",
      "url": "https://api.example.com/mcp",
      "disabled": true
    }
  }
}
EOF

# device_aliases.json
cat > "$INSTALL_DIR/device_aliases.json" << 'EOF'
{
  "освещение": {
    "улица": {
      "object": "Relay01",
      "property": "status"
    },
    "коридор,прихожая": {
      "object": "Relay02",
      "property": "status"
    },
    "комната отдыха,гостинная": {
      "object": "Relay03",
      "property": "status"
    },
    "туалет": {
      "object": "Relay04",
      "property": "status"
    },
    "душ": {
      "object": "Relay05",
      "property": "status"
    },
    "сауна,баня,парная,парилка": {
      "object": "Relay06",
      "property": "status"
    }
  },
  "колонки": {
    "комната отдыха,гостинная": {
      "object": "ESP32_Bedroom",
      "property": "tts"
    }
  },
  "устройства": {
    "септик,канализация": {
      "object": "Relay16",
      "property": "status"
    },
    "бойлер,нагреватель": {
      "object": "Relay17",
      "property": "status"
    },
    "полотенцесушитель,горячая вода": {
      "object": "Relay18",
      "property": "status"
    }
  },
  "климат": {
    "температура в комнате отдыха": {
      "object": "Boiler_Dacha",
      "property": "TempInRoom"
    },
    "температура в парной": {
      "object": "Steam",
      "property": "getTemp"
    },
    "влажность": {
      "object": "HumiditySensor",
      "property": "value"
    }
  }
}
EOF

# schedule.json
cat > "$INSTALL_DIR/schedule.json" << 'EOF'
[
  {
    "id": "morning_routine",
    "enabled": false,
    "description": "Доброе утро",
    "time": "07:30",
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "action": {
      "type": "script",
      "script": "GoodMorning"
    }
  }
]
EOF

# VERSION
echo "v1.0.0" > "$INSTALL_DIR/VERSION"

# === 7. Создание systemd-сервисов ===
cat > /tmp/mcp-majordomo.service << EOF
[Unit]
Description=MCP Server for MajorDoMo
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/usr/bin/python3 mcp-majordomo-xiaozhi.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /tmp/mcp-web-panel.service << EOF
[Unit]
Description=MCP Web Panel for Aliases
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/usr/bin/python3 web_panel.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /tmp/mcp-scheduler.service << EOF
[Unit]
Description=MCP Scheduler
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/usr/bin/python3 scheduler.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /tmp/mcp-telegram-bot.service << EOF
[Unit]
Description=MCP Telegram Bot
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/usr/bin/python3 telegram_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo mv /tmp/mcp-*.service /etc/systemd/system/

# === 8. Настройка sudo для обновления ===
echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/systemctl restart mcp-web-panel mcp-majordomo mcp-scheduler mcp-telegram-bot" | sudo tee /etc/sudoers.d/mcp-bridge >/dev/null

# === 9. Добавление cron для проверки обновлений ===
(crontab -l 2>/dev/null; echo "0 * * * * /usr/bin/python3 /opt/mcp-bridge/check_update.py >> /opt/mcp-bridge/logs/update.log 2>&1") | crontab -

# === 10. Запуск сервисов ===
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-majordomo mcp-web-panel mcp-scheduler

if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    sudo systemctl enable --now mcp-telegram-bot
fi

echo "==============================================="
echo " Установка завершена!"
echo " Веб-панель: http://$(hostname -I | awk '{print $1}'):5000"
echo " Логин: $WEB_USER"
echo " Пароль: $WEB_PASS"
echo " MajorDoMo: $MAJORDOMO_URL"
echo " GitHub: https://github.com/$GITHUB_REPO"
echo " Логи: $INSTALL_DIR/logs/actions.log"
echo "==============================================="