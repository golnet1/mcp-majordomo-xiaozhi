#!/usr/bin/env python3
"""
Веб-панель для редактирования device_aliases.json
С поддержкой редактирования устройств, множественных алиасов, поиска по логам
и автоматической проверки обновлений из GitHub.
"""

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
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# === Вспомогательные функции ===
def check_auth(username, password):
    return username == WEB_PANEL_USER and password == WEB_PANEL_PASS

def authenticate():
    return Response(
        'Требуется авторизация', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def load_aliases():
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
                            "category": category,
                            "original_key": key
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
        print(f"LOG ERROR: {e}", file=sys.stderr)

def load_logs(limit=100, query=None):
    logs = []
    try:
        if not os.path.exists(LOG_FILE):
            return logs
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines):
            if len(logs) >= limit:
                break
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if query:
                    search_text = query.lower()
                    found = (
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
    except Exception as e:
        print(f"LOG LOAD ERROR: {e}", file=sys.stderr)
    return logs

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
        safe_files = [
            "mcp_pipe.py", "web_panel.py", "mcp-majordomo-xiaozhi.py", "scheduler.py", 
            "check_update.py", "telegram_bot.py", "action_logger.py", "log_rotator.py", "VERSION"
        ]
        
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

# === Шаблоны ===
HTML_TEMPLATE = """
<!DOCTYPE html>
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
            --border: #333333;
            --primary: #64b5f6;
            --success: #81c784;
            --danger: #e57373;
            --warning: #ffb74d;
            --input-bg: #2d2d2d;
            --input-border: #444;
            --header-bg: #1a1a1a;
        }
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 16px;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.6;
            transition: background-color 0.3s, color 0.3s;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }
        h1 {
            color: var(--primary);
            margin: 0;
            font-size: 1.8rem;
        }
        #theme-toggle {
            background: var(--card-bg);
            border: 1px solid var(--border);
            width: 40px;
            height: 40px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        #status {
            text-align: center;
            margin: 16px 0;
            min-height: 24px;
        }
        .success { color: var(--success); font-weight: bold; }
        .error { color: var(--danger); font-weight: bold; }
        .add-category, .category {
            background: var(--card-bg);
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 24px;
            overflow: hidden;
        }
        .add-category input {
            width: 100%;
            padding: 10px;
            margin: 8px 0;
            border: 1px solid var(--input-border);
            border-radius: 4px;
            font-size: 1rem;
            background: var(--input-bg);
            color: var(--text);
        }
        .add-category button {
            background: var(--primary);
            color: white;
            border: none;
            padding: 10px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1rem;
            width: 100%;
        }
        .category-header {
            padding: 16px;
            background: var(--primary);
            color: white;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .category-header h2 {
            margin: 0;
            font-size: 1.4rem;
        }
        .delete-category {
            background: var(--danger);
            color: white;
            border: none;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 16px;
        }
        .add-device {
            padding: 16px;
            border-top: 1px solid var(--border);
        }
        .device-fields {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .device-fields input {
            width: 100%;
            padding: 10px;
            border: 1px solid var(--input-border);
            border-radius: 4px;
            font-size: 1rem;
            background: var(--input-bg);
            color: var(--text);
        }
        .add-device-btn {
            background: var(--success);
            color: white;
            border: none;
            padding: 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1rem;
            width: 100%;
            margin-top: 8px;
        }
        .device {
            padding: 16px;
            border-bottom: 1px solid var(--border);
        }
        .device:last-child {
            border-bottom: none;
        }
        .device-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .device-name {
            font-weight: bold;
            font-size: 1.1rem;
        }
        .device-actions button {
            margin-left: 6px;
            padding: 4px 8px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
        .edit-btn { background: var(--warning); color: #000; }
        .delete-btn { background: var(--danger); color: white; }
        .device-details {
            font-size: 0.9rem;
            color: #888;
        }
        @media (min-width: 600px) {
            .device-fields {
                flex-direction: row;
                gap: 8px;
            }
            .device-fields input {
                flex: 1;
            }
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
            margin: 10% auto;
            padding: 20px;
            border-radius: 8px;
            width: 90%;
            max-width: 500px;
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .close {
            color: var(--text);
            font-size: 24px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover { color: var(--danger); }
        .form-group {
            margin-bottom: 12px;
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
            background: var(--input-bg);
            color: var(--text);
        }
        .modal-footer {
            text-align: right;
            margin-top: 16px;
        }
        .modal-footer button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1rem;
        }
        .save-btn { background: var(--success); color: white; }
        .cancel-btn { background: var(--danger); color: white; margin-left: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <div id="update-notification">
            Доступна новая версия! <button onclick="applyUpdate()" style="margin-left:10px;">Обновить</button>
        </div>
        
        <header>
            <h1>Редактор алиасов MajorDoMo</h1>
            <button id="theme-toggle" onclick="toggleTheme()">🌓</button>
        </header>
        
        <div class="export-import">
            <button class="export-btn" onclick="exportAliases()">📤 Экспорт JSON</button>
            <button class="import-btn" onclick="document.getElementById('import-file').click()">📥 Импорт JSON</button>
            <input type="file" id="import-file" accept=".json" style="display:none;" onchange="importAliases(this.files[0])">
        </div>

        <div id="status"></div>

        <div class="add-category">
            <input type="text" id="new_category" placeholder="Название категории (например, освещение)">
            <button onclick="addCategory()">Добавить категорию</button>
        </div>

        {% for category, devices in aliases.items() %}
        <div class="category">
            <div class="category-header">
                <h2>{{ category }}</h2>
                <button class="delete-category" onclick="deleteCategory('{{ category }}')">🗑️</button>
            </div>
            
            <div class="add-device">
                <div class="device-fields">
                    <input type="text" id="device_name_{{ loop.index }}" placeholder="Имя (например, улица)">
                    <input type="text" id="object_{{ loop.index }}" placeholder="Объект (Relay01)">
                    <input type="text" id="property_{{ loop.index }}" placeholder="Свойство (status)">
                </div>
                <button class="add-device-btn" onclick="addDevice('{{ category }}', {{ loop.index }})">Добавить устройство</button>
            </div>

            {% for alias_name, device_spec in devices.items() %}
            <div class="device">
                <div class="device-header">
                    <div class="device-name">{{ alias_name }}</div>
                    <div class="device-actions">
                        <button class="edit-btn" onclick="editDevice('{{ category }}', '{{ alias_name|e }}', '{{ device_spec.object|e }}', '{{ device_spec.property|e }}')">✏️</button>
                        <button class="delete-btn" onclick="deleteDevice('{{ category }}', '{{ alias_name|e }}')">🗑️</button>
                    </div>
                </div>
                <div class="device-details">
                    Объект: {{ device_spec.object }}<br>
                    Свойство: {{ device_spec.property }}
                </div>
            </div>
            {% endfor %}
        </div>
        {% endfor %}
    </div>

    <!-- Модальное окно редактирования -->
    <div id="editModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>Редактировать устройство</h2>
                <span class="close" onclick="closeModal()">&times;</span>
            </div>
            <div class="form-group">
                <label>Категория</label>
                <input type="text" id="edit_category" readonly>
            </div>
            <div class="form-group">
                <label>Имя устройства</label>
                <input type="text" id="edit_name">
            </div>
            <div class="form-group">
                <label>Объект</label>
                <input type="text" id="edit_object">
            </div>
            <div class="form-group">
                <label>Свойство</label>
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
            fetch('/update/status')
                .then(res => res.json())
                .then(data => {
                    if (data.update_available) {
                        document.getElementById('update-notification').style.display = 'block';
                    }
                })
                .catch(err => console.log('Ошибка загрузки статуса обновления:', err));
            
            const saved = localStorage.getItem('theme') || 'light';
            document.documentElement.setAttribute('data-theme', saved);
        });

        function toggleTheme() {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            const next = current === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        }

        function showMessage(text, isError=false) {
            const status = document.getElementById('status');
            status.innerHTML = `<div class="${isError ? 'error' : 'success'}">${text}</div>`;
            setTimeout(() => status.innerHTML = '', 3000);
        }

        // === Обновление системы ===
        async function applyUpdate() {
            if (!confirm('Обновить систему? Сервисы будут перезапущены.')) return;
            const res = await fetch('/update/apply', {method: 'POST'});
            const data = await res.json();
            if (data.success) {
                alert('Система обновлена! Страница перезагрузится.');
                location.reload();
            } else {
                alert('Ошибка: ' + (data.error || 'неизвестная'));
            }
        }

        // === Редактирование устройства ===
        let currentEdit = { category: '', name: '' };

        function editDevice(category, name, object, property) {
            currentEdit = { category, name };
            document.getElementById('edit_category').value = category;
            document.getElementById('edit_name').value = name;
            document.getElementById('edit_object').value = object;
            document.getElementById('edit_property').value = property;
            document.getElementById('editModal').style.display = 'block';
        }

        function closeModal() {
            document.getElementById('editModal').style.display = 'none';
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
                headers: {'Content-Type': 'application/json'},
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
                location.reload();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка', true);
            }
        }

        window.onclick = function(event) {
            const modal = document.getElementById('editModal');
            if (event.target == modal) {
                closeModal();
            }
        };

        async function exportAliases() {
            const res = await fetch('/api/export');
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'device_aliases.json';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }

        async function importAliases(file) {
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/api/import', { method: 'POST', body: formData });
            if (res.ok) {
                showMessage('Алиасы импортированы');
                location.reload();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка импорта', true);
            }
        }

        async function addCategory() {
            const name = document.getElementById('new_category').value.trim();
            if (!name) return;
            const res = await fetch('/api/category', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name})
            });
            if (res.ok) {
                showMessage('Категория добавлена');
                location.reload();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка', true);
            }
        }

        async function deleteCategory(name) {
            if (!confirm('Удалить категорию и все устройства?')) return;
            const res = await fetch(`/api/category/${encodeURIComponent(name)}`, {method: 'DELETE'});
            if (res.ok) {
                showMessage('Категория удалена');
                location.reload();
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
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({category, name, object: obj, property: prop})
            });
            if (res.ok) {
                showMessage('Устройство добавлено');
                location.reload();
            } else {
                const err = await res.json();
                showMessage(err.error || 'Ошибка', true);
            }
        }

        async function deleteDevice(category, name) {
            if (!confirm('Удалить устройство?')) return;
            const res = await fetch(`/api/device?category=${encodeURIComponent(category)}&name=${encodeURIComponent(name)}`, {method: 'DELETE'});
            if (res.ok) {
                showMessage('Устройство удалено');
                location.reload();
            } else {
                showMessage('Ошибка удаления', true);
            }
        }
    </script>
</body>
</html>
"""

LOGS_TEMPLATE = """
<!DOCTYPE html>
<html data-theme="{{ request.cookies.get('theme', 'light') }}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Логи действий</title>
    <style>
        :root {
            --bg: #ffffff;
            --text: #333333;
            --card-bg: #ffffff;
            --border: #e0e0e0;
            --primary: #4a6fa5;
            --success: #28a745;
            --danger: #dc3545;
        }
        [data-theme="dark"] {
            --bg: #121212;
            --text: #e0e0e0;
            --card-bg: #1e1e1e;
            --border: #333333;
            --primary: #64b5f6;
            --success: #81c784;
            --danger: #e57373;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 16px;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }
        h1 {
            color: var(--primary);
            margin: 0;
        }
        .search-box {
            display: flex;
            margin-bottom: 16px;
            gap: 8px;
        }
        .search-box input {
            flex: 1;
            padding: 8px 12px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background: var(--card-bg);
            color: var(--text);
        }
        .search-box button {
            padding: 8px 16px;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .log-entry {
            padding: 12px;
            border-bottom: 1px solid var(--border);
            font-family: monospace;
            font-size: 0.9rem;
        }
        .log-success { color: var(--success); }
        .log-error { color: var(--danger); }
        .export-csv {
            display: inline-block;
            padding: 8px 16px;
            background: var(--success);
            color: white;
            text-decoration: none;
            border-radius: 4px;
            margin-bottom: 16px;
        }
        #log-list {
            min-height: 200px;
        }
        .no-results {
            text-align: center;
            color: #888;
            padding: 20px;
        }
        #refresh-btn {
            margin-left: 10px;
            padding: 4px 8px;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        #auto-refresh {
            margin-left: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Логи действий</h1>
            <a href="/" style="color:var(--primary); text-decoration:underline;">← Назад</a>
        </header>
        
        <div class="search-box">
            <input type="text" id="search-input" placeholder="Поиск по логам (источник, пользователь, действие, цель...)">
            <button onclick="searchLogs()">Найти</button>
            <button id="refresh-btn" onclick="loadLogs(currentQuery)">🔄</button>
            <label id="auto-refresh">
                <input type="checkbox" id="auto-refresh-checkbox" onchange="toggleAutoRefresh()"> Автообновление
            </label>
        </div>
        
        <a id="export-link" class="export-csv" href="/logs/export">📤 Экспорт в CSV</a>
        
        <div id="log-list">
            <!-- Логи будут загружены сюда -->
        </div>
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
                        <div class="log-entry">
                            <span style="color:#888;">${entry.timestamp.substring(0, 19)}</span>
                            [${entry.source}] 
                            <b>${entry.user}</b> → 
                            ${entry.action}(${entry.target})
                            ${entry.success ? '<span class="log-success">✓</span>' : '<span class="log-error">✗</span>'}
                            ${entry.details ? `<br><small>${JSON.stringify(entry.details)}</small>` : ''}
                        </div>
                    `).join('');
                }
                
                document.getElementById('export-link').href = `/logs/export?query=${encodeURIComponent(query)}`;
            } catch (err) {
                console.error('Ошибка загрузки логов:', err);
            }
        }

        function searchLogs() {
            const query = document.getElementById('search-input').value.trim();
            loadLogs(query);
        }

        function toggleAutoRefresh() {
            const checkbox = document.getElementById('auto-refresh-checkbox');
            if (checkbox.checked) {
                autoRefreshInterval = setInterval(() => {
                    loadLogs(currentQuery);
                }, 3000); // 3 секунды
            } else {
                if (autoRefreshInterval) {
                    clearInterval(autoRefreshInterval);
                }
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            loadLogs();
            document.getElementById('search-input').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') searchLogs();
            });
        });
    </script>
</body>
</html>
"""

# === МАРШРУТЫ ===

@app.route("/")
@requires_auth
def index():
    try:
        flat_aliases = load_aliases()
        categories = {}
        for alias_name, specs in flat_aliases.items():
            for spec in specs:
                cat = spec["category"]
                if cat not in categories:
                    categories[cat] = {}
                key = alias_name
                counter = 1
                while key in categories[cat]:
                    key = f"{alias_name}_{counter}"
                    counter += 1
                categories[cat][key] = spec
        return render_template_string(HTML_TEMPLATE, aliases=categories)
    except Exception as e:
        print(f"Ошибка в index(): {e}", file=sys.stderr)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route("/logs")
@requires_auth
def view_logs():
    return render_template_string(LOGS_TEMPLATE)

@app.route("/logs/api")
@requires_auth
def api_logs():
    query = request.args.get("query", "").strip()
    logs = load_logs(limit=100, query=query)
    return jsonify(logs)

@app.route("/logs/export")
@requires_auth
def export_logs_csv():
    import csv
    from io import StringIO
    
    query = request.args.get("query", "").strip()
    logs = load_logs(limit=10000, query=query)
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Время", "Источник", "Пользователь", "Действие", "Цель", "Успешно", "Детали"])
    
    for record in logs:
        writer.writerow([
            record.get("timestamp", "")[:19],
            record.get("source", ""),
            record.get("user", ""),
            record.get("action", ""),
            record.get("target", ""),
            "Да" if record.get("success") else "Нет",
            json.dumps(record.get("details", {}), ensure_ascii=False)
        ])
    
    output.seek(0)
    filename = "actions_filtered.csv" if query else "actions.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

@app.route("/api/export")
@requires_auth
def export_aliases():
    if not os.path.exists(ALIASES_FILE):
        return jsonify({"error": "Файл не найден"}), 404
    with open(ALIASES_FILE, "r", encoding="utf-8") as f:
        data = f.read()
    return Response(
        data,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=device_aliases.json"}
    )

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
        save_aliases(data)
        log_action(
            source="web",
            user=request.authorization.username,
            action="import_aliases",
            target="device_aliases.json",
            success=True,
            details={"file_size": len(json.dumps(data))}
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Ошибка парсинга: {str(e)}"}), 400

@app.route("/api/category", methods=["POST"])
@requires_auth
def add_category():
    data = request.json
    name = data.get("name")
    if not name:
        return jsonify({"error": "Имя категории обязательно"}), 400
    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    if name in raw:
        return jsonify({"error": "Категория уже существует"}), 400
    raw[name] = {}
    save_aliases(raw)
    log_action(
        source="web",
        user=request.authorization.username,
        action="add_category",
        target=name,
        success=True
    )
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
    del raw[name]
    save_aliases(raw)
    log_action(
        source="web",
        user=request.authorization.username,
        action="delete_category",
        target=name,
        success=True
    )
    return jsonify({"success": True})

@app.route("/api/device", methods=["POST"])
@requires_auth
def add_device():
    data = request.json
    category = data.get("category")
    name = data.get("name")
    obj = data.get("object")
    prop = data.get("property")
    if not all([category, name, obj, prop]):
        return jsonify({"error": "Все поля обязательны"}), 400

    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

    if category not in raw:
        raw[category] = {}

    # === НОВОЕ: Проверяем, есть ли уже такой object + property в категории ===
    existing_key = None
    for key, spec in raw[category].items():
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
        raw[category][new_key] = {"object": obj, "property": prop}
        del raw[category][existing_key]
    else:
        # === Создаём новую запись ===
        raw[category][name] = {"object": obj, "property": prop}

    save_aliases(raw)
    log_action(
        source="web",
        user=request.authorization.username,
        action="add_device",
        target=f"{category}/{name}",
        success=True
    )
    return jsonify({"success": True})

@app.route("/api/device", methods=["DELETE"])
@requires_auth
def delete_device():
    category = request.args.get("category")
    name = request.args.get("name")
    if not category or not name:
        return jsonify({"error": "Параметры category и name обязательны"}), 400

    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

    if category not in raw:
        return jsonify({"error": "Категория не найдена"}), 404

    # === НОВОЕ: Ищем ключ, содержащий имя ===
    target_key = None
    for key in raw[category].keys():
        names = [n.strip() for n in key.split(",")]
        if name in names:
            target_key = key
            break

    if not target_key:
        return jsonify({"error": "Устройство не найдено"}), 404

    # === Удаляем имя из ключа ===
    names = [n.strip() for n in target_key.split(",")]
    names.remove(name)

    # === Удаляем старую запись ===
    old_spec = raw[category].pop(target_key)

    if names:
        # === Если остались имена, создаём новый ключ ===
        new_key = ",".join(names)
        raw[category][new_key] = old_spec

    save_aliases(raw)
    log_action(
        source="web",
        user=request.authorization.username,
        action="delete_device",
        target=f"{category}/{name}",
        success=True
    )
    return jsonify({"success": True})
    
@app.route("/api/device/edit", methods=["POST"])
@requires_auth
def edit_device():
    data = request.json
    old_category = data.get("old_category")
    old_name = data.get("old_name")
    new_category = data.get("new_category")
    new_name = data.get("new_name")
    obj = data.get("object")
    prop = data.get("property")

    if not all([old_category, old_name, new_category, new_name, obj, prop]):
        return jsonify({"error": "Все поля обязательны"}), 400

    raw = {}
    if os.path.exists(ALIASES_FILE):
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

    if old_category not in raw:
        return jsonify({"error": "Исходная категория не найдена"}), 404

    # === НОВОЕ: Найти ключ, содержащий old_name ===
    old_key = None
    for key in raw[old_category].keys():
        names = [n.strip() for n in key.split(",")]
        if old_name in names:
            old_key = key
            break

    if not old_key:
        return jsonify({"error": "Исходное устройство не найдено"}), 404

    # === Удаляем old_name из старого ключа ===
    old_names = [n.strip() for n in old_key.split(",")]
    old_names.remove(old_name)

    # === Удаляем старую запись ===
    old_spec = raw[old_category].pop(old_key)

    if old_names:
        # === Если остались имена, создаём новый ключ ===
        remaining_key = ",".join(old_names)
        raw[old_category][remaining_key] = old_spec

    # === Ищем, есть ли уже такой object + property в new_category ===
    existing_key = None
    if new_category in raw:
        for key, spec in raw[new_category].items():
            if spec["object"] == obj and spec["property"] == prop:
                existing_key = key
                break

    if existing_key and new_category == old_category:
        # === Объединяем имена ===
        names = [n.strip() for n in existing_key.split(",")]
        if new_name not in names:
            names.append(new_name)
        new_key = ",".join(names)
        raw[new_category][new_key] = {"object": obj, "property": prop}
        # Удаляем старый ключ, если он отличается
        if existing_key != new_key:
            del raw[new_category][existing_key]
    elif existing_key and new_category != old_category:
        # === Объединяем в новой категории ===
        names = [n.strip() for n in existing_key.split(",")]
        if new_name not in names:
            names.append(new_name)
        new_key = ",".join(names)
        raw[new_category][new_key] = {"object": obj, "property": prop}
        # Удаляем старый ключ, если он отличается
        if existing_key != new_key:
            del raw[new_category][existing_key]
    else:
        # === Создаём новую запись ===
        raw[new_category][new_name] = {"object": obj, "property": prop}

    save_aliases(raw)
    log_action(
        source="web",
        user=request.authorization.username,
        action="edit_device",
        target=f"{old_category}/{old_name} → {new_category}/{new_name}",
        success=True,
        details={"object": obj, "property": prop}
    )
    return jsonify({"success": True})

# === МАРШРУТЫ ОБНОВЛЕНИЯ ===

@app.route("/update/status")
@requires_auth
def update_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            return jsonify(json.load(f))
    return jsonify({"update_available": False})

@app.route("/update/apply", methods=["POST"])
@requires_auth
def apply_update():
    success = update_from_github()
    if success:
        # Сбрасываем статус после обновления
        if os.path.exists(STATUS_FILE):
            os.remove(STATUS_FILE)
        return jsonify({"success": True, "message": "Система обновлена и перезапущена"})
    else:
        return jsonify({"error": "Ошибка при обновлении"}), 500

if __name__ == "__main__":
    print(f"Веб-панель запущена. Логин: {WEB_PANEL_USER}, Пароль: {WEB_PANEL_PASS}")
    app.run(host="0.0.0.0", port=5000, debug=False)