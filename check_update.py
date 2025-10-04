#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime, timedelta

GITHUB_REPO = "golnet1/mcp-majordomo-xiaozhi"  # ← РЕПОЗИТОРИЙ
VERSION_FILE = "/opt/mcp-bridge/VERSION"
STATUS_FILE = "/opt/mcp-bridge/update_status.json"

def get_current_version():
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, "r") as f:
            return f.read().strip()
    return "unknown"

def get_latest_version():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data["tag_name"]
    except Exception as e:
        print(f"Ошибка проверки обновления: {e}")
        return None

def save_status(current, latest):
    status = {
        "current_version": current,
        "latest_version": latest,
        "update_available": latest != current,
        "last_check": datetime.utcnow().isoformat() + "Z"
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)

if __name__ == "__main__":
    current = get_current_version()
    latest = get_latest_version()
    if latest:
        save_status(current, latest)
        if latest != current:
            print(f"Доступно обновление: {current} → {latest}")
        else:
            print("Установлена актуальная версия")
    else:
        print("Не удалось проверить обновления")