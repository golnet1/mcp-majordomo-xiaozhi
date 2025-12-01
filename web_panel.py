#!/usr/bin/env python3
"""
Веб-панель для редактирования device_aliases.json
Поддерживает новую структуру:
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
    return Response('Требуется авторизация', 401,
                    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# === Загрузка алиасов (оригинальная структура) ===
def load_aliases():
    """
    Загружает оригинальную структуру из файла:
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
    """
    if not os.path.exists(ALIASES_FILE):
        return {}
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw
    except Exception as e:
        print(f"Ошибка загрузки алиасов: {e}", file=sys.stderr)
        return {}

# === Сохранение алиасов (оригинальная структура) ===
def save_aliases(data):
    """
    Сохраняет оригинальную структуру в файл.
    """
    backup = ALIASES_FILE + ".bak"
    if os.path.exists(ALIASES_FILE):
        os.replace(ALIASES_FILE, backup)

    try:
        with open(ALIASES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Ошибка сохранения алиасов: {e}", file=sys.stderr)
        # Восстановить из бекапа в случае ошибки
        if os.path.exists(backup):
            os.replace(backup, ALIASES_FILE)
        return False


def log_action(source, action, target, success=True, user="web", details=None):
    try:
        from action_logger import log_action as logger
        logger(source=source, user=user, action=action, target=target, success=success, details=details)
    except ImportError:
        print(f"Log: {source} - {user} - {action} - {target} - {success} - {details}", file=sys.stderr)

def load_logs(limit=100, query=""):
    if not os.path.exists(LOG_FILE):
        return []
    try:
        logs = []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if query.lower() in json.dumps(entry, ensure_ascii=False).lower():
                        logs.append(entry)
                except json.JSONDecodeError:
                    continue

        # Сортируем по timestamp от новых к старым (предполагаем ISO 8601 формат)
        # и возвращаем только нужное количество (limit) с начала списка (самые новые)
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return logs[:limit]

    except Exception as e:
        print(f"Ошибка чтения логов: {e}", file=sys.stderr)
        return []

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
        url = f"https://api.github.com/repos/{GITHUB_REPO}/zipball/main"
        # Скачиваем
        zip_path = "/tmp/mcp_update.zip"
        urllib.request.urlretrieve(url, zip_path)

        # Распаковываем
        extract_dir = "/tmp/mcp_update/"
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Находим папку с содержимым (обычно первая папка в архиве)
        extracted_folder = os.path.join(extract_dir, os.listdir(extract_dir)[0])

        # Определяем файлы, которые нужно обновить
        files_to_update = [
            "mcp_pipe.py",
            "mcp-majordomo-xiaozhi.py",
            "web_panel.py",
            "scheduler.py",
            "telegram_bot.py",
            "action_logger.py",
            "log_rotator.py",
            "check_update.py",
            "install_mcp_majordomo.sh",
            "VERSION"
        ]

        updated_any = False
        for file in files_to_update:
            src_file = os.path.join(extracted_folder, file)
            dst_file = f"/opt/mcp-bridge/{file}"
            if os.path.exists(src_file):
                shutil.copy2(src_file, dst_file)
                print(f"Обновлён файл: {file}", file=sys.stderr)
                updated_any = True

        try:
            # Удаляем файл, если он существует
            if os.path.isfile(zip_path):
                os.remove(zip_path)
                print(f"Файл {zip_path} удалён.")
            else:
                print(f"Файл {zip_path} не найден.")

            # Удаляем папку и всё её содержимое, если она существует
            if os.path.isdir(extract_dir):
                shutil.rmtree(extract_dir)
                print(f"Папка {extract_dir} и её содержимое удалены.")
            else:
                print(f"Папка {extract_dir} не найдена.")

        except OSError as e:
            print(f"Ошибка при удалении файлов: {e}")

        if not updated_any:
            raise Exception("Ни один файл не был обновлён")

        # Перезапускаем сервисы
        subprocess.run(["sudo", "systemctl", "restart", "mcp-majordomo", "mcp-web-panel", "mcp-scheduler", "mcp-telegram-bot", "mcp-log-rotate"], check=True)
        return True
    except Exception as e:
        print(f"Ошибка обновления: {e}", file=sys.stderr)
        return False

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
            --input-bg: #f5f5f5;
            --success: #28a745;
            --warning: #ffc107;
            --danger: #dc3545;
            --primary: #007bff;
        }
        [data-theme="dark"] {
            --bg: #121212;
            --text: #e0e0e0;
            --card-bg: #1e1e1e;
            --border: #333333;
            --input-bg: #2c2c2c;
        }
        body {
            font-family: Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 16px;
            transition: background-color 0.3s, color 0.3s;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        h1 {
            margin: 0;
        }
        #theme-toggle {
            background: none;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 4px 8px;
            cursor: pointer;
            border-radius: 4px;
        }
        #update-notification {
            background: var(--warning);
            color: #000;
            padding: 8px;
            border-radius: 4px;
            margin-bottom: 16px;
            display: none;
            text-align: center;
        }
        .category {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .category-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .add-device {
            background: var(--input-bg);
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 16px;
        }
        .add-category {
            background: var(--input-bg);
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        @media (min-width: 600px) {
            .add-category {
                flex-direction: row;
                gap: 8px;
            }
        }
        .add-category input, .add-category select {
            padding: 8px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background: var(--input-bg);
            color: var(--text);
        }
        .add-category-btn {
            background: var(--success);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1rem;
        }
        .device-fields {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .device-fields input {
            padding: 8px;
            border: 1px solid var(--border);
            border-radius: 4px;
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
        #update-notification.show {
            display: block;
        }
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.4);
        }
        .modal-content {
            background-color: var(--card-bg);
            margin: 15% auto;
            padding: 20px;
            border: 1px solid var(--border);
            border-radius: 8px;
            width: 80%;
            max-width: 500px;
        }
        .modal-header {
            margin-bottom: 16px;
        }
        .modal-actions {
            margin-top: 16px;
            text-align: right;
        }
        .modal-actions button {
            padding: 6px 12px;
            margin-left: 8px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .save-btn { background: var(--success); color: white; }
        .cancel-btn { background: var(--danger); color: white; margin-left: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <div id="update-notification">Доступна новая версия! <button onclick="applyUpdate()" style="margin-left:10px;">Обновить</button></div>
        <header>
            <h1>Редактор алиасов MajorDoMo</h1>
            <button id="theme-toggle" onclick="toggleTheme()">🌓</button>
        </header>
        <div class="export-import">
            <button class="export-btn" onclick="exportAliases()">📤 Экспорт JSON</button>
            <button class="import-btn" onclick="document.getElementById('import-file').click()">📥 Импорт JSON</button>
            <input type="file" id="import-file" accept=".json" style="display:none;" onchange="importAliases(this.files[0])">
			<a href="/logs" class="export-btn">📋 Логи</a>
        </div>
        <div id="status"></div>
        <div class="add-category">
            <input type="text" id="new_category" placeholder="Название категории (например, свет)">
            <select id="new_category_type">
                <option value="relay">relay</option>
                <option value="sensors">sensors</option>
                <option value="device">device</option>
                <option value="media">media</option>
            </select>
            <button class="add-category-btn" onclick="addCategory()">Добавить категорию</button>
        </div>
        {% for category, details in aliases.items() %}
        <div class="category">
            <div class="category-header">
                <h2>{{ category }} (тип: {{ details.type }})</h2>
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
            {% for device_key, device_spec in details.devices.items() %}
            <div class="device">
                <div class="device-header">
                    <div class="device-name">{{ device_key }}</div>
                    <div class="device-actions">
                        <button class="edit-btn" onclick="editDevice('{{ category }}', '{{ device_key|e }}', '{{ device_spec.object|e }}', '{{ device_spec.property|e }}')">✏️</button>
                        <button class="delete-btn" onclick="deleteDevice('{{ category }}', '{{ device_key|e }}')">🗑️</button>
                    </div>
                </div>
                <div class="device-details">Объект: {{ device_spec.object }}<br>Свойство: {{ device_spec.property }}</div>
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
            </div>
            <div>
                <input type="text" id="edit_category" placeholder="Категория" readonly style="width:100%; margin-bottom:8px;">
                <input type="text" id="edit_name" placeholder="Имя (через запятую)" style="width:100%; margin-bottom:8px;">
                <input type="text" id="edit_object" placeholder="Объект" style="width:100%; margin-bottom:8px;">
                <input type="text" id="edit_property" placeholder="Свойство" style="width:100%; margin-bottom:8px;">
            </div>
            <div class="modal-actions">
                <button class="save-btn" onclick="saveDevice()">Сохранить</button>
                <button class="cancel-btn" onclick="closeModal()">Отмена</button>
            </div>
        </div>
    </div>

    <script>
        let currentEdit = { category: '', name: '' };

        function showMessage(msg, isError = false) {
            const status = document.getElementById('status');
            status.innerHTML = `<div style="padding: 8px; margin: 8px 0; border-radius: 4px; background: ${isError ? '#f8d7da' : '#d4edda'}; color: ${isError ? '#721c24' : '#155724'};">${msg}</div>`;
        }

        function toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            document.cookie = `theme=${newTheme}; path=/; max-age=31536000`; // 1 year
        }

        // Загрузка темы из cookie при запуске
        document.addEventListener('DOMContentLoaded', () => {
            const savedTheme = document.cookie.replace(/(?:(?:^|.*;\s*)theme\s*\=\s*([^;]*).*$)|^.*$/, "$1");
            if (savedTheme) {
                document.documentElement.setAttribute('data-theme', savedTheme);
            }
        });

        async function checkForUpdate() {
            try {
                const resp = await fetch('/update/status');
                const data = await resp.json();
                if (data.update_available) {
                    document.getElementById('update-notification').classList.add('show');
                }
            } catch (err) {
                console.error('Ошибка проверки обновления:', err);
            }
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
            const type = document.getElementById('new_category_type').value.trim();
            if (!name) return;

            const res = await fetch('/api/category', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, type: type }) // Передаём выбранный тип
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
            if (!confirm('Удалить категорию и все её устройства?')) return;
            const res = await fetch(`/api/category/${encodeURIComponent(name)}`, { method: 'DELETE' });
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
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ category, name, object: obj, property: prop })
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
            const res = await fetch(`/api/device?category=${encodeURIComponent(category)}&name=${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (res.ok) {
                showMessage('Устройство удалено');
                location.reload();
            } else {
                showMessage('Ошибка удаления', true);
            }
        }

        // Проверяем обновления при загрузке
        checkForUpdate();
    </script>
</body>
</html>"""

