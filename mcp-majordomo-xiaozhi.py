#!/usr/bin/env python3
"""Универсальный MCP-сервер для MajorDoMo + xiaozhi
С поддержкой дублирующихся алиасов и системных типов устройств (relay, media, device, sensors).
Все действия логируются в единый файл /opt/mcp-bridge/logs/actions.log
Версия: 1.1.0
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
    def log_action(*args, **kwargs): pass # Заглушка, если логгер недоступен

# === Загрузка алиасов (с поддержкой системных типов на уровне группы) ===
def load_aliases():
    """Загружает алиасы из групп и раскрывает составные ключи (через запятую).
    Поддерживает дублирующиеся имена в разных группах.
    Возвращает: {"улица": [{"object": ..., "property": ..., "category": "освещение", "type": "relay"}], ...}
    """
    if not os.path.exists(ALIASES_FILE):
        return {}
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        aliases = {}
        for category, group_data in raw.items():
            # group_data теперь содержит "type" и "devices"
            group_type = group_data.get("type")
            devices = group_data.get("devices", {})

            if not group_type or not devices:
                logger.warning(f"Пропущена группа '{category}' из-за отсутствия 'type' или 'devices': {group_data}")
                continue

            for key, spec in devices.items():
                obj = spec.get("object")
                prop = spec.get("property")

                if not obj or not prop:
                    logger.warning(f"Пропущено устройство в группе '{category}' из-за отсутствия 'object' или 'property': {spec}")
                    continue

                names = [name.strip().lower() for name in key.split(",")]
                for name in names:
                    if name:
                        if name not in aliases:
                            aliases[name] = []
                        aliases[name].append({
                            "object": obj,
                            "property": prop,
                            "category": category, # Сохраняем имя группы
                            "type": group_type # Берём тип из группы
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
        r'^(температура|влажность|давление|газ|уровень)\s+(в|на)\s+',
        r'^(свет|освещение|статус|температура|влажность|давление|газ|уровень)\s*',
        r'^(на|в)\s+'
    ]
    for pat in patterns:
        query = re.sub(pat, '', query)
    # Убираем окончания 'е', 'у', 'ом'
    if query.endswith('е'): query = query[:-1]
    if query.endswith('у'): query = query[:-1]
    if query.endswith('ом'): query = query[:-2]
    return query.strip()

# === Поиск устройства по типу (и/или категории) ===
def find_device_by_category(alias_name: str, preferred_categories: list = None, preferred_types: list = None):
    """Находит устройство по имени и предпочтительным типам/категориям.
    Сначала ищет по типу, если указаны оба.
    """
    aliases = load_aliases()
    if alias_name not in aliases:
        return None

    specs = aliases[alias_name]

    # Если указаны предпочтительные типы, ищем сначала по ним
    if preferred_types:
        for spec in specs:
            if spec["type"] in preferred_types:
                # Если также указаны категории, проверяем и их
                if preferred_categories and spec["category"] in preferred_categories:
                    return spec
                elif not preferred_categories: # Если категории не указаны, подходит тип
                    return spec
    # Если типы не указаны или не найдены, ищем по категориям
    elif preferred_categories:
        for spec in specs:
            if spec["category"] in preferred_categories:
                return spec

    # Если ничего не подошло, возвращаем первую
    return specs[0]

# === MCP-сервер ===
mcp = FastMCP("Majordomo Universal")

# === ОСНОВНЫЕ МЕТОДЫ (с поддержкой дубликатов и логированием, поиск по типу) ===

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
    """Человекочитаемое управление с нормализацией и поддержкой дубликатов (по типу relay/device)"""
    norm_name = normalize_query(device_name)
    # Ищем среди устройств типа relay или device
    device_spec = find_device_by_category(norm_name, preferred_types=["relay", "device"])
    if not device_spec:
        aliases = load_aliases()
        # Формируем список только релевантных алиасов
        relevant_aliases = []
        for alias_name, specs in aliases.items():
            for spec in specs:
                if spec["type"] in ["relay", "device"]:
                    relevant_aliases.append(alias_name)
                    break # Добавляем алиас, если хотя бы один из его экземпляров подходит
        available = ", ".join(sorted(set(relevant_aliases)))
        log_action(source="mcp", user="xiaozhi", action="set_device", target=device_name, success=False, details={"error": "Устройство не найдено", "available": available})
        return {"error": f"Устройство '{device_name}' не найдено. Доступные: {available}"}

    value = "1" if state.lower() in ("включи", "включить", "on", "1", "да", "зажги", "активируй", "включи свет") else "0"
    result = set_property(device_spec["object"], device_spec["property"], value)
    if "success" in result:
        log_action(source="mcp", user="xiaozhi", action="set_device", target=norm_name, success=True, details={"state": "включено" if value == "1" else "выключено", "type": device_spec["type"]})
    else:
        log_action(source="mcp", user="xiaozhi", action="set_device", target=norm_name, success=False, details={"error": result.get("error", "Unknown error"), "type": device_spec["type"]})
    return result

@mcp.tool()
def get_device(device_name: str) -> dict:
    """Человекочитаемый статус с нормализацией и поддержкой дубликатов (по всем типам)"""
    norm_name = normalize_query(device_name)
    # Ищем среди всех типов
    device_spec = find_device_by_category(norm_name)
    if not device_spec:
        log_action(source="mcp", user="xiaozhi", action="get_device", target=device_name, success=False, details={"error": "Устройство не найдено"})
        return {"error": f"Устройство '{device_name}' не найдено."}

    result = get_property(device_spec["object"], device_spec["property"])
    if "error" in result:
        log_action(source="mcp", user="xiaozhi", action="get_device", target=norm_name, success=False, details={"error": result["error"], "type": device_spec["type"]})
        return result

    # Формируем ответ в зависимости от типа устройства
    if device_spec["type"] in ["relay", "device"]:
        status = "включено" if result["value"] == "1" else "выключено"
        log_action(source="mcp", user="xiaozhi", action="get_device", target=norm_name, success=True, details={"status": status, "raw_value": result["value"], "type": device_spec["type"]})
        return {"device": device_name, "status": status, "raw_value": result["value"], "type": device_spec["type"]}
    elif device_spec["type"] == "sensors":
        # Для сенсоров возвращаем просто значение, предполагая, что оно уже человекочитаемо
        # или можно добавить логику форматирования в зависимости от свойства
        log_action(source="mcp", user="xiaozhi", action="get_device", target=norm_name, success=True, details={"value": result["value"], "type": device_spec["type"], "raw_value": result["value"]})
        return {"device": device_name, "value": result["value"], "type": device_spec["type"], "raw_value": result["value"]}
    elif device_spec["type"] == "media":
        # Для media можно возвращать статус воспроизведения или текущую песню
        # Пока возвращаем raw_value
        log_action(source="mcp", user="xiaozhi", action="get_device", target=norm_name, success=True, details={"status": result["value"], "type": device_spec["type"], "raw_value": result["value"]})
        return {"device": device_name, "status": result["value"], "type": device_spec["type"], "raw_value": result["value"]}
    else:
        # Неизвестный тип
        log_action(source="mcp", user="xiaozhi", action="get_device", target=norm_name, success=True, details={"raw_value": result["value"], "type": device_spec["type"]})
        return {"device": device_name, "raw_value": result["value"], "type": device_spec["type"]}

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

# === НОВЫЕ МЕТОДЫ (с TTS, поддержкой дубликатов и логированием, поиск по типу) ===

@mcp.tool()
def control_device(device_query: str, action: str, tts_feedback: bool = True) -> dict:
    """Управление с TTS и поддержкой дублирующихся алиасов (по типу relay/device)
    Управляет устройством: включает или выключает.
    Используй, когда пользователь говорит: 'включи свет в комнате отдыха', 'выключи улицу'.
    """
    norm_query = normalize_query(device_query)
    logger.info(f"Запрос управления: '{device_query}' → нормализовано: '{norm_query}'")

    # Ищем среди устройств типа relay или device
    device_spec = find_device_by_category(norm_query, preferred_types=["relay", "device"])
    if not device_spec:
        aliases = load_aliases()
        # Формируем список только релевантных алиасов
        relevant_aliases = []
        for alias_name, specs in aliases.items():
            for spec in specs:
                if spec["type"] in ["relay", "device"]:
                    relevant_aliases.append(alias_name)
                    break # Добавляем алиас, если хотя бы один из его экземпляров подходит
        available = ", ".join(sorted(set(relevant_aliases)))
        logger.info(f"Не найдено. Доступные: {available}")
        log_action(source="mcp", user="xiaozhi", action="control_device", target=device_query, success=False, details={"error": "Устройство не найдено", "available": available})
        return {"error": f"Не найдено: '{device_query}'. Доступные: {available}"}

    # Гибкая обработка действия
    action_lower = action.lower()
    if any(word in action_lower for word in ["включи", "включить", "on", "1", "да", "зажги", "активируй", "включи свет"]):
        value = "1"
        state_word = "включён"
    elif any(word in action_lower for word in ["выключи", "выключить", "off", "0", "нет", "потуши", "деактивируй", "выключи свет"]):
        value = "0"
        state_word = "выключен"
    else:
        log_action(source="mcp", user="xiaozhi", action="control_device", target=device_query, success=False, details={"error": f"Неизвестное действие: '{action}'", "type": device_spec["type"]})
        return {"error": f"Неизвестное действие: '{action}'. Используйте 'включи' или 'выключи'."}

    # Выполнение команды
    resp = call_majordomo("POST", f"data/{device_spec['object']}.{device_spec['property']}", data={"data": value})
    if resp and resp.status_code == 200:
        if tts_feedback:
            # say_via_tts(f"{norm_query} {state_word}")
            pass # Пока без TTS
        logger.info(f"Устройство {device_spec['object']} ({norm_query}) {state_word}")
        log_action(source="mcp", user="xiaozhi", action="control_device", target=norm_query, success=True, details={"state": state_word, "type": device_spec["type"]})
        return {"success": True, "device": device_query, "action": state_word, "type": device_spec["type"]}
    else:
        error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
        logger.error(error_msg)
        log_action(source="mcp", user="xiaozhi", action="control_device", target=norm_query, success=False, details={"error": error_msg, "type": device_spec["type"]})
        return {"error": error_msg}

@mcp.tool()
def get_device_status(device_query: str, tts_feedback: bool = True) -> dict:
    """Статус с TTS и поддержкой дублирующихся алиасов (по всем типам)"""
    norm_query = normalize_query(device_query)
    # Ищем среди всех типов
    device_spec = find_device_by_category(norm_query)
    if not device_spec:
        log_action(source="mcp", user="xiaozhi", action="get_device_status", target=device_query, success=False, details={"error": "Устройство не найдено"})
        return {"error": f"Не найдено: '{device_query}'"}

    resp = call_majordomo("GET", f"data/{device_spec['object']}.{device_spec['property']}")
    if resp and resp.status_code == 200:
        try:
            value = resp.json().get("data", resp.text.strip())
        except:
            value = resp.text.strip()

        # Определяем статус в зависимости от типа
        if device_spec["type"] in ["relay", "device"]:
            status = "включено" if value == "1" else "выключено"
            if tts_feedback:
                # say_via_tts(f"Свет в {norm_query} {status}")
                pass # Пока без TTS
            log_action(source="mcp", user="xiaozhi", action="get_device_status", target=norm_query, success=True, details={"status": status, "value": value, "type": device_spec["type"]})
            return {"device": device_query, "status": status, "type": device_spec["type"]}
        elif device_spec["type"] == "sensors":
            if tts_feedback:
                # say_via_tts(f"Значение {norm_query}: {value}")
                pass # Пока без TTS
            log_action(source="mcp", user="xiaozhi", action="get_device_status", target=norm_query, success=True, details={"value": value, "type": device_spec["type"]})
            return {"device": device_query, "value": value, "type": device_spec["type"]}
        else: # media или другие
            if tts_feedback:
                # say_via_tts(f"Статус {norm_query}: {value}")
                pass # Пока без TTS
            log_action(source="mcp", user="xiaozhi", action="get_device_status", target=norm_query, success=True, details={"raw_value": value, "type": device_spec["type"]})
            return {"device": device_query, "raw_value": value, "type": device_spec["type"]}
    else:
        error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
        logger.error(error_msg)
        log_action(source="mcp", user="xiaozhi", action="get_device_status", target=norm_query, success=False, details={"error": error_msg, "type": device_spec["type"]})
        return {"error": error_msg}

# --- НОВЫЕ ИНСТРУМЕНТЫ ДЛЯ ПОИСКА ПО НАЗВАНИЮ ГРУППЫ (ДЛЯ ДЕМОНСТРАЦИИ) ---
# Эти инструменты ищут устройства по названию группы (например, "освещение", "температура")
# и затем применяют соответствующую логику (управление для relay, получение значения для sensors).

@mcp.tool()
def control_relay_by_category_name(category_name: str, location: str, action: str, tts_feedback: bool = True) -> dict:
    """Управление реле по названию группы и местоположению (например, включи освещение в комнате отдыха).
    category_name: "освещение", "свет" и т.д. (название группы, содержащей relay)
    location: "комната отдыха", "кухня" и т.д. (алиас устройства)
    action: "включи", "выключи"
    """
    # Загрузим все алиасы
    aliases = load_aliases()
    # Найдём все алиасы, принадлежащие группе с именем category_name и типом relay
    relevant_specs = []
    full_aliases_data = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            full_aliases_data = json.load(f)

    if category_name in full_aliases_data and full_aliases_data[category_name].get("type") == "relay":
        devices_in_group = full_aliases_data[category_name].get("devices", {})
        for key, spec in devices_in_group.items():
            names = [n.strip().lower() for n in key.split(",")]
            for name in names:
                if name == location.lower(): # Найдено совпадение по местоположению
                    relevant_specs.append({
                        "object": spec["object"],
                        "property": spec["property"],
                        "category": category_name,
                        "type": "relay"
                    })
                    break # Нашли в этой группе, выходим из цикла по именам

    if not relevant_specs:
         log_action(source="mcp", user="xiaozhi", action="control_relay_by_category_name", target=f"{category_name} {location}", success=False, details={"error": f"Устройство не найдено в группе '{category_name}'", "type": "relay"})
         return {"error": f"Устройство '{location}' не найдено в группе '{category_name}'."}

    # Берём первое найденное устройство
    device_spec = relevant_specs[0]
    logger.info(f"Найдено устройство для управления по группе и местоположению: {device_spec}")

    # Гибкая обработка действия
    action_lower = action.lower()
    if any(word in action_lower for word in ["включи", "включить", "on", "1", "да", "зажги", "активируй", "включи свет"]):
        value = "1"
        state_word = "включён"
    elif any(word in action_lower for word in ["выключи", "выключить", "off", "0", "нет", "потуши", "деактивируй", "выключи свет"]):
        value = "0"
        state_word = "выключен"
    else:
        log_action(source="mcp", user="xiaozhi", action="control_relay_by_category_name", target=f"{category_name} {location}", success=False, details={"error": f"Неизвестное действие: '{action}'", "type": device_spec["type"]})
        return {"error": f"Неизвестное действие: '{action}'. Используйте 'включи' или 'выключи'."}

    # Выполнение команды
    resp = call_majordomo("POST", f"data/{device_spec['object']}.{device_spec['property']}", data={"data": value})
    if resp and resp.status_code == 200:
        if tts_feedback:
            # say_via_tts(f"{location} {state_word}")
            pass # Пока без TTS
        logger.info(f"Устройство {device_spec['object']} ({category_name} {location}) {state_word}")
        log_action(source="mcp", user="xiaozhi", action="control_relay_by_category_name", target=f"{category_name} {location}", success=True, details={"state": state_word, "type": device_spec["type"]})
        return {"success": True, "group": category_name, "location": location, "action": state_word, "type": device_spec["type"]}
    else:
        error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
        logger.error(error_msg)
        log_action(source="mcp", user="xiaozhi", action="control_relay_by_category_name", target=f"{category_name} {location}", success=False, details={"error": error_msg, "type": device_spec["type"]})
        return {"error": error_msg}

@mcp.tool()
def get_sensor_by_category_name(category_name: str, location: str, tts_feedback: bool = True) -> dict:
    """Получение значения сенсора по названию группы и местоположению (например, какая температура в комнате отдыха).
    category_name: "температура", "влажность" и т.д. (название группы, содержащей sensors)
    location: "комната отдыха", "душ" и т.д. (алиас устройства)
    """
    # Загрузим все алиасы
    aliases = load_aliases()
    # Найдём все алиасы, принадлежащие группе с именем category_name и типом sensors
    relevant_specs = []
    full_aliases_data = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            full_aliases_data = json.load(f)

    if category_name in full_aliases_data and full_aliases_data[category_name].get("type") == "sensors":
        devices_in_group = full_aliases_data[category_name].get("devices", {})
        for key, spec in devices_in_group.items():
            names = [n.strip().lower() for n in key.split(",")]
            for name in names:
                if name == location.lower(): # Найдено совпадение по местоположению
                    relevant_specs.append({
                        "object": spec["object"],
                        "property": spec["property"],
                        "category": category_name,
                        "type": "sensors"
                    })
                    break # Нашли в этой группе, выходим из цикла по именам

    if not relevant_specs:
         log_action(source="mcp", user="xiaozhi", action="get_sensor_by_category_name", target=f"{category_name} {location}", success=False, details={"error": f"Сенсор не найден в группе '{category_name}'", "type": "sensors"})
         return {"error": f"Сенсор '{location}' не найден в группе '{category_name}'."}

    # Берём первое найденное устройство
    device_spec = relevant_specs[0]
    logger.info(f"Найден сенсор для получения значения по группе и местоположению: {device_spec}")

    # Получение значения
    resp = call_majordomo("GET", f"data/{device_spec['object']}.{device_spec['property']}")
    if resp and resp.status_code == 200:
        try:
            value = resp.json().get("data", resp.text.strip())
        except:
            value = resp.text.strip()

        # Форматирование ответа в зависимости от типа сенсора (по названию группы)
        if "температура" in category_name.lower():
            response_text = f"температура в {location} {value} градусов"
        elif "влажность" in category_name.lower():
            response_text = f"влажность в {location} {value} процентов"
        else:
            # Для других типов сенсоров
            response_text = f"значение {category_name} в {location} {value}"

        if tts_feedback:
            # say_via_tts(response_text)
            pass # Пока без TTS
        logger.info(f"Значение {category_name} в {location}: {value}")
        log_action(source="mcp", user="xiaozhi", action="get_sensor_by_category_name", target=f"{category_name} {location}", success=True, details={"value": value, "response_text": response_text, "type": device_spec["type"]})
        return {"sensor_group": category_name, "location": location, "value": value, "response": response_text, "type": device_spec["type"]}
    else:
        error_msg = f"MajorDoMo error: {resp.status_code if resp else 'timeout'}"
        logger.error(error_msg)
        log_action(source="mcp", user="xiaozhi", action="get_sensor_by_category_name", target=f"{category_name} {location}", success=False, details={"error": error_msg, "type": device_spec["type"]})
        return {"error": error_msg}


# === Запуск ===
if __name__ == "__main__":
    mcp.run(transport="stdio")
