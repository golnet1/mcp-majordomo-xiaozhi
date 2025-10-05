#!/usr/bin/env python3
"""
Единый логгер с уведомлениями об ошибках в Telegram.
"""

import json
import os
import sys
from datetime import datetime

LOG_FILE = "/opt/mcp-bridge/logs/actions.log"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Настройки Telegram для уведомлений
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_error(message: str):
    """Отправляет сообщение об ошибке в Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🚨 Ошибка в системе умного дома:\n{message}",
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Не удалось отправить в Telegram: {e}", file=sys.stderr)

def log_action(
    source: str,
    action: str,
    target: str,
    success: bool = True,
    user: str = "system",
    details: dict = None
):
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": source,
        "user": user,
        "action": action,
        "target": target,
        "success": success,
        "details": details or {}
    }
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
        # Отправляем уведомление при критической ошибке
        if not success and source in ("mcp", "scheduler"):
            error_msg = f"<b>{source.upper()}</b>\nДействие: {action}\nЦель: {target}\nДетали: {json.dumps(details, ensure_ascii=False)}"
            send_telegram_error(error_msg)
            
    except Exception as e:
        print(f"LOG ERROR: {e}", file=sys.stderr)