LOGS_TEMPLATE = """<!DOCTYPE html>
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
            --input-bg: #f5f5f5;
            --success: #28a745;
            --warning: #ffc107;
            --danger: #dc3545;
            --primary: #007bff;
        }
        [data-theme="dark"] {
            --bg: #121212;
            --text: #e0e0e0;
            --card-bg: #1e1e1e;
            --border: #333333;
            --input-bg: #2c2c2c;
        }
        body {
            font-family: Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 16px;
            transition: background-color 0.3s, color 0.3s;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        h1 {
            margin: 0;
        }
        #theme-toggle {
            background: none;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 4px 8px;
            cursor: pointer;
            border-radius: 4px;
        }
        #controls-container {
            margin-bottom: 16px;
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
        }
        #search-input {
            padding: 8px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background: var(--input-bg);
            color: var(--text);
            flex-grow: 1;
            min-width: 200px;
        }
        .control-group {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        #logs {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            max-height: 60vh; /* Уменьшено для места под навигацию */
            overflow-y: auto;
        }
        .log-entry {
            padding: 8px;
            border-bottom: 1px solid var(--border);
            font-family: monospace;
            font-size: 0.9rem;
        }
        .log-success { color: var(--success); }
        .log-error { color: var(--danger); }
        .export-link {
            margin-top: 16px;
            display: inline-block;
            padding: 8px 16px;
            background: var(--primary);
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }
        .pagination {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            margin-top: 10px;
            flex-wrap: wrap;
        }
        .pagination button {
            padding: 5px 10px;
            border: 1px solid var(--border);
            background: var(--input-bg);
            color: var(--text);
            cursor: pointer;
            border-radius: 4px;
        }
        .pagination button:disabled {
            cursor: not-allowed;
            opacity: 0.5;
        }
        .pagination-info {
            white-space: nowrap; /* Не переносить текст внутри */
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Логи MajorDoMo MCP</h1>
            <a href="/" class="back-link">← Назад</a>
            <button id="theme-toggle" onclick="toggleTheme()">🌓</button>
        </header>
        <div id="controls-container">
            <input type="text" id="search-input" placeholder="Поиск в логах..." onkeyup="if(event.key === 'Enter') searchLogs()">
            <button onclick="searchLogs()">Найти</button>
            <button onclick="toggleAutoRefresh()">Автообновление: <span id="auto-refresh-status">Выкл</span></button>
            <div class="control-group">
                <label for="page-size">Строк на странице:</label>
                <select id="page-size" onchange="changePageSize()">
                    <option value="20">20</option>
                    <option value="50">50</option>
                    <option value="100" selected>100</option> <!-- По умолчанию 100 -->
                    <option value="200">200</option>
                    <option value="500">500</option>
                    <option value="1000">1000</option>
                </select>
            </div>
        </div>
        <div id="logs"></div>
        <div class="pagination">
            <button id="prev-page" onclick="prevPage()" disabled>Предыдущая</button>
            <div class="pagination-info">
                Страница <span id="current-page">1</span> из <span id="total-pages">1</span> (Всего записей: <span id="total-records">0</span>)
            </div>
            <button id="next-page" onclick="nextPage()" disabled>Следующая</button>
        </div>
        <a id="export-link" class="export-link" href="/logs/export">📥 Экспорт CSV</a>
    </div>
    <script>
        let autoRefreshInterval = null;
        let currentPage = 1;
        let currentQuery = '';
        let currentPageSize = 100; // Начальное значение
        let totalRecords = 0;
        let totalPages = 1;

        function toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            document.cookie = `theme=${newTheme}; path=/; max-age=31536000`; // 1 year
        }

        // Загрузка темы из cookie при запуске
        document.addEventListener('DOMContentLoaded', () => {
            const savedTheme = document.cookie.replace(/(?:(?:^|.*;\s*)theme\s*\=\s*([^;]*).*$)|^.*$/, "$1");
            if (savedTheme) {
                document.documentElement.setAttribute('data-theme', savedTheme);
            }
            // Загрузка начальных логов
            loadLogs();
        });

        async function loadLogs(query = '', page = 1, pageSize = 100) {
            // Сохраняем параметры для будущего использования
            currentQuery = query;
            currentPage = page;
            currentPageSize = pageSize;

            try {
                // Обновляем URL-параметры для экспорта
                const exportUrl = `/logs/export?query=${encodeURIComponent(query)}&page=${page}&page_size=${pageSize}`;
                document.getElementById('export-link').href = exportUrl;

                const response = await fetch(`/logs/api?query=${encodeURIComponent(query)}&page=${page}&page_size=${pageSize}`);
                const data = await response.json();
                
                // Предполагаем, что API возвращает объект { logs: [...], total: N }
                const logs = data.logs || data; // Совместимость, если вдруг придет только массив
                totalRecords = data.total || logs.length; // Если total нет, используем длину массива (не точно)
                totalPages = Math.ceil(totalRecords / pageSize);

                // Обновляем информацию о пагинации
                document.getElementById('current-page').textContent = page;
                document.getElementById('total-pages').textContent = totalPages;
                document.getElementById('total-records').textContent = totalRecords;

                // Включаем/выключаем кнопки
                document.getElementById('prev-page').disabled = (page <= 1);
                document.getElementById('next-page').disabled = (page >= totalPages);

                document.getElementById('logs').innerHTML = logs.map(entry => `
                    <div class="log-entry">
                        <b>${new Date(entry.timestamp).toLocaleString()}</b> |
                        <b>${entry.user}</b> → ${entry.action} (${entry.target}) ${entry.success ? '<span class="log-success">✓</span>' : '<span class="log-error">✗</span>'}
                        ${entry.details ? `<br><small>${JSON.stringify(entry.details)}</small>` : ''}
                    </div>
                `).join('');

            } catch (err) {
                console.error('Ошибка загрузки логов:', err);
                document.getElementById('logs').innerHTML = `<div class="log-entry log-error">Ошибка загрузки: ${err.message}</div>`;
                // Сбрасываем информацию о пагинации при ошибке
                document.getElementById('current-page').textContent = '1';
                document.getElementById('total-pages').textContent = '1';
                document.getElementById('total-records').textContent = '0';
                document.getElementById('prev-page').disabled = true;
                document.getElementById('next-page').disabled = true;
            }
        }

        function searchLogs() {
            const query = document.getElementById('search-input').value.trim();
            loadLogs(query, 1, currentPageSize); // Начинаем с первой страницы при новом поиске
        }

        function changePageSize() {
            const newSize = parseInt(document.getElementById('page-size').value);
            currentPageSize = newSize;
            // При смене размера страницы, возвращаемся к первой странице
            loadLogs(currentQuery, 1, currentPageSize);
        }

        function prevPage() {
            if (currentPage > 1) {
                loadLogs(currentQuery, currentPage - 1, currentPageSize);
            }
        }

        function nextPage() {
            if (currentPage < totalPages) {
                loadLogs(currentQuery, currentPage + 1, currentPageSize);
            }
        }

        function toggleAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
                document.getElementById('auto-refresh-status').textContent = 'Выкл';
            } else {
                autoRefreshInterval = setInterval(() => {
                    // При автообновлении, возможно, нужно оставаться на текущей странице
                    // и использовать текущий размер страницы.
                    // loadLogs(currentQuery, currentPage, currentPageSize);
                    // Или сбросить на первую страницу при обновлении?
                    loadLogs(currentQuery, 1, currentPageSize); // Пример: сброс на 1-ю страницу
                }, 5000); // Обновление каждые 5 секунд
                document.getElementById('auto-refresh-status').textContent = 'Вкл';
            }
        }
    </script>
</body>
</html>"""

