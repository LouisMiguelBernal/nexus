"""
Nexus - Trade Journal Storage
"""

import logging
from typing import Dict, List, Optional

from backend.storage.db import get_connection

logger = logging.getLogger("nexus.storage.journal")


def log_trade(trade: dict) -> int:
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO trade_journal (symbol, side, entry_price, exit_price, leverage,
                                   size_usd, pnl_usd, pnl_pct, zone_tier, zone_type,
                                   macro_status, notes, entry_time, exit_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.get("symbol"),
        trade.get("side"),
        trade.get("entry_price"),
        trade.get("exit_price"),
        trade.get("leverage", 1),
        trade.get("size_usd"),
        trade.get("pnl_usd"),
        trade.get("pnl_pct"),
        trade.get("zone_tier"),
        trade.get("zone_type"),
        trade.get("macro_status"),
        trade.get("notes"),
        trade.get("entry_time"),
        trade.get("exit_time"),
    ))
    conn.commit()
    return cursor.lastrowid


def get_trades(symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
    conn = get_connection()
    if symbol:
        rows = conn.execute(
            "SELECT * FROM trade_journal WHERE symbol = ? ORDER BY created_at DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trade_journal ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_performance_stats() -> Dict:
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END) as losses,
            COALESCE(AVG(pnl_pct), 0) as avg_pnl_pct,
            COALESCE(SUM(pnl_usd), 0) as total_pnl_usd,
            COALESCE(AVG(CASE WHEN pnl_usd > 0 THEN pnl_pct END), 0) as avg_win_pct,
            COALESCE(AVG(CASE WHEN pnl_usd <= 0 THEN pnl_pct END), 0) as avg_loss_pct
        FROM trade_journal WHERE exit_price IS NOT NULL
    """).fetchone()

    total = row["total_trades"] or 0
    wins = row["wins"] or 0

    return {
        "total_trades": total,
        "wins": wins,
        "losses": row["losses"] or 0,
        "win_rate": round(wins / max(total, 1), 4),
        "avg_pnl_pct": round(row["avg_pnl_pct"], 4),
        "total_pnl_usd": round(row["total_pnl_usd"], 2),
        "avg_win_pct": round(row["avg_win_pct"], 4),
        "avg_loss_pct": round(row["avg_loss_pct"], 4),
    }
