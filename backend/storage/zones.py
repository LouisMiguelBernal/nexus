"""
Nexus - Zone Watchlist CRUD
"""

import json
import logging
from typing import Dict, List, Optional

from backend.storage.db import get_connection

logger = logging.getLogger("nexus.storage.zones")


def save_zone(zone_data: dict) -> int:
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO zones (symbol, price_center, price_low, price_high, zone_type,
                          tier, score, exchanges, exchange_count, first_seen, last_seen, persistent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        zone_data["symbol"] if "symbol" in zone_data else "UNKNOWN",
        zone_data.get("price_center", 0),
        zone_data.get("price_low", 0),
        zone_data.get("price_high", 0),
        zone_data.get("zone_type", ""),
        zone_data.get("tier", ""),
        zone_data.get("score", 0),
        json.dumps(zone_data.get("exchanges", [])),
        zone_data.get("exchange_count", 0),
        zone_data.get("first_seen", 0),
        zone_data.get("last_seen", 0),
        1 if zone_data.get("persistent") else 0,
    ))
    conn.commit()
    return cursor.lastrowid


def add_to_watchlist(symbol: str, price_center: float, tier: str, zone_type: str) -> int:
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO zone_watchlist (symbol, price_center, tier, zone_type)
        VALUES (?, ?, ?, ?)
    """, (symbol, price_center, tier, zone_type))
    conn.commit()
    return cursor.lastrowid


def remove_from_watchlist(watchlist_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM zone_watchlist WHERE id = ?", (watchlist_id,))
    conn.commit()


def get_watchlist(status: Optional[str] = None) -> List[Dict]:
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM zone_watchlist WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM zone_watchlist ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_watchlist_status(watchlist_id: int, status: str):
    conn = get_connection()
    conn.execute("UPDATE zone_watchlist SET status = ? WHERE id = ?", (status, watchlist_id))
    conn.commit()
