## 🌐 English | [Русский](#русский)

# 🏠 MCP Bridge for MajorDoMo — Smart Home with AI

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Raspberry%20Pi-lightgrey.svg)](https://www.raspberrypi.org/)

> **MCP Bridge** is a complete smart home control system built on **MajorDoMo**, integrated with the **AI agent [xiaozhi](https://xiaozhi.me)** via the **[MCP (Model Context Protocol)](https://github.com/modelcontextprotocol)**.  
> It supports control via **voice**, **Telegram**, **web interface**, **scheduling**, and **scenarios**.

---

## 📌 Overview

This project provides a complete bridge between **[MajorDoMo](https://github.com/sergejey/majordomo)** (open-source home automation) and **AI agents** using the **MCP protocol**. It includes:

- ✅ **MCP Server** — connects AI to MajorDoMo  
- ✅ **Web Panel** — edit device aliases, view logs, manage settings  
- ✅ **Telegram Bot** — control devices via Telegram  
- ✅ **Scheduler** — automate tasks by time  
- ✅ **Auto-updater** — checks GitHub for new versions  
- ✅ **Unified Logging** — all actions in one place  

✅ Works on **Raspberry Pi**, **Linux servers**.

---

## 🚀 Quick Start

### 1. Prerequisites
- Linux server or Raspberry Pi
- MajorDoMo installed and accessible at `http://YOUR_MAJORDOMO_IP`
- Python 3.8+

### 2. Installation
```bash
# Download the installer
wget https://raw.githubusercontent.com/golnet1/mcp-majordomo-xiaozhi/refs/heads/main/install_mcp_majordomo.sh

# Run the installer (interactive)
chmod +x install_mcp_majordomo.sh
./install_mcp_majordomo.sh
```

Follow the prompts to configure:
- MajorDoMo URL  
- Web panel credentials  
- Telegram bot (optional)  
- MCP endpoint (for xiaozhi)

### 3. Access Web Panel
Open in browser:  
👉 http://YOUR_SERVER_IP:5000  
Login with credentials you provided during installation.

---

## 🧩 Components

| Component        | Description                          | Port / Access |
|------------------|--------------------------------------|---------------|
| **MCP Server**   | Connects AI agents to MajorDoMo      | —             |
| **Web Panel**    | Manage devices, aliases, logs        | `5000`        |
| **Telegram Bot** | Control via Telegram commands        | —             |
| **Scheduler**    | Time-based automation                | —             |
| **Log Viewer**   | Real-time action monitoring          | —             |

---

## 📝 Usage

### Web Panel
- **Edit Aliases**: Add devices like `"улица" → Relay01.status`  
- **View Logs**: See all actions with filtering  
- **Update System**: One-click updates from GitHub  

### Telegram Commands
```text
/auth <password>       — authorize
/light улица включи    — turn on street light
/status улица          — check status
/script GoodMorning    — run scenario
```

### Voice Commands (via xiaozhi)
- «Включи свет в комнате отдыха»  
- «Выключи всё»  
- «Какая температура в парной?»

---

## 🔧 Configuration

All settings are stored in `/opt/mcp-bridge/.env`:
```ini
MAJORDOMO_URL=http://192.168.88.2
WEB_PANEL_USER=admin
WEB_PANEL_PASS=secure_password
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
TELEGRAM_AUTH_PASSWORD=bot_secret
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=...
```

After editing, restart services:
```bash
sudo systemctl restart mcp-*
```

---

## 🔄 Auto-Updates

The system checks for updates **every hour** and shows a notification in the web panel when a new version is available.


---

## 📜 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

- **[MajorDoMo](https://github.com/sergejey/majordomo)** — open-source home automation  
- **[xiaozhi](https://xiaozhi.me)** — AI agent platform  
- **[MCP Protocol](https://modelcontextprotocol.io/)** — standard for AI-tool communication

---

<br><br>
## Русский
# 🏠 MCP Bridge для MajorDoMo — Умный дом с ИИ

[![Лицензия](https://img.shields.io/badge/лицензия-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Платформа](https://img.shields.io/badge/платформа-Linux%20%7C%20Raspberry%20Pi-lightgrey.svg)](https://www.raspberrypi.org/)

> **MCP Bridge** — это полноценная система управления умным домом на базе **[MajorDoMo](https://github.com/sergejey/majordomo)**, интегрированная с **ИИ-агентом [xiaozhi](https://xiaozhi.me)** через протокол **[MCP (Model Context Protocol)](https://modelcontextprotocol.io/)**.  
> Поддерживает управление через **голос**, **Telegram**, **веб-интерфейс**, **расписание** и **сценарии**.

---

## 📌 Обзор

Этот проект обеспечивает полный мост между **[MajorDoMo](https://github.com/sergejey/majordomo)** (открытой системой автоматизации дома) и **ИИ-агентом** с использованием протокола **MCP**. Включает:

- ✅ **MCP-сервер** — подключает ИИ к MajorDoMo  
- ✅ **Веб-панель** — редактирование алиасов, просмотр логов, настройка  
- ✅ **Telegram-бот** — управление через Telegram  
- ✅ **Планировщик** — автоматизация по расписанию  
- ✅ **Автообновление** — проверка обновлений на GitHub  
- ✅ **Единый логгер** — все действия в одном месте  

✅ Работает на **Raspberry Pi**, **Linux-серверах**.

---

### 🚀 Быстрый старт

#### 1. Требования
- Сервер Linux или Raspberry Pi  
- Установленный MajorDoMo по адресу `http://ВАШ_IP_MAJORDOMO`  
- Python 3.8+

#### 2. Установка
```bash
# Скачать установщик
wget https://raw.githubusercontent.com/golnet1/mcp-majordomo-xiaozhi/refs/heads/main/install_mcp_majordomo.sh

# Запустить установщик (интерактивный)
chmod +x install_mcp_majordomo.sh
./install_mcp_majordomo.sh
```

Следуйте инструкциям для настройки:
- URL MajorDoMo  
- Учётные данные веб-панели  
- Telegram-бот (опционально)  
- MCP-эндпоинт (для xiaozhi)

#### 3. Доступ к веб-панели
Откройте в браузере:  
👉 http://IP_ВАШЕГО_СЕРВЕРА:5000  
Войдите с данными, указанными при установке.

---

### 🧩 Компоненты

| Компонент        | Описание                             | Порт / Доступ |
|------------------|--------------------------------------|---------------|
| **MCP-сервер**   | Подключает ИИ к MajorDoMo            | —             |
| **Веб-панель**   | Управление устройствами, алиасами, логами | `5000`    |
| **Telegram-бот** | Управление через команды Telegram    | —             |
| **Планировщик**  | Автоматизация по времени             | —             |
| **Просмотр логов**| Мониторинг действий в реальном времени | —           |

---

### 📝 Использование

#### Веб-панель
- **Редактирование алиасов**: Добавьте устройства вроде `"улица" → Relay01.status`  
- **Просмотр логов**: Все действия с фильтрацией  
- **Обновление системы**: Обновление в один клик из GitHub  

#### Команды Telegram
```text
/auth <пароль>         — авторизация
/light улица включи    — включить свет на улице
/status улица          — проверить статус
/script Доброеутро     — запустить сценарий
```

#### Голосовые команды (через xiaozhi)
- «Включи свет в комнате отдыха»  
- «Выключи всё»  
- «Какая температура в парной?»

---

### 🔧 Настройка

Все параметры хранятся в `/opt/mcp-bridge/.env`:
```ini
MAJORDOMO_URL=http://192.168.88.2
WEB_PANEL_USER=admin
WEB_PANEL_PASS=надёжный_пароль
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
TELEGRAM_AUTH_PASSWORD=секретный_пароль
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=...
```

После редактирования перезапустите сервисы:
```bash
sudo systemctl restart mcp-*
```

---

### 🔄 Автообновление

Система проверяет обновления **каждый час** и показывает уведомление в веб-панели, когда доступна новая версия.

---

### 📜 Лицензия

Распространяется по лицензии **MIT**. Подробнее см. в файле [LICENSE](LICENSE).

---

### 🙏 Благодарности

- **[MajorDoMo](https://github.com/sergejey/majordomo)** — открытая система автоматизации дома  
- **[xiaozhi](https://xiaozhi.me)** — платформа ИИ-агентов  
- **[MCP Protocol](https://modelcontextprotocol.io/)** — стандарт для взаимодействия ИИ и инструментов

> 💡 **Совет**: Звёздочка на GitHub помогает проекту расти! ⭐  
> 🐞 Нашли баг? Откройте [Issue](https://github.com/golnet1/mcp-majordomo-xiaozhi/issues)!