@app.route("/")
@requires_auth
def index():
    try:
        # Загружаем оригинальную структуру
        raw_aliases = load_aliases()
        return render_template_string(HTML_TEMPLATE, aliases=raw_aliases)
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
    try:
        # Получаем номер страницы и размер страницы из параметров запроса
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 100))
        if page < 1 or page_size < 1:
            return jsonify({"error": "Номер страницы и размер должны быть положительными числами"}), 400
    except ValueError:
        return jsonify({"error": "Некорректные параметры страницы или размера"}), 400

    # Загружаем ВСЕ логи, соответствующие запросу, и сортируем их (новые сверху)
    # load_logs уже сортирует и возвращает ограниченное количество
    # Для пагинации нужно получить ВСЕ подходящие записи, отсортировать, и выбрать нужную страницу
    all_logs = load_logs(limit=10000, query=query) # Увеличиваем лимит для пагинации

    # Теперь all_logs уже отсортирован от новых к старым
    total_records = len(all_logs)

    # Вычисляем индексы для текущей страницы (в отсортированном списке)
    # Страница 1 -> индексы 0...page_size-1
    # Страница 2 -> индексы page_size...2*page_size-1
    start_index = (page - 1) * page_size
    end_index = start_index + page_size

    # Получаем только логи для текущей страницы
    logs_for_page = all_logs[start_index:end_index]

    # Возвращаем объект с массивом логов и общим количеством записей
    return jsonify({
        "logs": logs_for_page,
        "total": total_records
    })


