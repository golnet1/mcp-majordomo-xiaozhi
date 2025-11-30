#!/usr/bin/env python3
"""
Универсальный MCP-сервер для MajorDoMo + xiaozhi
С поддержкой дублирующихся алиасов (например, "комната отдыха" в освещении и колонках).
Все действия логируются в единый файл /opt/mcp-bridge/logs/actions.log
"""
import sys
import os
import json
import logging
import re
import requests
from mcp.server.fastmcp import FastMCP

# === Настройка ===
log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper())
logging.basicConfig(stream=sys.stderr, level=log_level, format="%(levelname)s: %(message)s")
logger = logging.getLogger("mcp_majordomo")

MAJORDOMO_URL = os.getenv("MAJORDOMO_URL", "http://127.0.0.1")
ALIASES_FILE = "/opt/mcp-bridge/device_aliases.json"

# === Импорт единого логгера ===
sys.path.append("/opt/mcp-bridge")
try:
    from action_logger import log_action
except ImportError:
    logger.error("Не удалось импортировать action_logger. Логирование отключено.")
    def log_action(*args, **kwargs):
        pass  # Заглушка, если логгер недоступен

# === Загрузка алиасов (новая структура) ===
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

# === MajorDoMo API (с поддержкой params) ===
def call_majordomo(method: str, path: str, data=None, params=None):
    url = f"{MAJORDOMO_URL}/api/{path}"
    try:
        if method == "POST":
            if isinstance(data, dict):
                resp = requests.post(url, json=data, params=params, timeout=15)
            else:
                resp = requests.post(url, data=data, params=params, timeout=15)
        else:
            resp = requests.get(url, params=params, timeout=15)
        return resp
    except Exception as e:
        logger.error(f"Majordomo API error: {e}")
        return None

# === Нормализация запросов ===
def normalize_query(query: str) -> str:
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

# === Поиск устройства с учётом категории и типа ===
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

# === TTS (ищет только в категории "колонки") ===
def say_via_tts(text: str, room: str = "комната отдыха") -> bool:
    """Озвучивает текст через колонку в указанной комнате."""
    alias_name = normalize_query(room)
    device_spec = find_device_by_category_and_type(alias_name, preferred_categories=["колонки"])
    if not device_spec:
        logger.warning(f"Колонка не найдена для комнаты: {room}")
        return False

    resp = call_majordomo("GET", f"method/{device_spec['object']}.say", params={"text": text})
    return resp is not None and resp.status_code == 200

# === MCP-сервер ===
mcp = FastMCP("Majordomo Universal")

# === СТАРЫЕ МЕТОДЫ (с поддержкой дубликатов и логированием) ===
@mcp.tool()
def get_property(object: str, property: str) -> dict:
    """Технический метод: получить свойство по object.property"""
    path = f"data/{object}.{property}"
    resp = call_majordomo("GET", path)
    if resp and resp.status_code == 200:
        try:
            value = resp.json().get("data", resp.text.strip())
        except:
            value = resp.text.strip()
        return {"value": value}
    return {"error": f"Ошибка: {resp.status_code if resp else 'timeout'}"}

@mcp.tool()
def set_property(object: str, property: str, value: str) -> dict:
    """Технический метод: установить свойство"""
    path = f"data/{object}.{property}"
    payload = {"data": str(value)}
    resp = call_majordomo("POST", path, data=payload)
    if resp and resp.status_code == 200:
        return {"success": True}
    return {"error": f"MajorDoMo вернул статус {resp.status_code if resp else 'N/A'}"}

@mcp.tool()
def set_device(device_name: str, state: str) -> dict:
    """Человекочитаемое управление с нормализацией и поддержкой дубликатов. Использует тип 'relay'."""
    norm_name = normalize_query(device_name)
    device_spec = find_device_by_category_and_type(
        norm_name,
        preferred_categories=["свет", "устройства"],
        required_type="relay" # Только реле
    )
    if not device_spec:
        aliases = load_aliases()
        available = ", ".join(aliases.keys())
        log_action(
            source="mcp",
            user="xiaozhi",
            action="set_device",
            target=device_name,
            success=False,
            details={"error": "Устройство (реле) не найдено", "available": available}
        )
        return {"error": f"Устройство (реле) '{device_name}' не найдено. Доступные: {available}"}

    value = "1" if state.lower() in ("включи", "включить", "on", "1", "да") else "0"
    result = set_property(device_spec["object"], device_spec["property"], value)
    if "success" in result:
        log_action(
            source="mcp",
            user="xiaozhi",
            action="set_device",
            target=norm_name,
            success=True,
            details={"state": "включено" if value == "1" else "выключено"}
        )
    else:
        log_action(
            source="mcp",
            user="xiaozhi",
            action="set_device",
            target=norm_name,
            success=False,
            details={"error": result.get("error", "Unknown error")}
        )
    return result

