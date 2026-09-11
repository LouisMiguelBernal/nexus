"""
Nexus - SQLite Database Connection + Schema
Local storage for zones, alerts, journal, briefs.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from backend.config import DB_PATH

logger = logging.getLogger("nexus.db")

_connection: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
        _init_schema(_connection)
        logger.info(f"SQLite connected: {DB_PATH}")
    return _connection


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            price_center REAL NOT NULL,
            price_low REAL NOT NULL,
            price_high REAL NOT NULL,
            zone_type TEXT NOT NULL,
            tier TEXT NOT NULL,
            score REAL NOT NULL,
            exchanges TEXT NOT NULL,
            exchange_count INTEGER NOT NULL,
            first_seen REAL NOT NULL,
            last_seen REAL NOT NULL,
            persistent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS zone_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            price_center REAL NOT NULL,
            tier TEXT NOT NULL,
            zone_type TEXT NOT NULL,
            status TEXT DEFAULT 'watching',
            alert_on_approach INTEGER DEFAULT 1,
            alert_on_hit INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT NOT NULL,
            symbol TEXT,
            message TEXT NOT NULL,
            data TEXT,
            sent_telegram INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            leverage INTEGER DEFAULT 1,
            size_usd REAL,
            pnl_usd REAL,
            pnl_pct REAL,
            zone_tier TEXT,
            zone_type TEXT,
            macro_status TEXT,
            notes TEXT,
            entry_time TIMESTAMP,
            exit_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brief_text TEXT NOT NULL,
            signals_json TEXT,
            generated_at REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Rolling snapshots of derivative metrics (OBI, tape speed, liquidation
        -- imbalance). Written every few seconds; trimmed to last 7 days by the
        -- periodic pruner. Used for historical research + back-testing.
        CREATE TABLE IF NOT EXISTS metric_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            metric TEXT NOT NULL,   -- obi | tape | liq
            t REAL NOT NULL,        -- unix seconds
            value REAL,             -- primary scalar (e.g. obi, tps, imbalance)
            extra TEXT              -- JSON blob for secondary fields
        );

        CREATE INDEX IF NOT EXISTS idx_zones_symbol ON zones(symbol);
        CREATE INDEX IF NOT EXISTS idx_zones_tier ON zones(tier);
        CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
        CREATE INDEX IF NOT EXISTS idx_journal_symbol ON trade_journal(symbol);
        CREATE INDEX IF NOT EXISTS idx_metrics_sym_t ON metric_snapshots(symbol, metric, t);
    """)
    conn.commit()


def close():
    global _connection
    if _connection:
        _connection.close()
        _connection = None
        logger.info("SQLite connection closed")
