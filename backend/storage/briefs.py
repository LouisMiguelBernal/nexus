"""
Nexus - Morning Brief Storage
"""

import json
import logging
from typing import Dict, List, Optional

from backend.storage.db import get_connection

logger = logging.getLogger("nexus.storage.briefs")


def save_brief(brief_text: str, signals: dict, generated_at: float) -> int:
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO briefs (brief_text, signals_json, generated_at)
        VALUES (?, ?, ?)
    """, (brief_text, json.dumps(signals), generated_at))
    conn.commit()
    return cursor.lastrowid


def get_last_brief() -> Optional[Dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM briefs ORDER BY generated_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_briefs(limit: int = 10) -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM briefs ORDER BY generated_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