@mcp.tool()
def get_device(device_name: str) -> dict:
    """Человекочитаемый статус с нормализацией и поддержкой дубликатов. Использует тип 'relay'."""
    norm_name = normalize_query(device_name)
    device_spec = find_device_by_category_and_type(
        norm_name,
        preferred_categories=["свет", "устройства"],
        required_type="relay" # Только реле
    )
    if not device_spec:
        log_action(
            source="mcp",
            user="xiaozhi",
            action="get_device",
            target=device_name,
            success=False,
            details={"error": "Устройство (реле) не найдено"}
        )
        return {"error": f"Устройство (реле) '{device_name}' не найдено."}

    result = get_property(device_spec["object"], device_spec["property"])
    if "error" in result:
        log_action(
            source="mcp",
            user="xiaozhi",
            action="get_device",
            target=norm_name,
            success=False,
            details={"error": result["error"]}
        )
        return result

    status = "включено" if result["value"] == "1" else "выключено"
    log_action(
        source="mcp",
        user="xiaozhi",
        action="get_device",
        target=norm_name,
        success=True,
        details={"status": status, "raw_value": result["value"]}
    )
    return {"device": device_name, "status": status, "raw_value": result["value"]}

@mcp.tool()
def list_devices() -> dict:
    """Список всех устройств"""
    aliases = load_aliases()
    return {"devices": list(aliases.keys())}

@mcp.tool()
def list_rooms() -> dict:
    """Список комнат из MajorDoMo"""
    resp = call_majordomo("GET", "rooms")
    if resp and resp.status_code == 200:
        try:
            return {"rooms": resp.json()}
        except:
            return {"error": "Invalid JSON response"}
    return {"error": f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"}

@mcp.tool()
def get_room(room_id: str) -> dict:
    """Детали комнаты по ID"""
    resp = call_majordomo("GET", f"rooms/{room_id}")
    if resp and resp.status_code == 200:
        try:
            return {"room": resp.json()}
        except:
            return {"error": "Invalid JSON response"}
    return {"error": f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"}

# === НОВЫЕ МЕТОДЫ (с TTS, поддержкой дубликатов, логированием и учётом типа) ===
@mcp.tool()
def control_device(device_query: str, action: str, tts_feedback: bool = True) -> dict:
    """
    Управление реле (тип 'relay') с TTS и поддержкой дублирующихся алиасов.
    Используй, когда пользователь говорит: 'включи свет в комнате отдыха', 'выключи улицу'.
    Не используй, если пользователь говорит 'через 1 минуту' или 'в 15:30'.
    """
    norm_query = normalize_query(device_query)
    logger.info(f"Запрос: '{device_query}' → нормализовано: '{norm_query}'")

    # Ищем устройство в категориях свет/устройств с типом relay
    device_spec = find_device_by_category_and_type(
        norm_query,
        preferred_categories=["свет", "устройства"],
        required_type="relay" # Только реле
    )
    if not device_spec:
        # Формируем список ТОЛЬКО релевантных алиасов (реле)
        aliases = load_aliases()
        relevant_aliases = []
        for alias_name, specs in aliases.items():
            for spec in specs:
                if spec["category"] in ["свет", "устройства"] and spec["type"] == "relay":
                    relevant_aliases.append(alias_name)
                    break
        available = ", ".join(sorted(set(relevant_aliases)))
        logger.info(f"Не найдено. Доступные реле: {available}")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="control_device",
            target=device_query,
            success=False,
            details={"error": "Устройство (реле) не найдено", "available": available}
        )
        return {"error": f"Не найдено (реле): '{device_query}'. Доступные: {available}"}

    # Гибкая обработка действия
    action_lower = action.lower()
    if any(word in action_lower for word in ["включи", "включить", "on", "1", "да", "зажги", "активируй", "включи свет"]):
        value = "1"
        state_word = "включён"
    elif any(word in action_lower for word in ["выключи", "выключить", "off", "0", "нет", "потуши", "деактивируй", "выключи свет"]):
        value = "0"
        state_word = "выключен"
    else:
        log_action(
            source="mcp",
            user="xiaozhi",
            action="control_device",
            target=device_query,
            success=False,
            details={"error": f"Неизвестное действие: '{action}'"}
        )
        return {"error": f"Неизвестное действие: '{action}'. Используйте 'включи' или 'выключи'."}

    # Выполнение команды
    resp = call_majordomo("POST", f"data/{device_spec['object']}.{device_spec['property']}", data={"data": value})
    if resp and resp.status_code == 200:
        if tts_feedback:
            say_via_tts(f"Свет в {norm_query} {state_word}")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="control_device",
            target=norm_query,
            success=True,
            details={"state": state_word, "device_query": device_query, "action": action}
        )
        return {"success": True, "target": norm_query, "state": state_word}
    else:
        error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
        log_action(
            source="mcp",
            user="xiaozhi",
            action="control_device",
            target=norm_query,
            success=False,
            details={"error": error_msg, "device_query": device_query}
        )
        return {"error": error_msg}

