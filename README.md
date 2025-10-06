# 🏠 MCP Bridge for MajorDoMo — Умный дом с ИИ

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Raspberry%20Pi-lightgrey.svg)](https://www.raspberrypi.org/)

> **MCP Bridge** — это полноценная система управления умным домом на базе **MajorDoMo**, интегрированная с **ИИ-агентом [xiaozhi](https://xiaozhi.me)** через протокол **[MCP (Model Context Protocol)](https://github.com/modelcontextprotocol)**.  
> Поддерживает управление через **голос**, **Telegram**, **веб-интерфейс**, **расписание** и **сценарии**.

---

## 🌐 English | [Русский](#русский)

## 📌 Overview

This project provides a complete bridge between **[MajorDoMo](https://github.com/sergejey/majordomo)** (open-source home automation) and **AI agents** using the **MCP protocol**. It includes:

- ✅ **MCP Server** — connects AI to MajorDoMo
- ✅ **Web Panel** — edit device aliases, view logs, manage settings
- ✅ **Telegram Bot** — control devices via Telegram
- ✅ **Scheduler** — automate tasks by time
- ✅ **Auto-updater** — checks GitHub for new versions
- ✅ **Unified Logging** — all actions in one place

Works on **Raspberry Pi**, **Linux servers**.

---

## 🚀 Quick Start

### 1. Prerequisites
- Linux server or Raspberry Pi
- MajorDoMo installed and accessible at `http://YOUR_MAJORDOMO_IP`
- Python 3.8+

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/golnet1/mcp-majordomo-xiaozhi.git
cd mcp-majordomo-xiaozhi

# Run the installer (interactive)
chmod +x install_mcp_majordomo.sh
./install_mcp_majordomo.sh
```
Follow the prompts to configure:

MajorDoMo URL
Web panel credentials
Telegram bot (optional)
MCP endpoint (for xiaozhi)
3. Access Web Panel
Open in browser:
👉 http://YOUR_SERVER_IP:5000
Login with credentials you provided during installation.

🧩 Components
MCP Server
Connects AI agents to MajorDoMo
—
Web Panel
Manage devices, aliases, logs
5000
Telegram Bot
Control via Telegram commands
—
Scheduler
Time-based automation
—
Log Viewer
Real-time action monitoring
—
📝 Usage
Web Panel
Edit Aliases: Add devices like "улица" → Relay01.status
View Logs: See all actions with filtering and auto-refresh
Update System: One-click updates from GitHub
Telegram Commands
text


1
2
3
4
/auth <password>       — authorize
/light улица включи    — turn on street light
/status улица          — check status
/script GoodMorning    — run scenario
Voice Commands (via xiaozhi)
«Включи свет в комнате отдыха»
«Выключи всё»
«Какая температура в парной?» 

🔧 Configuration
All settings are stored in /opt/mcp-bridge/.env:

ini


1
2
3
4
5
6
7
MAJORDOMO_URL=http://192.168.88.2
WEB_PANEL_USER=admin
WEB_PANEL_PASS=secure_password
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
TELEGRAM_AUTH_PASSWORD=bot_secret
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=...
Edit this file and restart services:

```bash
sudo systemctl restart mcp-*
```
🔄 Auto-Updates
The system checks for updates every hour and shows a notification in the web panel when a new version is available.


🙏 Acknowledgements
MajorDoMo — open-source home automation
xiaozhi — AI agent platform
MCP Protocol — standard for AI-tool communication




# 🏠 MCP Bridge для MajorDoMo — Умный дом с ИИ

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Raspberry%20Pi-lightgrey.svg)](https://www.raspberrypi.org/)

> **MCP Bridge** — это полноценная система управления умным домом на базе **[MajorDoMo](https://github.com/sergejey/majordomo)**, интегрированная с **ИИ-агентом [xiaozhi](https://xiaozhi.me)** через протокол **[MCP (Model Context Protocol)](https://github.com/modelcontextprotocol)**.  
> Поддерживает управление через **голос**, **Telegram**, **веб-интерфейс**, **расписание** и **сценарии**.

---

## 📌 Обзор

Этот проект обеспечивает полный мост между **[MajorDoMo](https://mjdm.ru/)** (открытой системой автоматизации дома) **ИИ-агентами** с использованием протокола **MCP**. Включает:

- ✅ **MCP-сервер** — подключает ИИ к MajorDoMo
- ✅ **Веб-панель** — редактирование алиасов, просмотр логов, настройка
- ✅ **Telegram-бот** — управление через команды Telegram
- ✅ **Планировщик** — автоматизация по расписанию
- ✅ **Автообновление** — проверка обновлений на GitHub
- ✅ **Единый логгер** — все действия в одном месте

Работает на **Raspberry Pi**, **Linux-серверах**.

---

🚀 Быстрый старт
### 1. Требования
- Сервер Linux или Raspberry Pi
- Установленный MajorDoMo по адресу http://ВАШ_IP_MAJORDOMO
- Python 3.8+
### 2. Установка
```bash
# Клонировать репозиторий
git clone https://github.com/golnet1/mcp-majordomo-xiaozhi.git
cd mcp-majordomo-xiaozhi

# Запустить установщик (интерактивный)
chmod +x install_mcp_majordomo.sh
./install_mcp_majordomo.sh
Следуйте инструкциям для настройки:
```

URL MajorDoMo
Учётные данные веб-панели
Telegram-бот (опционально)
MCP-эндпоинт (для xiaozhi)
3. Доступ к веб-панели
Откройте в браузере:
👉 http://IP_ВАШЕГО_СЕРВЕРА:5000
Войдите с данными, указанными при установке.

🧩 Компоненты
MCP-сервер
Подключает ИИ к MajorDoMo
—
Веб-панель
Управление устройствами, алиасами, логами
5000
Telegram-бот
Управление через команды Telegram
—
Планировщик
Автоматизация по времени
—
Просмотр логов
Мониторинг действий в реальном времени
—
📝 Использование
Веб-панель
Редактирование алиасов: Добавьте устройства вроде "улица" → Relay01.status
Просмотр логов: Все действия с фильтрацией и автообновлением
Обновление системы: Обновление в один клик из GitHub
Команды Telegram
text


1
2
3
4
/auth <пароль>         — авторизация
/light улица включи    — включить свет на улице
/status улица          — проверить статус
/script Доброеутро     — запустить сценарий
Голосовые команды (через xiaozhi)
«Включи свет в комнате отдыха»
«Выключи всё»
«Какая температура в парной?» 

🔧 Настройка
Все параметры хранятся в /opt/mcp-bridge/.env:

ini


1
2
3
4
5
6
7
MAJORDOMO_URL=http://192.168.88.2
WEB_PANEL_USER=admin
WEB_PANEL_PASS=надёжный_пароль
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
TELEGRAM_AUTH_PASSWORD=секретный_пароль
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=...
Отредактируйте этот файл и перезапустите сервисы:

```bash
sudo systemctl restart mcp-*
```
🔄 Автообновление
Система проверяет обновления каждый час и показывает уведомление в веб-панели, когда доступна новая версия.


🙏 Благодарности
MajorDoMo — открытая система автоматизации дома
xiaozhi — платформа ИИ-агентов
MCP Protocol — стандарт для взаимодействия ИИ и инструментов
