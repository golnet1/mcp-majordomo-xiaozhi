#!/usr/bin/env python3
"""
Фоновый планировщик для MajorDoMo.
Поддержка дублирующихся алиасов (например, "комната отдыха" в освещении и колонках).
Проверяет schedule.json каждую минуту и выполняет задачи.
"""

import json
import time
import threading
import logging
import os
import sys
import re
from datetime import datetime
import requests

# === Настройки ===
SCHEDULE_FILE = "/opt/mcp-bridge/schedule.json"
MAJORDOMO_URL = "http://192.168.88.2"
ALIASES_FILE = "/opt/mcp-bridge/device_aliases.json"
LOG_FILE = "/opt/mcp-bridge/logs/actions.log"

# Настройка логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Scheduler")

# === Вспомогательные функции ===

def load_aliases():
    """
    Загружает алиасы и раскрывает составные ключи (через запятую).
    Поддерживает дублирующиеся имена в разных категориях.
    Возвращает: {"улица": [spec1], "комната отдыха": [spec_освещение, spec_колонки]}
    """
    if not os.path.exists(ALIASES_FILE):
        logger.warning(f"Файл алиасов не найден: {ALIASES_FILE}")
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

def call_majordomo(method, path, data=None):
    """Выполняет запрос к MajorDoMo API."""
    url = f"{MAJORDOMO_URL}/api/{path}"
    try:
        if method == "POST":
            if isinstance(data, dict):
                resp = requests.post(url, json=data, timeout=10)
            else:
                resp = requests.post(url, data=data, timeout=10)
        else:
            resp = requests.get(url, timeout=10)
        return resp
    except Exception as e:
        logger.error(f"MajorDoMo API error: {e}")
        return None

def log_action(action, target, success=True, details=None):
    """Логирует действия в единый файл."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "scheduler",
            "user": "system",
            "action": action,
            "target": target,
            "success": success,
            "details": details or {}
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Ошибка записи лога: {e}")

def send_telegram_error(message):
    """Отправляет уведомление об ошибке в Telegram."""
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🚨 Ошибка в планировщике:\n{message}",
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Не удалось отправить в Telegram: {e}")

def execute_task(task):
    """Выполняет задачу из расписания."""
    try:
        action = task["action"]
        task_id = task.get("id", "unknown")
        description = task.get("description", task_id)
        
        if action["type"] == "device":
            device_name = action["device"].lower()
            norm_name = normalize_query(device_name)
            
            # Ищем в категориях освещения/устройств
            dev = find_device_by_category(norm_name, ["освещение", "устройства"])
            
            if not dev:
                error_msg = f"Устройство не найдено: {device_name}"
                logger.error(error_msg)
                log_action("device", device_name, success=False, details={"task_id": task_id, "error": error_msg})
                send_telegram_error(f"<b>Задача:</b> {description}\n{error_msg}")
                return
            
            value = "1" if action["state"].lower() in ("включи", "on", "1") else "0"
            resp = call_majordomo("POST", f"data/{dev['object']}.{dev['property']}", {"data": value})
            success = resp is not None and resp.status_code == 200
            
            if success:
                logger.info(f"✅ Выполнено: {description}")
                log_action("device", norm_name, success=True, details={"task_id": task_id, "state": "включено" if value=="1" else "выключено"})
            else:
                error_msg = f"MajorDoMo вернул статус {resp.status_code if resp else 'N/A'}"
                logger.error(f"❌ Ошибка: {description} — {error_msg}")
                log_action("device", norm_name, success=False, details={"task_id": task_id, "error": error_msg})
                send_telegram_error(f"<b>Задача:</b> {description}\n{error_msg}")

        elif action["type"] == "script":
            script_name = action["script"]
            resp = call_majordomo("GET", f"script/{script_name}")
            success = resp is not None and resp.status_code == 200
            
            if success:
                logger.info(f"✅ Сценарий запущен: {script_name}")
                log_action("script", script_name, success=True, details={"task_id": task_id})
            else:
                error_msg = f"Сценарий не запущен (статус {resp.status_code if resp else 'N/A'})"
                logger.error(f"❌ Ошибка: {error_msg}")
                log_action("script", script_name, success=False, details={"task_id": task_id, "error": error_msg})
                send_telegram_error(f"<b>Сценарий:</b> {script_name}\n{error_msg}")

    except Exception as e:
        error_msg = f"Исключение: {str(e)}"
        logger.exception(f"Ошибка выполнения задачи {task_id}")
        log_action("execute_task", task_id, success=False, details={"error": str(e)})
        send_telegram_error(f"<b>Задача:</b> {task.get('description', task_id)}\n{error_msg}")

def scheduler_loop():
    """Основной цикл планировщика."""
    last_check = None
    while True:
        now = datetime.now()
        current_min = now.strftime("%H:%M")
        current_day = now.strftime("%a").lower()[:3]  # "mon", "tue", ...

        # Проверяем раз в минуту
        if current_min == last_check:
            time.sleep(30)
            continue

        try:
            if not os.path.exists(SCHEDULE_FILE):
                logger.warning(f"Файл расписания не найден: {SCHEDULE_FILE}")
                time.sleep(60)
                continue

            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                tasks = json.load(f)

            for task in tasks:
                if not task.get("enabled", True):
                    continue
                if task.get("time") == current_min and current_day in task.get("days", []):
                    logger.info(f"⏰ Запуск задачи: {task.get('description', task['id'])}")
                    threading.Thread(target=execute_task, args=(task,)).start()
        except Exception as e:
            logger.exception(f"Ошибка в планировщике: {e}")
            log_action("scheduler_error", "schedule.json", success=False, details={"error": str(e)})

        last_check = current_min
        time.sleep(30)

if __name__ == "__main__":
    logger.info("Запуск планировщика...")
    scheduler_loop()