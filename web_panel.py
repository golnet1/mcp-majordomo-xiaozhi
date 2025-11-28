#!/usr/bin/env python3
"""Веб-панель для редактирования device_aliases.json
С поддержкой системных типов устройств (relay, media, device, sensors),
редактирования устройств, множественных алиасов, поиска по логам
и автоматической проверки обновлений из GitHub."""
import os
import sys
import json
import subprocess
from flask import Flask, request, jsonify, render_template_string, Response

# === Настройки безопасности ===
WEB_PANEL_USER = os.getenv("WEB_PANEL_USER", "admin")
WEB_PANEL_PASS = os.getenv("WEB_PANEL_PASS", "0")
ALIASES_FILE = "/opt/mcp-bridge/device_aliases.json"
LOG_FILE = "/opt/mcp-bridge/logs/actions.log"
VERSION_FILE = "/opt/mcp-bridge/VERSION"
STATUS_FILE = "/opt/mcp-bridge/update_status.json"
GITHUB_REPO = "golnet1/mcp-majordomo-xiaozhi"

# === Инициализация Flask ===
app = Flask(__name__)

# === Отключаем кэширование в браузере ===
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, public, max-age=0"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# === Базовая аутентификация ===
def check_auth(username, password):
    return username == WEB_PANEL_USER and password == WEB_PANEL_PASS