@mcp.tool()
def get_device_status(device_query: str, tts_feedback: bool = True) -> dict:
    """Статус реле (тип 'relay') с TTS и поддержкой дублирующихся алиасов."""
    norm_query = normalize_query(device_query)
    device_spec = find_device_by_category_and_type(
        norm_query,
        preferred_categories=["свет", "устройства"],
        required_type="relay" # Только реле
    )
    if not device_spec:
        log_action(
            source="mcp",
            user="xiaozhi",
            action="get_device_status",
            target=device_query,
            success=False,
            details={"error": "Устройство (реле) не найдено"}
        )
        return {"error": f"Не найдено (реле): '{device_query}'"}

    resp = call_majordomo("GET", f"data/{device_spec['object']}.{device_spec['property']}")
    if resp and resp.status_code == 200:
        try:
            value = resp.json().get("data", resp.text.strip())
        except:
            value = resp.text.strip()
        status = "включено" if value == "1" else "выключено"
        if tts_feedback:
            say_via_tts(f"Свет в {norm_query} {status}")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="get_device_status",
            target=norm_query,
            success=True,
            details={"status": status, "value": value, "device_query": device_query}
        )
        return {"device": norm_query, "status": status}
    error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
    log_action(
        source="mcp",
        user="xiaozhi",
        action="get_device_status",
        target=norm_query,
        success=False,
        details={"error": error_msg, "device_query": device_query}
    )
    return {"error": error_msg}

@mcp.tool()
def get_sensor_value(sensor_query: str, unit: str = "", tts_feedback: bool = True) -> dict:
    """
    Чтение значения сенсора (тип 'sensors') с TTS и поддержкой дубликаций.
    unit: строка для озвучивания, например, "градусов", "процентов", "Паскаль".
    """
    norm_query = normalize_query(sensor_query)
    logger.info(f"Запрос сенсора: '{sensor_query}' → нормализовано: '{norm_query}'")

    # --- ИЗМЕНЕНИЕ: Предположим, что unit="%" указывает на влажность ---
    # В реальности ИИ должен сам понимать контекст запроса ("влажность")
    # и вызывать соответствующий инструмент или передавать категорию.
    # Но если unit используется как подсказка:
    preferred_categories = None
    if unit == "процентов" or "влажность" in sensor_query: # Простая эвристика
         preferred_categories = ["сенсоры_влажность","сенсоры_влажности"] 
    elif unit in ["градусов", "°C", "°F"]:
         preferred_categories = ["сенсоры_температура","сенсоры_температуры"] 
    elif unit in ["давление", "бар", "паскаль","па","атм","мм рт.ст."]:
         preferred_categories = ["сенсоры_давление","сенсоры_давления"] 
    elif unit in ["ppm", "co2"]:
         preferred_categories = ["сенсоры_газ","сенсоры_газа","сенсоры_углекислый газ"] 

    # Ищем устройство с типом sensors и предпочтительно в нужной категории
    device_spec = find_device_by_category_and_type(
        norm_query,
        preferred_categories=preferred_categories, # Используем определённые категории
        required_type="sensors"
    )
    # ---

    if not device_spec:
        # Формируем список ТОЛЬКО сенсоров
        aliases = load_aliases()
        relevant_aliases = []
        for alias_name, specs in aliases.items():
            for spec in specs:
                if spec["type"] == "sensors":
                    relevant_aliases.append(alias_name)
                    break
        available = ", ".join(sorted(set(relevant_aliases)))
        logger.info(f"Сенсор не найден. Доступные: {available}")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="get_sensor_value",
            target=sensor_query,
            success=False,
            details={"error": "Сенсор не найден", "available": available}
        )
        return {"error": f"Сенсор не найден: '{sensor_query}'. Доступные: {available}"}

    resp = call_majordomo("GET", f"data/{device_spec['object']}.{device_spec['property']}")
    if resp and resp.status_code == 200:
        try:
            value = resp.json().get("data", resp.text.strip())
        except:
            value = resp.text.strip()

        if tts_feedback:
            say_via_tts(f"В {norm_query} {value} {unit}")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="get_sensor_value",
            target=norm_query,
            success=True,
            details={"value": value, "unit": unit, "sensor_query": sensor_query}
        )
        return {"sensor": norm_query, "value": value, "unit": unit}
    else:
        error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
        log_action(
            source="mcp",
            user="xiaozhi",
            action="get_sensor_value",
            target=norm_query,
            success=False,
            details={"error": error_msg, "sensor_query": sensor_query}
        )
        return {"error": error_msg}