@app.route("/logs/export")
@requires_auth
def export_logs():
    import io
    import csv
    query = request.args.get("query", "").strip()
    logs = load_logs(limit=10000, query=query) # Большой лимит для экспорта

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "source", "user", "action", "target", "success", "details"])
    for log in logs:
        writer.writerow([
            log.get("timestamp", ""),
            log.get("source", ""),
            log.get("user", ""),
            log.get("action", ""),
            log.get("target", ""),
            log.get("success", ""),
            json.dumps(log.get("details", {}), ensure_ascii=False)
        ])

    filename = "actions_filtered.csv" if query else "actions.csv"
    return Response(output.getvalue(),
                    mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={filename}"})

@app.route("/api/export")
@requires_auth
def export_aliases():
    if not os.path.exists(ALIASES_FILE):
        return jsonify({"error": "Файл не найден"}), 404

    with open(ALIASES_FILE, "r", encoding="utf-8") as f:
        data = f.read()

    return Response(data,
                    mimetype="application/json",
                    headers={"Content-Disposition": "attachment;filename=device_aliases.json"})

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
        # Проверим, соответствует ли структура новому формату
        for cat_name, cat_details in data.items():
            if not isinstance(cat_details, dict) or "type" not in cat_details or "devices" not in cat_details:
                return jsonify({"error": f"Неверный формат категории '{cat_name}'. Ожидается 'type' и 'devices'."}), 400
            if not isinstance(cat_details["devices"], dict):
                 return jsonify({"error": f"Поле 'devices' в категории '{cat_name}' должно быть словарём."}), 400
            for dev_key, dev_spec in cat_details["devices"].items():
                 if not isinstance(dev_spec, dict) or "object" not in dev_spec or "property" not in dev_spec:
                     return jsonify({"error": f"Неверный формат устройства '{dev_key}' в категории '{cat_name}'. Ожидается 'object' и 'property'."}), 400

        success = save_aliases(data) # Используем новую функцию сохранения
        if success:
            log_action(source="web",
                       user=request.authorization.username,
                       action="import_aliases",
                       target="device_aliases.json",
                       success=True,
                       details={"file_size": len(json.dumps(data))})
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Ошибка сохранения файла"}), 500
    except json.JSONDecodeError:
        return jsonify({"error": "Ошибка парсинга JSON"}), 400
    except Exception as e:
        return jsonify({"error": f"Ошибка импорта: {str(e)}"}), 500

@app.route("/api/category", methods=["POST"])
@requires_auth
def add_category():
    data = request.json
    name = data.get("name")
    device_type = data.get("type", "unknown") # Используем тип из запроса
    if not name:
        return jsonify({"error": "Имя категории обязательно"}), 400

    raw = load_aliases() # Загружаем текущую структуру

    if name in raw:
        existing_details = raw[name]
        if isinstance(existing_details, dict) and "type" in existing_details:
            return jsonify({"error": f"Категория '{name}' уже существует с типом '{existing_details['type']}'"}), 400

    # Добавляем новую категорию с выбранным типом и пустым словарём устройств
    raw[name] = {"type": device_type, "devices": {}}
    success = save_aliases(raw) # Используем новую функцию сохранения

    if success:
        log_action(source="web",
                   user=request.authorization.username,
                   action="add_category",
                   target=name,
                   success=True,
                   details={"type": device_type}) # Логируем тип
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Ошибка сохранения файла"}), 500

@app.route("/api/category/<name>", methods=["DELETE"])
@requires_auth
def delete_category(name):
    raw = load_aliases() # Загружаем текущую структуру

    if name not in raw:
        return jsonify({"error": "Категория не найдена"}), 404

    del raw[name]
    success = save_aliases(raw) # Используем новую функцию сохранения

    if success:
        log_action(source="web",
                   user=request.authorization.username,
                   action="delete_category",
                   target=name,
                   success=True)
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Ошибка сохранения файла"}), 500

@app.route("/api/device", methods=["POST"])
@requires_auth
def add_device():
    data = request.json
    category = data.get("category")
    name = data.get("name") # Это будет ключом в словаре devices
    obj = data.get("object")
    prop = data.get("property")

    if not all([category, name, obj, prop]):
        return jsonify({"error": "Все поля обязательны"}), 400

    raw = load_aliases() # Загружаем текущую структуру

    if category not in raw:
        # Создаём категорию с типом по умолчанию, если её нет
        raw[category] = {"type": "unknown", "devices": {}}

    # Проверяем, существует ли устройство с таким ключом
    if name in raw[category]["devices"]:
        return jsonify({"error": "Устройство с таким именем уже существует в категории"}), 400

    # Добавляем новое устройство под ключом 'name'
    raw[category]["devices"][name] = {"object": obj, "property": prop}

    success = save_aliases(raw) # Используем новую функцию сохранения

    if success:
        log_action(source="web",
                   user=request.authorization.username,
                   action="add_device",
                   target=f"{category}/{name}",
                   success=True)
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Ошибка сохранения файла"}), 500

@app.route("/api/device", methods=["DELETE"])
@requires_auth
def delete_device():
    category = request.args.get("category")
    name = request.args.get("name")

    if not category or not name:
        return jsonify({"error": "Параметры category и name обязательны"}), 400

    raw = load_aliases() # Загружаем текущую структуру

    if category not in raw:
        return jsonify({"error": "Категория не найдена"}), 404

    if name not in raw[category]["devices"]:
        return jsonify({"error": "Устройство не найдено"}), 404

    # Удаляем устройство по ключу 'name'
    del raw[category]["devices"][name]

    # Опционально: удалить категорию, если в ней больше нет устройств
    # if not raw[category]["devices"]:
    #     del raw[category]

    success = save_aliases(raw) # Используем новую функцию сохранения

    if success:
        log_action(source="web",
                   user=request.authorization.username,
                   action="delete_device",
                   target=f"{category}/{name}",
                   success=True)
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Ошибка сохранения файла"}), 500

@app.route("/api/device/edit", methods=["POST"])
@requires_auth
def edit_device():
    data = request.json
    old_category = data.get("old_category")
    old_name = data.get("old_name") # Старый ключ устройства
    new_category = data.get("new_category")
    new_name = data.get("new_name") # Новый ключ устройства
    obj = data.get("object")
    prop = data.get("property")

    if not all([old_category, old_name, new_category, new_name, obj, prop]):
        return jsonify({"error": "Все поля обязательны"}), 400

    raw = load_aliases() # Загружаем текущую структуру

    if old_category not in raw:
        return jsonify({"error": "Старая категория не найдена"}), 404

    if old_name not in raw[old_category]["devices"]:
        return jsonify({"error": "Старое устройство не найдено"}), 404

    # Извлекаем спецификацию старого устройства
    old_spec = raw[old_category]["devices"][old_name]

    # Если категория не меняется и имя не меняется, просто обновляем object и property
    if old_category == new_category and old_name == new_name:
        raw[old_category]["devices"][old_name] = {"object": obj, "property": prop}
    else:
        # Если меняется категория или имя
        # Удаляем старое устройство
        del raw[old_category]["devices"][old_name]

        # Если новая категория отличается, создаём её, если нужно
        if new_category not in raw:
            raw[new_category] = {"type": "unknown", "devices": {}}

        # Проверяем, существует ли уже устройство с новым именем в новой (или старой, если не менялась) категории
        if new_name in raw[new_category]["devices"]:
             # Восстанавливаем старое устройство, так как новое имя занято
             raw[old_category]["devices"][old_name] = old_spec
             return jsonify({"error": f"Устройство с именем '{new_name}' уже существует в категории '{new_category}'"}), 400

        # Добавляем устройство с новым именем
        raw[new_category]["devices"][new_name] = {"object": obj, "property": prop}

    success = save_aliases(raw) # Используем новую функцию сохранения

    if success:
        log_action(source="web",
                   user=request.authorization.username,
                   action="edit_device",
                   target=f"{old_category}/{old_name} -> {new_category}/{new_name}",
                   success=True)
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Ошибка сохранения файла"}), 500

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
    app.run(host="0.0.0.0", port=5000, debug=False)