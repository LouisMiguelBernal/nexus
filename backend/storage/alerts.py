"""
Nexus - Alert History Storage
"""

import json
import logging
from typing import Dict, List

from backend.storage.db import get_connection

logger = logging.getLogger("nexus.storage.alerts")


def save_alert(alert_type: str, message: str, symbol: str = "", data: dict = None, sent_telegram: bool = False) -> int:
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO alerts (alert_type, symbol, message, data, sent_telegram)
        VALUES (?, ?, ?, ?, ?)
    """, (alert_type, symbol, message, json.dumps(data) if data else None, 1 if sent_telegram else 0))
    conn.commit()
    return cursor.lastrowid


def get_recent_alerts(limit: int = 50, alert_type: str = None) -> List[Dict]:
    conn = get_connection()
    if alert_type:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE alert_type = ? ORDER BY created_at DESC LIMIT ?",
            (alert_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