@mcp.tool()
def set_device_parameter(device_query: str, parameter: str, value: str, tts_feedback: bool = True) -> dict:
    """
    Установка параметра устройства (тип 'device') с TTS и поддержкой дубликаций.
    Используется, например, для установки температуры.
    """
    norm_query = normalize_query(device_query)
    logger.info(f"Запрос установки параметра: '{device_query}' → нормализовано: '{norm_query}', параметр: '{parameter}', значение: '{value}'")

    # Ищем устройство с типом device
    device_spec = find_device_by_category_and_type(
        norm_query,
        required_type="device" # Только устройства с параметрами
    )
    if not device_spec:
        # Формируем список ТОЛЬКО устройств с параметрами
        aliases = load_aliases()
        relevant_aliases = []
        for alias_name, specs in aliases.items():
            for spec in specs:
                if spec["type"] == "device":
                    relevant_aliases.append(alias_name)
                    break
        available = ", ".join(sorted(set(relevant_aliases)))
        logger.info(f"Устройство (device) не найдено. Доступные: {available}")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="set_device_parameter",
            target=device_query,
            success=False,
            details={"error": "Устройство (device) не найдено", "available": available}
        )
        return {"error": f"Устройство (device) не найдено: '{device_query}'. Доступные: {available}"}

    # Выполнение команды
    resp = call_majordomo("POST", f"data/{device_spec['object']}.{device_spec['property']}", data={"data": str(value)})
    if resp and resp.status_code == 200:
        if tts_feedback:
            say_via_tts(f"Параметр {parameter} в {norm_query} установлен на {value}")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="set_device_parameter",
            target=norm_query,
            success=True,
            details={"parameter": parameter, "value": value, "device_query": device_query}
        )
        return {"success": True, "target": norm_query, "parameter": parameter, "value": value}
    else:
        error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
        log_action(
            source="mcp",
            user="xiaozhi",
            action="set_device_parameter",
            target=norm_query,
            success=False,
            details={"error": error_msg, "device_query": device_query}
        )
        return {"error": error_msg}


@mcp.tool()
def run_script(script_name: str, tts_feedback: bool = True) -> dict:
    """Запуск сценария"""
    resp = call_majordomo("GET", f"script/{script_name}")
    if resp and resp.status_code == 200:
        if tts_feedback:
            say_via_tts(f"Сценарий {script_name} запущен")
        log_action(
            source="mcp",
            user="xiaozhi",
            action="run_script",
            target=script_name,
            success=True
        )
        return {"success": True, "script": script_name}
    else:
        error_msg = f"Сценарий '{script_name}' не запущен"
        log_action(
            source="mcp",
            user="xiaozhi",
            action="run_script",
            target=script_name,
            success=False,
            details={"error": error_msg}
        )
        return {"error": error_msg}

# === ГОЛОСОВОЕ УПРАВЛЕНИЕ ПЛАНИРОВЩИКОМ ===
import subprocess
from datetime import datetime, timedelta

SCHEDULE_FILE = "/opt/mcp-bridge/schedule.json"

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

