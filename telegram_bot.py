#!/usr/bin/env python3
"""
Telegram-бот для управления MajorDoMo через MCP-логику.
Поддержка дублирующихся алиасов (например, "комната отдыха" в освещении и колонках).
Команды:
  /auth <пароль>      — авторизация
  /light <место> <включи/выключи>
  /status <место>
  /script <имя>
"""

import os
import json
import logging
import sys
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.append("/opt/mcp-bridge")
from action_logger import log_action

# Настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Получи у @BotFather
AUTHORIZED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Твой chat_id
AUTH_PASSWORD = os.getenv("TELEGRAM_AUTH_PASSWORD", "secret123")
MAJORDOMO_URL = "http://192.168.88.2"
ALIASES_FILE = "/opt/mcp-bridge/device_aliases.json"

# Хранилище сессий
AUTHORIZED_USERS = set()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_aliases():
    """
    Загружает алиасы и раскрывает составные ключи (через запятую).
    Поддерживает дублирующиеся имена в разных категориях.
    Возвращает: {"улица": [spec1], "комната отдыха": [spec_освещение, spec_колонки]}
    """
    if not os.path.exists(ALIASES_FILE):
        return {}

    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        aliases = {}
        for category, devices in raw.items():
            for key, spec in devices.items():
                names = [name.strip().lower() for name in key.split(",")]
                for name in names:
                    if name:
                        if name not in aliases:
                            aliases[name] = []
                        aliases[name].append({
                            "object": spec["object"],
                            "property": spec["property"],
                            "category": category
                        })
        return aliases
    except Exception as e:
        logger.error(f"Ошибка загрузки алиасов: {e}")
        return {}

def normalize_query(query: str) -> str:
    """Нормализует запрос (как в MCP-сервере)."""
    query = query.lower().strip()
    patterns = [
        r'^(свет|освещение|статус)\s+(на|в)\s+',
        r'^(температура|влажность)\s+(в|на)\s+',
        r'^(свет|освещение|статус|температура|влажность)\s*',
        r'^(на|в)\s+'
    ]
    for pat in patterns:
        query = re.sub(pat, '', query)
    if query.endswith('е'): query = query[:-1]
    if query.endswith('у'): query = query[:-1]
    if query.endswith('ом'): query = query[:-2]
    return query.strip()

def find_device_by_category(alias_name: str, preferred_categories: list = None):
    """Находит устройство по имени и предпочтительным категориям."""
    aliases = load_aliases()
    if alias_name not in aliases:
        return None
    
    specs = aliases[alias_name]
    
    if preferred_categories:
        for spec in specs:
            if spec["category"] in preferred_categories:
                return spec
    
    return specs[0] if specs else None

def call_majordomo(method, path, data=None, params=None):
    import requests
    url = f"{MAJORDOMO_URL}/api/{path}"
    try:
        if method == "POST":
            resp = requests.post(url, json=data, params=params, timeout=10)
        else:
            resp = requests.get(url, params=params, timeout=10)
        return resp
    except Exception as e:
        logger.error(f"MajorDoMo error: {e}")
        return None

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /auth <пароль>")
        return
    password = context.args[0]
    if password == AUTH_PASSWORD:
        AUTHORIZED_USERS.add(update.effective_chat.id)
        await update.message.reply_text("✅ Авторизация успешна!")
    else:
        await update.message.reply_text("❌ Неверный пароль")

async def light(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in AUTHORIZED_USERS:
        await update.message.reply_text("🔒 Сначала авторизуйтесь: /auth <пароль>")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /light <место> <включи/выключи>")
        return
    
    location = " ".join(context.args[:-1]).lower()
    action = context.args[-1].lower()
    norm = normalize_query(location)
    
    # Ищем в категории освещения
    dev = find_device_by_category(norm, ["освещение"])
    
    if not dev:
        aliases = load_aliases()
        available = ", ".join(
            k for k, specs in aliases.items() 
            for spec in specs 
            if spec["category"] == "освещение"
        )
        await update.message.reply_text(f"Не найдено. Доступные: {available}")
        return
    
    value = "1" if action in ("включи", "on") else "0"
    resp = call_majordomo("POST", f"data/{dev['object']}.{dev['property']}", {"data": value})
    if resp and resp.status_code == 200:
        state = "включён" if value == "1" else "выключен"
        await update.message.reply_text(f"✅ Свет в {norm} {state}")
        log_action(
            source="telegram",
            user=str(update.effective_user.id),
            action="control_device",
            target=norm,
            success=True,
            details={"state": state}
        )
    else:
        await update.message.reply_text("❌ Ошибка MajorDoMo")
        log_action(
            source="telegram",
            user=str(update.effective_user.id),
            action="control_device",
            target=norm,
            success=False,
            details={"error": "MajorDoMo error"}
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in AUTHORIZED_USERS:
        await update.message.reply_text("🔒 Сначала авторизуйтесь: /auth <пароль>")
        return
    if not context.args:
        await update.message.reply_text("Использование: /status <место>")
        return
    
    location = " ".join(context.args).lower()
    norm = normalize_query(location)
    
    # Ищем в категориях освещения/устройств/климата
    dev = find_device_by_category(norm, ["освещение", "устройства", "климат"])
    
    if not dev:
        await update.message.reply_text("Устройство не найдено")
        return
    
    resp = call_majordomo("GET", f"data/{dev['object']}.{dev['property']}")
    if resp and resp.status_code == 200:
        try:
            value = resp.json().get("data", resp.text.strip())
        except:
            value = resp.text.strip()
        
        if dev["category"] == "климат":
            msg = f"🌡 {norm}: {value}°C" if "temp" in dev["property"].lower() else f"💧 {norm}: {value}%"
        else:
            status = "включено" if value == "1" else "выключено"
            msg = f"💡 {norm}: {status}"
        
        await update.message.reply_text(msg)
        log_action(
            source="telegram",
            user=str(update.effective_user.id),
            action="get_status",
            target=norm,
            success=True,
            details={"value": value}
        )
    else:
        await update.message.reply_text("❌ Ошибка получения статуса")
        log_action(
            source="telegram",
            user=str(update.effective_user.id),
            action="get_status",
            target=norm,
            success=False,
            details={"error": "MajorDoMo error"}
        )

async def script(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in AUTHORIZED_USERS:
        await update.message.reply_text("🔒 Сначала авторизуйтесь: /auth <пароль>")
        return
    if not context.args:
        await update.message.reply_text("Использование: /script <имя_сценария>")
        return
    script_name = context.args[0]
    resp = call_majordomo("GET", f"script/{script_name}")
    if resp and resp.status_code == 200:
        await update.message.reply_text(f"✅ Сценарий {script_name} запущен")
        log_action(
            source="telegram",
            user=str(update.effective_user.id),
            action="run_script",
            target=script_name,
            success=True
        )
    else:
        await update.message.reply_text("❌ Сценарий не запущен")
        log_action(
            source="telegram",
            user=str(update.effective_user.id),
            action="run_script",
            target=script_name,
            success=False,
            details={"error": "MajorDoMo error"}
        )

def main():
    if not TELEGRAM_TOKEN:
        logger.error("Задайте TELEGRAM_BOT_TOKEN")
        return
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("light", light))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("script", script))
    
    logger.info("Telegram-бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()