def requires_auth(f):
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response('Необходима аутентификация', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# === Загрузка и сохранение алиасов (новая структура) ===
def load_aliases():
    if not os.path.exists(ALIASES_FILE):
        return {}
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Проверяем структуру на соответствие новой
        for category, group_data in data.items():
            if not isinstance(group_data, dict) or "type" not in group_data or "devices" not in group_data:
                print(f"Предупреждение: Неверная структура категории '{category}' в файле: {group_data}", file=sys.stderr)
                continue
            if group_data["type"] not in ["relay", "media", "device", "sensors"]:
                print(f"Предупреждение: Неизвестный системный тип в категории '{category}': {group_data['type']}", file=sys.stderr)
        aliases = {}
        for category, group_data in data.items():
            devices = group_data.get("devices", {})
            for key, spec in devices.items():
                obj = spec.get("object")
                prop = spec.get("property")
                device_type = group_data.get("type") # Берём тип из группы

                if not obj or not prop or not device_type:
                    print(f"Предупреждение: Пропущено устройство в категории '{category}' из-за отсутствия полей: {spec}", file=sys.stderr)
                    continue

                names = [name.strip().lower() for name in key.split(",")]
                for name in names:
                    if name:
                        if name not in aliases:
                            aliases[name] = []
                        aliases[name].append({
                            "object": obj,
                            "property": prop,
                            "category": category,
                            "type": device_type # Добавляем тип
                        })
        return aliases
    except Exception as e:
        print(f"Ошибка загрузки алиасов: {e}", file=sys.stderr)
        return {}

def save_aliases(data):
    backup = ALIASES_FILE + ".bak"
    if os.path.exists(ALIASES_FILE):
        os.replace(ALIASES_FILE, backup)
    with open(ALIASES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# === Логирование действий ===
def log_action(source, action, target, success=True, user="web", details=None):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        record = {
            "timestamp": __import__('datetime').datetime.utcnow().isoformat() + "Z",
            "source": source,
            "user": user,
            "action": action,
            "target": target,
            "success": success,
            "details": details or {}
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Ошибка логирования: {e}", file=sys.stderr)

# === API для категорий (с типом) ===
@app.route("/api/categories")
@requires_auth
def get_categories():
    aliases = load_aliases()
    # Возвращаем список категорий с их типами
    # Для этого нужно загрузить полный JSON
    raw_data = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    categories_with_types = [{"name": name, "type": data["type"]} for name, data in raw_data.items()]
    return jsonify(categories_with_types)

@app.route("/api/category", methods=["POST"])
@requires_auth
def add_category():
    data = request.json
    name = data.get("name")
    device_type = data.get("type") # Новый параметр

    if not name or not device_type:
        return jsonify({"error": "Имя и тип категории обязательны"}), 400

    if device_type not in ["relay", "media", "device", "sensors"]:
         return jsonify({"error": "Неверный системный тип"}), 400

    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    if name in raw:
        return jsonify({"error": f"Категория с именем '{name}' уже существует"}), 409

    raw[name] = {"type": device_type, "devices": {}} # Инициализируем новую категорию с типом и пустыми устройствами
    save_aliases(raw)
    log_action(source="web", user=request.authorization.username, action="add_category", target=name, success=True, details={"type": device_type})
    return jsonify({"success": True})

@app.route("/api/category/<name>", methods=["DELETE"])
@requires_auth
def delete_category(name):
    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    if name not in raw:
        return jsonify({"error": "Категория не найдена"}), 404

    del raw[name] # Удаляем всю категорию
    save_aliases(raw)
    log_action(source="web", user=request.authorization.username, action="delete_category", target=name, success=True)
    return jsonify({"success": True})

# === API для устройств (с типом) ===
@app.route("/api/device", methods=["POST"])
@requires_auth
def add_device():
    data = request.json
    category = data.get("category") # Имя категории
    name = data.get("name") # Имя устройства (алиасы)
    obj = data.get("object") # Object
    prop = data.get("property") # Property

    if not all([category, name, obj, prop]):
        return jsonify({"error": "Все поля обязательны"}), 400

    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

    if category not in raw:
        return jsonify({"error": f"Категория '{category}' не найдена"}), 404

    # Проверяем, существует ли уже устройство с таким именем (алиасом) в *любой* категории
    for existing_category, existing_group_data in raw.items():
        for existing_alias_key in existing_group_data.get("devices", {}).keys():
            existing_names = [n.strip() for n in existing_alias_key.split(",")]
            if name in existing_names:
                return jsonify({"error": f"Устройство с именем '{name}' уже существует в категории '{existing_category}'"}), 409

    # Проверяем, есть ли уже устройство с такими object и property в этой категории
    existing_key = None
    for key, spec in raw[category]["devices"].items():
        if spec["object"] == obj and spec["property"] == prop:
            existing_key = key
            break

    if existing_key:
        # === Объединяем имена через запятую ===
        names = [n.strip() for n in existing_key.split(",")]
        if name not in names:
            names.append(name)
        new_key = ",".join(names)
        # === Заменяем старый ключ на новый ===
        raw[category]["devices"][new_key] = {"object": obj, "property": prop}
        del raw[category]["devices"][existing_key]
    else:
        # === Создаём новую запись ===
        raw[category]["devices"][name] = {"object": obj, "property": prop}

    save_aliases(raw)
    log_action(source="web", user=request.authorization.username, action="add_device", target=f"{category}/{name}", success=True, details={"object": obj, "property": prop})
    return jsonify({"success": True})

@app.route("/api/device/edit", methods=["POST"])
@requires_auth
def edit_device():
    data = request.json
    old_category = data.get("old_category") # Старая категория
    old_name = data.get("old_name") # Старое имя устройства (алиас)
    new_category = data.get("new_category") # Новая категория
    new_name = data.get("new_name") # Новое имя устройства (алиас)
    obj = data.get("object") # Object
    prop = data.get("property") # Property

    if not all([old_category, old_name, new_category, new_name, obj, prop]):
        return jsonify({"error": "Все поля обязательны"}), 400

    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

    if old_category not in raw:
        return jsonify({"error": "Старая категория не найдена"}), 404

    # === НОВОЕ: Найти ключ, содержащий old_name ===
    old_key = None
    for key in raw[old_category]["devices"].keys():
        names = [n.strip() for n in key.split(",")]
        if old_name in names:
            old_key = key
            break

    if not old_key:
        return jsonify({"error": "Старое устройство не найдено"}), 404

    # === Удаляем old_name из старого ключа ===
    old_names = [n.strip() for n in old_key.split(",")]
    old_names.remove(old_name)

    # === Удаляем старую запись ===
    old_spec = raw[old_category]["devices"].pop(old_key)

    if old_names:
        # === Если остались имена, создаём новый ключ ===
        remaining_key = ",".join(old_names)
        raw[old_category]["devices"][remaining_key] = old_spec

    # Проверяем, есть ли уже устройство с такими object и property в новой категории
    existing_key = None
    if new_category in raw:
        for key, spec in raw[new_category]["devices"].items():
            if spec["object"] == obj and spec["property"] == prop:
                existing_key = key
                break
    else:
        # Если новой категории не существует, создаём её с типом 'relay' по умолчанию или возвращаем ошибку
        # Пусть пока будет ошибка, чтобы пользователь сначала создал категорию с типом
        return jsonify({"error": f"Категория '{new_category}' не найдена. Сначала создайте её."}), 404


    if existing_key and new_category == old_category:
        # === Объединяем имена ===
        names = [n.strip() for n in existing_key.split(",")]
        if new_name not in names:
            names.append(new_name)
        new_key = ",".join(names)
        raw[new_category]["devices"][new_key] = {"object": obj, "property": prop}
        # Удаляем старый ключ, если он отличается
        if existing_key != new_key:
            del raw[new_category]["devices"][existing_key]
    elif existing_key and new_category != old_category:
        # === Объединяем в новой категории ===
        names = [n.strip() for n in existing_key.split(",")]
        if new_name not in names:
            names.append(new_name)
        new_key = ",".join(names)
        raw[new_category]["devices"][new_key] = {"object": obj, "property": prop}
        # Удаляем старый ключ, если он отличается
        if existing_key != new_key:
            del raw[new_category]["devices"][existing_key]
    else:
        # === Создаём новую запись ===
        raw[new_category]["devices"][new_name] = {"object": obj, "property": prop}

    save_aliases(raw)
    log_action(source="web", user=request.authorization.username, action="edit_device", target=f"{old_category}/{old_name}", success=True, details={"new_category": new_category, "new_name": new_name, "object": obj, "property": prop})
    return jsonify({"success": True})

@app.route("/api/device", methods=["DELETE"])
@requires_auth
def delete_device():
    category = request.args.get("category") # Имя категории
    name = request.args.get("name") # Имя устройства (алиас)

    if not category or not name:
        return jsonify({"error": "Параметры category и name обязательны"}), 400

    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

    if category not in raw:
        return jsonify({"error": "Категория не найдена"}), 404

    # Найдём ключ, содержащий имя устройства
    key_to_delete = None
    for key in raw[category]["devices"].keys():
        names = [n.strip() for n in key.split(",")]
        if name in names:
            key_to_delete = key
            break

    if not key_to_delete:
        return jsonify({"error": "Устройство не найдено"}), 404

    # Удаляем имя из ключа
    names = [n.strip() for n in key_to_delete.split(",")]
    names.remove(name)

    # Удаляем старую запись
    spec = raw[category]["devices"].pop(key_to_delete)

    if names:
        # Если остались имена, создаём новый ключ
        new_key = ",".join(names)
        raw[category]["devices"][new_key] = spec

    save_aliases(raw)
    log_action(source="web", user=request.authorization.username, action="delete_device", target=f"{category}/{name}", success=True)
    return jsonify({"success": True})

# --- Остальные API (импорт, экспорт, логи, обновления) ---
@app.route("/api/export")
@requires_auth
def export_aliases():
    if not os.path.exists(ALIASES_FILE):
        return jsonify({"error": "Файл алиасов не найден"}), 404
    with open(ALIASES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    log_action(source="web", user=request.authorization.username, action="export_aliases", target="device_aliases.json", success=True, details={"file_size": len(json.dumps(data))})
    return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json", headers={"Content-Disposition": "attachment;filename=device_aliases.json"})

@app.route("/api/import", methods=["POST"])
@requires_auth
def import_aliases():
    if 'file' not in request.files:
        return jsonify({"error": "Файл не загружен"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Файл не выбран"}), 400
    try:
        data = json.load(file)
        if not isinstance(data, dict):
            return jsonify({"error": "Неверный формат JSON"}), 400
        # Проверим структуру на соответствие новой
        for category, group_data in data.items():
            if not isinstance(group_data, dict) or "type" not in group_data or "devices" not in group_data:
                 return jsonify({"error": f"Неверная структура категории в импортируемом файле: {category}"}), 400
            if group_data["type"] not in ["relay", "media", "device", "sensors"]:
                 return jsonify({"error": f"Неверный системный тип в импортируемом файле: {group_data['type']}"}), 400
        save_aliases(data)
        log_action(source="web", user=request.authorization.username, action="import_aliases", target="device_aliases.json", success=True, details={"file_size": len(json.dumps(data))})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Ошибка парсинга: {str(e)}"}), 400

@app.route("/logs")
@requires_auth
def logs_page():
    return render_template_string(LOGS_HTML_TEMPLATE)

@app.route("/logs/api")
@requires_auth
def get_logs_api():
    query = request.args.get('query', '').lower()
    if not os.path.exists(LOG_FILE):
        return jsonify([])
    try:
        logs = []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    found = True
                    if query:
                        search_text = query.lower()
                        found = (
                            search_text in record.get("timestamp", "").lower() or
                            search_text in record.get("source", "").lower() or
                            search_text in record.get("user", "").lower() or
                            search_text in record.get("action", "").lower() or
                            search_text in record.get("target", "").lower() or
                            (search_text in "успешно успех" and record.get("success")) or
                            (search_text in "ошибка неудача fail" and not record.get("success"))
                        )
                    if not found:
                        continue
                    logs.append(record)
                except:
                    continue
        # Сортируем по времени (предполагаем, что timestamp есть)
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        # Ограничиваем последние 1000 записей
        return jsonify(logs[:1000])
    except Exception as e:
        print(f"LOG LOAD ERROR: {e}", file=sys.stderr)
        return jsonify([])

@app.route("/logs/export")
@requires_auth
def export_logs():
    if not os.path.exists(LOG_FILE):
        return "", 404
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Source", "User", "Action", "Target", "Success", "Details"])
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    writer.writerow([
                        record.get("timestamp"),
                        record.get("source"),
                        record.get("user"),
                        record.get("action"),
                        record.get("target"),
                        record.get("success"),
                        json.dumps(record.get("details", {}), ensure_ascii=False)
                    ])
                except:
                    continue
    except Exception as e:
        print(f"LOG EXPORT ERROR: {e}", file=sys.stderr)

    output.seek(0)
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=actions_log.csv"})

# === Функции обновления ===
def get_current_version():
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, "r") as f:
            return f.read().strip()
    return "unknown"

def get_latest_version():
    try:
        import urllib.request
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data["tag_name"]
    except Exception as e:
        print(f"Ошибка получения версии: {e}", file=sys.stderr)
        return None

def update_from_github():
    try:
        import urllib.request
        import zipfile
        import shutil
        # Получаем URL архива
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        zip_url = data["zipball_url"]
        # Скачиваем
        zip_path = "/tmp/mcp-update.zip"
        urllib.request.urlretrieve(zip_url, zip_path)
        # Распаковываем
        extract_to = "/tmp/mcp-update"
        shutil.rmtree(extract_to, ignore_errors=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        # Находим корневую папку
        root_items = os.listdir(extract_to)
        if not root_items:
            raise Exception("Архив пуст")
        update_dir = os.path.join(extract_to, root_items[0])
        print(f"Обновление из: {update_dir}", file=sys.stderr)
        # Обновляем файлы
        safe_files = ["mcp_pipe.py", "web_panel.py", "mcp-majordomo-xiaozhi.py", "scheduler.py", "mcp_config.json", "check_update.py", "telegram_bot.py", "action_logger.py", "log_rotator.py", "VERSION"]
        updated = []
        for file in safe_files:
            src = os.path.join(update_dir, file)
            dst = f"/opt/mcp-bridge/{file}"
            if os.path.exists(src):
                shutil.copy2(src, dst)
                updated.append(file)
                print(f"Обновлён: {file}", file=sys.stderr)
            else:
                print(f"Файл НЕ найден в релизе: {file}", file=sys.stderr)
        if not updated:
            raise Exception("Ни один файл не был обновлён")
        # Перезапускаем сервисы
        subprocess.run(["sudo", "systemctl", "restart", "mcp-web-panel", "mcp-majordomo"], check=True)
        return True
    except Exception as e:
        print(f"Ошибка обновления: {e}", file=sys.stderr)
        return False

@app.route("/update/check", methods=["GET"])
@requires_auth
def check_update():
    try:
        result = subprocess.run([sys.executable, "/opt/mcp-bridge/check_update.py"], capture_output=True, text=True)
        # check_update.py должен возвращать JSON
        import json
        try:
            update_info = json.loads(result.stdout)
            return jsonify(update_info)
        except json.JSONDecodeError:
            return jsonify({"error": "Ошибка парсинга ответа check_update.py", "raw_output": result.stdout}), 500
    except Exception as e:
        return jsonify({"error": f"Ошибка проверки обновления: {e}"}), 500

@app.route("/update/apply", methods=["POST"])
@requires_auth
def apply_update():
    try:
        result = subprocess.run([sys.executable, "/opt/mcp-bridge/check_update.py", "--apply"], capture_output=True, text=True)
        if result.returncode == 0:
            # Успешно обновлено, удаляем статус
            if os.path.exists(STATUS_FILE):
                os.remove(STATUS_FILE)
            return jsonify({"success": True, "message": "Система обновлена и перезапущена"})
        else:
            return jsonify({"error": f"Ошибка при обновлении: {result.stderr}"}), 500
    except Exception as e:
        return jsonify({"error": f"Ошибка выполнения обновления: {e}"}), 500

# === Шаблоны ===
HTML_TEMPLATE = """<!DOCTYPE html>
<html data-theme="{{ request.cookies.get('theme', 'light') }}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Редактор алиасов MajorDoMo</title>
    <style>
        :root {
            --bg: #ffffff;
            --text: #333333;
            --card-bg: #ffffff;
            --border: #e0e0e0;
            --primary: #4a6fa5;
            --success: #28a745;
            --danger: #dc3545;
            --warning: #ffc107;
            --input-bg: #ffffff;
            --input-border: #ddd;
            --header-bg: #f8f9fa;
        }
        [data-theme="dark"] {
            --bg: #121212;
            --text: #e0e0e0;
            --card-bg: #1e1e1e;
            --border: #444444;
            --primary: #66aaff;
            --success: #4caf50;
            --danger: #f44336;
            --warning: #ff9800;
            --input-bg: #2d2d2d;
            --input-border: #555555;
            --header-bg: #2b2b2b;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
            transition: background-color 0.3s, color 0.3s;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            background-color: var(--header-bg);
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        h1 {
            margin: 0;
            color: var(--primary);
        }
        .theme-toggle {
            background: none;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 12px;
            border-radius: 4px;
            cursor: pointer;
        }
        .export-import {
            text-align: center;
            margin: 16px 0;
        }
        .export-import button {
            margin: 0 8px;
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1rem;
        }
        .export-btn { background: var(--success); color: white; }
        .import-btn { background: var(--primary); color: white; }

        .add-category {
            background-color: var(--card-bg);
            padding: 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .add-category input, .add-category select {
            padding: 8px;
            border: 1px solid var(--input-border);
            border-radius: 4px;
            background-color: var(--input-bg);
            color: var(--text);
            flex: 1;
        }
        .add-category button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            background: var(--primary);
            color: white;
        }

        .category {
            background-color: var(--card-bg);
            padding: 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
            margin-bottom: 20px;
        }
        .category-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .category-header h2 {
            margin: 0;
            color: var(--primary);
        }
        .delete-category {
            background: var(--danger);
            color: white;
            border: none;
            border-radius: 4px;
            padding: 4px 8px;
            cursor: pointer;
        }
        .devices {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .device {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px;
            background-color: var(--bg);
            border-radius: 4px;
            border: 1px solid var(--border);
        }
        .device-info {
            flex: 1;
        }
        .device-name {
            font-weight: bold;
        }
        .device-details {
            font-size: 0.85rem;
            color: #666;
        }
        [data-theme="dark"] .device-details {
            color: #aaa;
        }
        .device-actions button {
            margin-left: 8px;
            padding: 4px 8px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9rem;
        }
        .edit-btn { background: var(--warning); color: black; }
        .delete-btn { background: var(--danger); color: white; }

        .add-device {
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px dashed var(--border);
        }
        .device-fields {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
        }
        .device-fields input {
            flex: 1;
            padding: 8px;
            border: 1px solid var(--input-border);
            border-radius: 4px;
            background-color: var(--input-bg);
            color: var(--text);
        }
        .add-device button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            background: var(--primary);
            color: white;
        }

        #status {
            margin-top: 16px;
            padding: 12px;
            border-radius: 4px;
            text-align: center;
        }
        .success { background-color: #d4edda; color: #155724; }
        .error { background-color: #f8d7da; color: #721c24; }

        /* Модальное окно редактирования */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }
        .modal-content {
            background-color: var(--card-bg);
            margin: 15% auto;
            padding: 20px;
            border: 1px solid var(--border);
            border-radius: 8px;
            width: 80%;
            max-width: 500px;
            color: var(--text);
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .modal-header h3 {
            margin: 0;
        }
        .close {
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .form-group {
            margin-bottom: 16px;
        }
        .form-group label {
            display: block;
            margin-bottom: 4px;
            font-weight: bold;
        }
        .form-group input {
            width: 100%;
            padding: 8px;
            border: 1px solid var(--input-border);
            border-radius: 4px;
            background-color: var(--input-bg);
            color: var(--text);
            box-sizing: border-box;
        }
        .modal-footer {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
        }
        .modal-footer button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1rem;
        }
        .cancel-btn { background: var(--danger); color: white; }
        .save-btn { background: var(--success); color: white; }

        /* Стили для страницы логов */
        #log-search {
            width: 100%;
            padding: 10px;
            margin-bottom: 16px;
            border: 1px solid var(--input-border);
            border-radius: 4px;
            background-color: var(--input-bg);
            color: var(--text);
        }
        #log-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .log-entry {
            padding: 10px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background-color: var(--bg);
            font-family: monospace;
            font-size: 0.9em;
        }
        .log-success { border-left: 4px solid var(--success); }
        .log-error { border-left: 4px solid var(--danger); }
        .no-results {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        [data-theme="dark"] .no-results {
            color: #aaa;
        }
        .export-csv {
            display: inline-block;
            margin-top: 16px;
            padding: 8px 16px;
            background: var(--primary);
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }

        /* Уведомление об обновлении */
        #update-notification {
            display: none;
            background: #fff3cd;
            color: #856404;
            padding: 12px;
            border: 1px solid #ffeaa7;
            border-radius: 8px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Редактор алиасов MajorDoMo</h1>
            <button class="theme-toggle" onclick="toggleTheme()">Тема</button>
        </header>

        <div id="update-notification">
            <strong>Доступно обновление!</strong> Перейдите на вкладку "Обновления", чтобы установить.
        </div>

        <div class="export-import">
            <button class="export-btn" onclick="exportAliases()">📤 Экспорт JSON</button>
            <button class="import-btn" onclick="document.getElementById('import-file').click()">📥 Импорт JSON</button>
            <input type="file" id="import-file" accept=".json" style="display:none;" onchange="importAliases(this.files[0])">
            <a href="/logs" class="export-btn">📋 Логи</a>
            <a href="#" class="export-btn" onclick="showUpdateTab()">🔄 Обновления</a>
        </div>

        <div id="status"></div>

        <div class="add-category">
            <input type="text" id="new_category" placeholder="Название группы (например, приборы)">
            <select id="new_type">
                <option value="">Выберите тип...</option>
                <option value="relay">relay</option>
                <option value="media">media</option>
                <option value="device">device</option>
                <option value="sensors">sensors</option>
            </select>
            <button onclick="addCategory()">Добавить группу</button>
        </div>

        <div id="categories-container"></div>

    </div>

    <!-- Модальное окно для редактирования -->
    <div id="edit-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Редактировать устройство</h3>
                <span class="close" onclick="closeModal()">&times;</span>
            </div>
            <div class="form-group">
                <label>Название (через запятую)</label>
                <input type="text" id="edit_name">
            </div>
            <div class="form-group">
                <label>Категория</label>
                <select id="edit_category"></select> <!-- Заполняется динамически -->
            </div>
            <div class="form-group">
                <label>Object</label>
                <input type="text" id="edit_object">
            </div>
            <div class="form-group">
                <label>Property</label>
                <input type="text" id="edit_property">
            </div>
            <div class="modal-footer">
                <button class="cancel-btn" onclick="closeModal()">Отмена</button>
                <button class="save-btn" onclick="saveDevice()">Сохранить</button>
            </div>
        </div>
    </div>

    <script>
        // Проверка обновления при загрузке
        document.addEventListener('DOMContentLoaded', () => {
            fetch('/update/status').then(res => res.json()).then(data => {
                if (data.update_available) {
                    document.getElementById('update-notification').style.display = 'block';
                }
            }).catch(err => console.log('Ошибка загрузки статуса обновления:', err));

            const saved = localStorage.getItem('theme') || 'light';
            document.documentElement.setAttribute('data-theme', saved);
        });

        function toggleTheme() {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            const next = current === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        }

        function showMessage(text, isError = false) {
            const status = document.getElementById('status');
            status.innerHTML = `<div class="${isError ? 'error' : 'success'}">${text}</div>`;
            setTimeout(() => status.innerHTML = '', 3000);
        }

        async function loadCategories() {
            const res = await fetch('/api/categories');
            const categories = await res.json();
            const container = document.getElementById('categories-container');
            container.innerHTML = '';

            // Загрузим полный JSON для получения устройств
            const fullAliasesRes = await fetch('/api/export');
            let fullAliases = {};
            try {
                fullAliases = await fullAliasesRes.json();
            } catch (e) {
                console.error("Ошибка загрузки полного JSON:", e);
                fullAliases = {};
            }

            for (const cat of categories) {
                const category = cat.name;
                const type = cat.type;
                const devices = fullAliases[category]?.devices || {};

                const categoryDiv = document.createElement('div');
                categoryDiv.className = 'category';
                categoryDiv.innerHTML = `<div class="category-header"><h2>${category} (Тип: ${type})</h2><button class="delete-category" onclick="deleteCategory('${category}')">🗑️</button></div>`;

                const devicesDiv = document.createElement('div');
                devicesDiv.className = 'devices';
                let idx = 0;
                for (const [key, spec] of Object.entries(devices)) {
                    const names = key.split(',').map(n => n.trim());
                    names.forEach(name => {
                        const deviceDiv = document.createElement('div');
                        deviceDiv.className = 'device';
                        deviceDiv.innerHTML = `
                            <div class="device-info">
                                <div class="device-name">${name}</div>
                                <div class="device-details">Object: ${spec.object}, Property: ${spec.property}</div>
                            </div>
                            <div class="device-actions">
                                <button class="edit-btn" onclick="editDevice('${category}', '${name}', '${spec.object}', '${spec.property}')">✏️</button>
                                <button class="delete-btn" onclick="deleteDevice('${category}', '${name}')">🗑️</button>
                            </div>
                        `;
                        devicesDiv.appendChild(deviceDiv);
                    });
                    idx++;
                }

                // Форма добавления устройства в категорию
                const addDeviceDiv = document.createElement('div');
                addDeviceDiv.className = 'add-device';
                addDeviceDiv.innerHTML = `
                    <div class="device-fields">
                        <input type="text" id="device_name_${idx}" placeholder="Название (например, улица)">
                        <input type="text" id="object_${idx}" placeholder="Object (например, Relay01)">
                        <input type="text" id="property_${idx}" placeholder="Property (например, status)">
                    </div>
                    <button onclick="addDevice('${category}', ${idx})">Добавить устройство</button>
                `;
                devicesDiv.appendChild(addDeviceDiv);

                categoryDiv.appendChild(devicesDiv);
                container.appendChild(categoryDiv);
            }
        }

        let aliasesByType = {};
        async function refreshData() {
            // Загрузка и обновление данных
            const fullAliasesRes = await fetch('/api/export');
            const fullAliases = await fullAliasesRes.json();
            aliasesByType = fullAliases;
            loadCategories();
        }

        // --- API вызовы ---
        async function addCategory() {
            const name = document.getElementById('new_category').value.trim();
            const type = document.getElementById('new_type').value.trim();
            if (!name || !type) {
                showMessage('Заполните все поля', true);
                return;
            }

            const res = await fetch('/api/category', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({name: name, type: type})
            });
            if (res.ok) {
                showMessage('Категория добавлена');
                document.getElementById('new_category').value = '';
                document.getElementById('new_type').value = '';
                refreshData();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка', true);
            }
        }

        async function deleteCategory(name) {
            if (!confirm('Удалить категорию и все устройства?')) return;
            const res = await fetch(`/api/category/${encodeURIComponent(name)}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                showMessage('Категория удалена');
                refreshData();
            } else {
                showMessage('Ошибка удаления', true);
            }
        }

        async function addDevice(category, idx) {
            const name = document.getElementById(`device_name_${idx}`).value.trim();
            const obj = document.getElementById(`object_${idx}`).value.trim();
            const prop = document.getElementById(`property_${idx}`).value.trim();
            if (!name || !obj || !prop) {
                showMessage('Заполните все поля', true);
                return;
            }

            const res = await fetch('/api/device', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({category: category, name: name, object: obj, property: prop})
            });
            if (res.ok) {
                showMessage('Устройство добавлено');
                document.getElementById(`device_name_${idx}`).value = '';
                document.getElementById(`object_${idx}`).value = '';
                document.getElementById(`property_${idx}`).value = '';
                refreshData();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка', true);
            }
        }

        async function deleteDevice(category, name) {
            if (!confirm('Удалить устройство?')) return;
            const res = await fetch(`/api/device?category=${encodeURIComponent(category)}&name=${encodeURIComponent(name)}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                showMessage('Устройство удалено');
                refreshData();
            } else {
                showMessage('Ошибка удаления', true);
            }
        }

        // --- Редактирование ---
        let currentEdit = { category: '', name: '' };

        async function editDevice(category, name, obj, prop) {
            currentEdit = { category, name };

            // Загрузим категории в селект
            const select = document.getElementById('edit_category');
            select.innerHTML = '';
            const res = await fetch('/api/categories');
            const categories = await res.json();
            categories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.name;
                option.textContent = `${cat.name} (Тип: ${cat.type})`;
                if (cat.name === category) option.selected = true;
                select.appendChild(option);
            });

            document.getElementById('edit_name').value = name;
            document.getElementById('edit_object').value = obj;
            document.getElementById('edit_property').value = prop;
            document.getElementById('edit-modal').style.display = 'block';
        }

        function closeModal() {
            document.getElementById('edit-modal').style.display = 'none';
        }

        async function saveDevice() {
            const name = document.getElementById('edit_name').value.trim();
            const obj = document.getElementById('edit_object').value.trim();
            const prop = document.getElementById('edit_property').value.trim();

            if (!name || !obj || !prop) {
                showMessage('Заполните все поля', true);
                return;
            }

            const res = await fetch('/api/device/edit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    old_category: currentEdit.category,
                    old_name: currentEdit.name,
                    new_category: document.getElementById('edit_category').value,
                    new_name: name,
                    object: obj,
                    property: prop
                })
            });

            if (res.ok) {
                showMessage('Устройство обновлено');
                closeModal();
                refreshData();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка', true);
            }
        }

        async function exportAliases() {
            const a = document.createElement('a');
            a.href = '/api/export';
            a.download = 'device_aliases.json';
            a.click();
        }

        async function importAliases(file) {
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/api/import', { method: 'POST', body: formData });
            if (res.ok) {
                showMessage('Алиасы импортированы');
                refreshData();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка импорта', true);
            }
        }

        function showUpdateTab() {
            // Просто вызов функции проверки, можно расширить
            checkUpdate();
        }

        // --- Обновление системы ---
        async function applyUpdate() {
            if (!confirm('Обновить систему? Сервисы будут перезапущены.')) return;
            const res = await fetch('/update/apply', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                alert('Система обновлена! Страница перезагрузится.');
                location.reload();
            } else {
                alert('Ошибка: ' + (data.error || 'неизвестная'));
            }
        }

        // --- Загрузка при открытии ---
        refreshData();

    </script>
</body>
</html>"""

LOGS_HTML_TEMPLATE = """<!DOCTYPE html>
<html data-theme="{{ request.cookies.get('theme', 'light') }}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Логи MajorDoMo MCP</title>
    <style>
        :root {
            --bg: #ffffff;
            --text: #333333;
            --card-bg: #ffffff;
            --border: #e0e0e0;
            --primary: #4a6fa5;
            --success: #28a745;
            --danger: #dc3545;
            --warning: #ffc107;
            --input-bg: #ffffff;
            --input-border: #ddd;
            --header-bg: #f8f9fa;
        }
        [data-theme="dark"] {
            --bg: #121212;
            --text: #e0e0e0;
            --card-bg: #1e1e1e;
            --border: #444444;
            --primary: #66aaff;
            --success: #4caf50;
            --danger: #f44336;
            --warning: #ff9800;
            --input-bg: #2d2d2d;
            --input-border: #555555;
            --header-bg: #2b2b2b;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
            transition: background-color 0.3s, color 0.3s;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            background-color: var(--header-bg);
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        h1 {
            margin: 0;
            color: var(--primary);
        }
        .back-link {
            color: var(--primary);
            text-decoration: underline;
        }
        .theme-toggle {
            background: none;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 12px;
            border-radius: 4px;
            cursor: pointer;
        }
        #log-search {
            width: 100%;
            padding: 10px;
            margin-bottom: 16px;
            border: 1px solid var(--input-border);
            border-radius: 4px;
            background-color: var(--input-bg);
            color: var(--text);
        }
        #log-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .log-entry {
            padding: 10px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background-color: var(--bg);
            font-family: monospace;
            font-size: 0.9em;
        }
        .log-success { border-left: 4px solid var(--success); }
        .log-error { border-left: 4px solid var(--danger); }
        .no-results {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        [data-theme="dark"] .no-results {
            color: #aaa;
        }
        .export-csv {
            display: inline-block;
            margin-top: 16px;
            padding: 8px 16px;
            background: var(--primary);
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Логи MajorDoMo MCP</h1>
            <a href="/" class="back-link">← Назад</a>
            <button class="theme-toggle" onclick="toggleTheme()">Тема</button>
        </header>

        <input type="text" id="log-search" placeholder="Поиск по логам..." onkeyup="loadLogs(this.value)">

        <a id="export-link" class="export-csv" href="/logs/export">📤 Экспорт в CSV</a>

        <div id="log-list"><!-- Логи будут загружены сюда --></div>
    </div>

    <script>
        let currentQuery = '';
        let autoRefreshInterval = null;

        // === Функция загрузки логов ===
        async function loadLogs(query = '') {
            currentQuery = query;
            try {
                const res = await fetch(`/logs/api?query=${encodeURIComponent(query)}`);
                const logs = await res.json();
                const list = document.getElementById('log-list');

                if (logs.length === 0) {
                    list.innerHTML = '<div class="no-results">Ничего не найдено</div>';
                } else {
                    list.innerHTML = logs.map(entry => `
                        <div class="log-entry ${entry.success ? 'log-success' : 'log-error'}">
                            [${entry.timestamp}] ${entry.source} - ${entry.action} on ${entry.target} by ${entry.user} - ${JSON.stringify(entry.details)}
                        </div>
                    `).join('');
                }
            } catch (e) {
                console.error('Ошибка загрузки логов:', e);
                document.getElementById('log-list').innerHTML = '<div class="no-results">Ошибка загрузки</div>';
            }
        }

        // === Автообновление ===
        function toggleAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
                document.getElementById('auto-refresh-btn').textContent = '🔄 Вкл. автообновление';
            } else {
                autoRefreshInterval = setInterval(() => loadLogs(currentQuery), 5000);
                document.getElementById('auto-refresh-btn').textContent = '🔄 Выкл. автообновление';
            }
        }

        // === Тема ===
        function toggleTheme() {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            const next = current === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        }

        // Загрузка при открытии
        document.addEventListener('DOMContentLoaded', () => {
            const saved = localStorage.getItem('theme') || 'light';
            document.documentElement.setAttribute('data-theme', saved);
            loadLogs();
        });

    </script>
</body>
</html>"""

@app.route("/")
@requires_auth
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    print(f"Веб-панель запущена. Логин: {WEB_PANEL_USER}, Пароль: {WEB_PANEL_PASS}")
    app.run(host="0.0.0.0", port=5000, debug=False)
