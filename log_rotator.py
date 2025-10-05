#!/usr/bin/env python3
"""
Ротация логов: удаление записей старше N дней.
Запускать раз в день через cron или systemd timer.
"""

import os
import json
from datetime import datetime, timedelta

LOG_FILE = "/opt/mcp-bridge/logs/actions.log"
BACKUP_FILE = "/opt/mcp-bridge/logs/actions.log.bak"
DAYS_TO_KEEP = 7

def rotate_logs():
    if not os.path.exists(LOG_FILE):
        print("Лог-файл не найден")
        return

    cutoff = datetime.utcnow() - timedelta(days=DAYS_TO_KEEP)
    kept_lines = []

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = datetime.fromisoformat(record["timestamp"].rstrip("Z"))
                    if ts >= cutoff:
                        kept_lines.append(line)
                except:
                    # Сохраняем неразборчивые строки (на всякий)
                    kept_lines.append(line)

        # Создаём резервную копию
        if os.path.exists(LOG_FILE):
            os.replace(LOG_FILE, BACKUP_FILE)

        # Пишем обновлённый файл
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(kept_lines))
            if kept_lines:
                f.write("\n")

        print(f"Ротация завершена. Осталось записей: {len(kept_lines)}")

    except Exception as e:
        print(f"Ошибка ротации: {e}")

if __name__ == "__main__":
    rotate_logs()