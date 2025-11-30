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
import subprocess  # ← Новый импорт

# === Настройки ===
SCHEDULE_FILE = "/opt/mcp-bridge/schedule.json"
MAJORDOMO_URL = os.getenv("MAJORDOMO_URL", "http://127.0.0.1")  # ← Берётся из .env
ALIASES_FILE = "/opt/mcp-bridge/device_aliases.json"
LOG_FILE = "/opt/mcp-bridge/logs/actions.log"

# Настройка логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Scheduler")

# === Вспомогательные функции ===

def load_aliases():
    """
    Загружает алиасы из нового формата:
    {
      "свет": {
        "type": "relay",
        "devices": {
          "улица": { "object": "Relay01", "property": "status" },
          ...
        }
      },
      ...
    }
    Поддерживает дублирующиеся имена в разных категориях.
    Возвращает: {"улица": [spec1], "комната отдыха": [spec_свет, spec_температура]}
    """
    if not os.path.exists(ALIASES_FILE):
        logger.warning(f"Файл алиасов не найден: {ALIASES_FILE}")
        return {}

    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        aliases = {}
        for category, details in raw.items():
            if "devices" not in details:
                continue
            for key, spec in details["devices"].items():
                names = [name.strip().lower() for name in key.split(",")]
                for name in names:
                    if name:
                        if name not in aliases:
                            aliases[name] = []
                        aliases[name].append({
                            "object": spec["object"],
                            "property": spec["property"],
                            "category": category,
                            "type": details.get("type", "unknown")
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
        r'^(температура|влажность|давление)\s+(в|на)\s+',
        r'^(свет|освещение|статус|температура|влажность|давление)\s*',
        r'^(на|в)\s+'
    ]
    for pat in patterns:
        query = re.sub(pat, '', query)
    if query.endswith('е'): query = query[:-1]
    if query.endswith('у'): query = query[:-1]
    if query.endswith('ом'): query = query[:-2]
    return query.strip()

def find_device_by_category_and_type(alias_name: str, preferred_categories: list = None, required_type: str = None):
    """
    Находит устройство по имени, предпочтительным категориям и/или типу.
    Возвращает первую подходящую спецификацию.
    """
    aliases = load_aliases()
    if alias_name not in aliases:
        return None

    specs = aliases[alias_name]
    # Сначала ищем по предпочтительным категориям
    if preferred_categories:
        for spec in specs:
            if spec["category"] in preferred_categories:
                # Если требуется определённый тип, проверяем его
                if required_type and spec["type"] != required_type:
                    continue
                return spec
    # Если не нашли по категориям, ищем по требуемому типу
    if required_type:
        for spec in specs:
            if spec["type"] == required_type:
                return spec
    # Если не нашли ни по категории, ни по типу, возвращаем первую
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
        import requests as req
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🚨 Ошибка в планировщике:\n{message}",
            "parse_mode": "HTML"
        }
        req.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Не удалось отправить в Telegram: {e}")

def execute_task(task):
    """Выполняет задачу из расписания."""
    task_id = task.get("id", "unknown")
    description = task.get("description", task_id)
    is_once = "once" in task.get("days", [])

    try:
        action = task["action"]
        
        if action["type"] == "device":
            device_name = action["device"].lower()
            norm_name = normalize_query(device_name)
            
            # Ищем в категориях свет/устройств с типом relay (для задач включения/выключения)
            dev = find_device_by_category_and_type(
                norm_name,
                preferred_categories=["свет", "устройства"], # Обновлено: используем "свет"
                required_type="relay" # Обновлено: ищем только реле
            )
            
            if not dev:
                error_msg = f"Устройство (реле) не найдено: {device_name}"
                logger.error(error_msg)
                log_action("device", device_name, success=False, details={"task_id": task_id, "error": error_msg})
                send_telegram_error(f"<b>Задача:</b> {description}\n{error_msg}")
                # === НОВОЕ: Удаляем одноразовое задание даже при ошибке ===
                if is_once:
                    schedule = load_schedule()
                    updated_schedule = [t for t in schedule if t["id"] != task_id]
                    save_schedule(updated_schedule)
                    reload_scheduler()
                    logger.info(f"[INFO] Одноразовое задание '{task_id}' удалено после ошибки.")
                # ===
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
                # === НОВОЕ: Удаляем одноразовое задание даже при ошибке ===
                if is_once:
                    schedule = load_schedule()
                    updated_schedule = [t for t in schedule if t["id"] != task_id]
                    save_schedule(updated_schedule)
                    reload_scheduler()
                    logger.info(f"[INFO] Одноразовое задание '{task_id}' удалено после ошибки.")
                # ===

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
                # === НОВОЕ: Удаляем одноразовое задание даже при ошибке ===
                if is_once:
                    schedule = load_schedule()
                    updated_schedule = [t for t in schedule if t["id"] != task_id]
                    save_schedule(updated_schedule)
                    reload_scheduler()
                    logger.info(f"[INFO] Одноразовое задание '{task_id}' удалено после ошибки.")
                # ===

        # === НОВОЕ: Удаление одноразового задания после успешного выполнения ===
        if is_once and (action["type"] == "device" and success or action["type"] == "script" and success):
            schedule = load_schedule()
            updated_schedule = [t for t in schedule if t["id"] != task_id]
            save_schedule(updated_schedule)
            reload_scheduler()
            logger.info(f"[INFO] Одноразовое задание '{task_id}' удалено после выполнения.")
        # ===

    except Exception as e:
        error_msg = f"Исключение: {str(e)}"
        logger.exception(f"Ошибка выполнения задачи {task_id}")
        log_action("execute_task", task_id, success=False, details={"error": str(e)})
        send_telegram_error(f"<b>Задача:</b> {task.get('description', task_id)}\n{error_msg}")
        # === НОВОЕ: Удаляем одноразовое задание даже при исключении ===
        if is_once:
            schedule = load_schedule()
            updated_schedule = [t for t in schedule if t["id"] != task_id]
            save_schedule(updated_schedule)
            reload_scheduler()
            logger.info(f"[INFO] Одноразовое задание '{task_id}' удалено после исключения.")
        # ===

def load_schedule():
    if not os.path.exists(SCHEDULE_FILE):
        return []
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_schedule(schedule):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

def reload_scheduler():
    """Перезапускает сервис планировщика."""
    try:
        subprocess.run(["sudo", "systemctl", "restart", "mcp-scheduler"], check=True)
    except subprocess.CalledProcessError:
        pass  # Игнорируем ошибки, если сервис не нуждается в перезапуске

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

            tasks = load_schedule()

            for task in tasks:
                if not task.get("enabled", True):
                    continue
                # === ИСПРАВЛЕНО: проверка на "once" ===
                if task.get("time") == current_min and (current_day in task.get("days", []) or "once" in task.get("days", [])):
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