@mcp.tool()
def add_scheduler_task(time_str: str, device: str, action: str, repeat_days: list = None) -> dict:
    """
    Добавляет задание в планировщик.
    time_str: "HH:MM" (например, "17:15")
    device: имя устройства (например, "улица")
    action: "включи" или "выключи"
    repeat_days: ["mon", "tue", ...] или None (одноразовое)
    """
    schedule = load_schedule()
    # Генерируем ID на основе времени и устройства
    task_id = f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{device.replace(' ', '_')}"

    # === НОВОЕ: Если repeat_days не указан, считаем одноразовым ===
    if repeat_days is None:
        repeat_days = ["once"]
    # ===

    new_task = {
        "id": task_id,
        "enabled": True,
        "description": f"Голосовое задание: {action} {device}",
        "time": time_str,
        "days": repeat_days,  # Теперь может быть и постоянным
        "action": {
            "type": "device",
            "device": device,
            "state": action
        }
    }
    schedule.append(new_task)
    save_schedule(schedule)
    reload_scheduler()

    # Логируем
    log_action(
        source="mcp",
        user="xiaozhi",
        action="add_scheduler_task",
        target=task_id,
        success=True,
        details={"time": time_str, "device": device, "action": action, "repeat_days": repeat_days}
    )
    return {"success": True, "message": f"Задание добавлено: {action} {device} в {time_str} {'каждый день' if repeat_days == ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] else 'по дням: ' + ', '.join(repeat_days)}"}

@mcp.tool()
def delete_scheduler_task(task_id: str) -> dict:
    """
    Удаляет задание из планировщика по ID.
    """
    schedule = load_schedule()
    original_count = len(schedule)
    schedule = [task for task in schedule if task["id"] != task_id]
    if len(schedule) == original_count:
        return {"success": False, "message": f"Задание с ID '{task_id}' не найдено"}

    save_schedule(schedule)
    reload_scheduler()

    log_action(
        source="mcp",
        user="xiaozhi",
        action="delete_scheduler_task",
        target=task_id,
        success=True
    )
    return {"success": True, "message": f"Задание '{task_id}' удалено"}

@mcp.tool()
def delete_all_scheduler_tasks() -> dict:
    """
    Удаляет ВСЕ задания из планировщика.
    """
    schedule = load_schedule()
    original_count = len(schedule)
    if original_count == 0:
        return {"success": True, "message": "Нет заданий для удаления"}

    # Оставляем только отключённые задания (если такие есть)
    schedule = [task for task in schedule if not task["enabled"]]
    save_schedule(schedule)
    reload_scheduler()

    log_action(
        source="mcp",
        user="xiaozhi",
        action="delete_all_scheduler_tasks",
        target="all",
        success=True,
        details={"deleted_count": original_count}
    )
    return {"success": True, "message": f"Все задания ({original_count}) удалены"}

@mcp.tool()
def list_scheduler_tasks() -> dict:
    """
    Возвращает список текущих заданий.
    """
    schedule = load_schedule()
    active_tasks = [task for task in schedule if task["enabled"]]
    if not active_tasks:
        message = "Нет активных заданий."
    else:
        task_list = []
        for task in active_tasks:
            time = task.get("time", "неизвестно")
            device = task["action"].get("device", "неизвестно")
            action = task["action"].get("state", "неизвестно")
            desc = task.get("description", f"{action} {device}")
            task_list.append(f"{time} — {desc}")
        message = "Активные задания: " + "; ".join(task_list)

    # Логируем
    log_action(
        source="mcp",
        user="xiaozhi",
        action="list_scheduler_tasks",
        target="all",
        success=True,
        details={"count": len(active_tasks)}
    )
    return {"tasks": active_tasks, "message": message}

@mcp.tool()
def add_temporary_scheduler_task(minutes_from_now: int, device: str, action: str) -> dict:
    """
    Добавляет задание, которое выполнится через N минут.
    minutes_from_now: int
    device: имя устройства
    action: "включи" или "выключи"
    """
    future_time = datetime.now() + timedelta(minutes=minutes_from_now)
    time_str = future_time.strftime("%H:%M")
    schedule = load_schedule()
    task_id = f"voice_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{device.replace(' ', '_')}"

    new_task = {
        "id": task_id,
        "enabled": True,
        "description": f"Временное задание: {action} {device} через {minutes_from_now} мин",
        "time": time_str,
        "days": ["once"],  # Одноразовое
        "action": {
            "type": "device",
            "device": device,
            "state": action
        }
    }
    schedule.append(new_task)
    save_schedule(schedule)
    reload_scheduler()

    log_action(
        source="mcp",
        user="xiaozhi",
        action="add_temporary_scheduler_task",
        target=task_id,
        success=True,
        details={"time": time_str, "device": device, "action": action, "minutes_delay": minutes_from_now}
    )
    return {"success": True, "message": f"Задание добавлено: {action} {device} через {minutes_from_now} минут"}

# === Запуск ===
if __name__ == "__main__":
    mcp.run(transport="stdio")