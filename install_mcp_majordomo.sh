#!/bin/bash
set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}=================================================${NC}"
echo -e "${CYAN} Установка системы управления MajorDoMo через MCP${NC}"
echo -e "${CYAN}=================================================${NC}"
echo ""
echo -e " Установка производится с правами ${GREEN}$(whoami)${NC}"
echo -e "${YELLOW} Все службы будут запускаться от этой учетной записи${NC}"
echo ""

WHOAMI="www-data"

# === 1. Запрос данных у пользователя ===

# MajorDoMo URL
read -p "IP или домен MajorDoMo (например, http://127.0.0.1): " MAJORDOMO_URL
MAJORDOMO_URL=${MAJORDOMO_URL:-http://127.0.0.1}

# MCP_ENDPOINT
echo
echo -e "${YELLOW}=== Настройка MCP-эндпоинта ===${NC}"
echo "Это WebSocket-адрес, по которому ИИ (xiaozhi) подключается к вашей системе."
echo "Формат: wss://api.xiaozhi.me/mcp/?token=ВАШ_ТОКЕН"
echo "Где взять:"
echo "1. Зарегистрируйтесь на https://xiaozhi.me"
echo "2. Создайте агента и получите токен в настройках"
echo "   Configure Role -> MCP Settings -> Get MCP Endpoint"
echo "3. Скопируйте полный URL из настроек агента"
echo
read -p "MCP_ENDPOINT URL с ключем: " MCP_ENDPOINT

if [ -z "$MCP_ENDPOINT" ]; then
    echo -e "${RED}Ошибка: URL не может быть пустым${NC}"
    exit 1
fi

if ! [[ "$MCP_ENDPOINT" =~ ^wss://.{20,}$ ]]; then
    echo -e "${RED}Ошибка: URL должен начинаться с wss:// и содержать не менее 20 символов после ://${NC}"
    exit 1
fi

# Telegram-бот
echo
echo -e "${YELLOW}=== Настройка Telegram-бота ===${NC}"
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
    read -s -p "Пароль для команд в Telegram (например, secret123): " TELEGRAM_AUTH_PASSWORD
    echo
fi

# Веб-панель
echo
echo -e "${YELLOW}=== Настройка веб-панели ===${NC}"
read -p "Логин для веб-панели (по умолчанию: admin): " WEB_USER
WEB_USER=${WEB_USER:-admin}
read -s -p "Пароль для веб-панели: " WEB_PASS
echo

if [ -z "$WEB_PASS" ]; then
    echo -e "${RED}Ошибка: пароль не может быть пустым${NC}"
    exit 1
fi

# === 2. Создание директорий ===
echo
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}Права на папку и файлы установки: ${GREEN}$WHOAMI${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
INSTALL_DIR="/opt/mcp-bridge"
LOGS_DIR="$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR"
mkdir -p "$LOGS_DIR"

get_python_ge_310() {
    for cmd in python3.14 python3.13 python3.12 python3.11 python3.10; do
        if command -v "$cmd" &> /dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

PYTHON_CMD=$(get_python_ge_310)

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${YELLOW}Ошибка: не найдена версия Python >= 3.10.${NC}"
    exit 1
else
    echo -e "${YELLOW}Найдена подходящая версия Python: $PYTHON_CMD${NC}"
fi

# === 3. Установка зависимостей ===
echo -e "${YELLOW}Установка Python-зависимостей...${NC}"

# Создаём виртуальное окружение
"$PYTHON_CMD" -m venv "$INSTALL_DIR/.venv"

# Устанавливаем зависимости через pip из виртуального окружения
"$INSTALL_DIR/.venv/bin/pip" install --quiet websockets flask requests python-telegram-bot fastmcp python-dotenv requests

# Убедитесь, что все зависимости установлены
if ! /opt/mcp-bridge/.venv/bin/python -c "import requests" &> /dev/null; then
    echo "Устанавливаем недостающие зависимости..."
    sudo /opt/mcp-bridge/.venv/bin/pip install --quiet requests websockets flask python-telegram-bot python-dotenv
fi

# === 4. Скачивание .py файлов с GitHub ===
echo -e "${YELLOW}Скачивание файлов с GitHub...${NC}"
GITHUB_URL="https://raw.githubusercontent.com/golnet1/mcp-majordomo-xiaozhi/main"

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
        echo -e "  ${GREEN}✓ $file — успешно${NC}"
    else
        echo -e "  ${RED}✗ $file — не найден в репозитории${NC}"
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

cat > "$INSTALL_DIR/mcp_config.json" << 'EOF'
{
  "mcpServers": {
    "majordomo-xiaozhi": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp-majordomo-xiaozhi"]
    }
  }
}
EOF

# device_aliases.json
cat > "$INSTALL_DIR/device_aliases.json" << 'EOF'
{
  "освещение": {
    "type": "relay",
    "devices": {
      "улица": {
        "object": "Relay01",
        "property": "status"
      },
      "коридор,прихожая": {
        "object": "Relay02",
        "property": "status"
      },
      "комната отдыха,гостиная,салон": {
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
    }
  },
  "свет": {
    "type": "relay",
    "devices": {
      "кухня": {
        "object": "Relay07",
        "property": "status"
      },
      "спальня": {
        "object": "Relay08",
        "property": "status"
      }
    }
  },
  "колонки": {
    "type": "media",
    "devices": {
      "колонка в комнате отдыха,гостиная": {
        "object": "ESP32_Bedroom",
        "property": "tts"
      }
    }
  },
  "устройства": {
    "type": "device",
    "devices": {
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
    }
  },
  "температура": {
    "type": "sensors",
    "devices": {
      "комната отдыха": {
        "object": "Boiler_Dacha",
        "property": "TempInRoom"
      },
      "парная,сауна": {
        "object": "Steam",
        "property": "getTemp"
      }
    }
  },
  "влажность": {
    "type": "sensors",
    "devices": {
      "парная,сауна": {
        "object": "HumiditySensor",
        "property": "value"
      },
      "душ": {
        "object": "ShowerHumidity",
        "property": "value"
      }
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
echo "v1.0.5" > "$INSTALL_DIR/VERSION"

# === 7. Создание systemd-сервисов ===
SERVICES=(
    "mcp-majordomo.service"
    "mcp-web-panel.service"
    "mcp-scheduler.service"
    "mcp-telegram-bot.service"
    "mcp-log-rotate.service"
    "mcp-log-rotate.timer"
)

cat > "/tmp/mcp-majordomo.service" << EOF
[Unit]
Description=MCP Server for MajorDoMo
After=network.target

[Service]
Type=simple
User=$WHOAMI
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/opt/mcp-bridge/.venv/bin/python3 /opt/mcp-bridge/mcp_pipe.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > "/tmp/mcp-web-panel.service" << EOF
[Unit]
Description=MCP Web Panel for Aliases
After=network.target

[Service]
Type=simple
User=$WHOAMI
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/opt/mcp-bridge/.venv/bin/python3 /opt/mcp-bridge/web_panel.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > "/tmp/mcp-scheduler.service" << EOF
[Unit]
Description=MCP Scheduler
After=network.target

[Service]
Type=simple
User=$WHOAMI
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/opt/mcp-bridge/.venv/bin/python3 /opt/mcp-bridge/scheduler.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > "/tmp/mcp-telegram-bot.service" << EOF
[Unit]
Description=MCP Telegram Bot
After=network.target

[Service]
Type=simple
User=$WHOAMI
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/opt/mcp-bridge/.venv/bin/python3 /opt/mcp-bridge/telegram_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > "/tmp/mcp-log-rotate.service" << EOF
[Unit]
Description=MCP Log Rotation

[Service]
Type=oneshot
User=$WHOAMI
WorkingDirectory=/opt/mcp-bridge
EnvironmentFile=/opt/mcp-bridge/.env
ExecStart=/opt/mcp-bridge/.venv/bin/python3 /opt/mcp-bridge/log_rotator.py
EOF

cat > "/tmp/mcp-log-rotate.timer" << EOF
[Unit]
Description=Ежедневная ротация логов MCP
Requires=mcp-log-rotate.service

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo chown -R "$WHOAMI":"$WHOAMI" "$INSTALL_DIR"
sudo mv /tmp/mcp-*.service /etc/systemd/system/
sudo mv /tmp/mcp-log-rotate.timer /etc/systemd/system/

# === 8. Настройка sudo для обновления ===
echo "$WHOAMI ALL=(ALL) NOPASSWD: /bin/systemctl restart mcp-web-panel mcp-majordomo mcp-scheduler mcp-telegram-bot" | sudo tee /etc/sudoers.d/mcp-bridge >/dev/null

# === 9. Добавление cron для проверки обновлений ===
(crontab -l 2>/dev/null; echo "0 * * * * /usr/bin/python3 /opt/mcp-bridge/check_update.py >> /opt/mcp-bridge/logs/update.log 2>&1") | crontab -

# === 10. Запуск сервисов ===
echo -e "${YELLOW}Применение изменений systemd и запуск служб...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-majordomo mcp-web-panel mcp-scheduler mcp-log-rotate.timer

if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    sudo systemctl enable --now mcp-telegram-bot
fi

# === Финальное сообщение ===
IP=$(hostname -I | awk '{print $1}')
echo
echo -e "${GREEN}===================================================${NC}"
echo -e "${GREEN} Установка завершена!${NC}"
echo
echo -e " Папка установки: ${CYAN}$INSTALL_DIR${NC}"
echo
echo -e " Веб-панель:       ${CYAN}http://$IP:5000${NC}"
echo -e " Логин:            ${CYAN}$WEB_USER${NC}"
echo -e " Пароль:           ${CYAN}$WEB_PASS;${NC}"
echo
echo -e " MajorDoMo:        ${CYAN}$MAJORDOMO_URL${NC}"
echo
echo -e " Логи:             ${CYAN}$INSTALL_DIR/logs/actions.log${NC}"
echo -e "${GREEN}===================================================${NC}"