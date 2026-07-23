"""
Nexus - Metric snapshot persistence.

OBI / tape-speed / liquidation-imbalance samples are rolling in-memory; this
module flushes them to SQLite so we can replay and back-test later.

Writes are batched - callers pass a list of (t, value, extra) tuples and we
INSERT them in one transaction to keep the hot path cheap.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Dict, Iterable, List, Optional, Tuple

from backend.storage.db import get_connection

logger = logging.getLogger("nexus.storage.metrics")

# Keep ~7 days of data. Pruner runs once per insert batch cheaply via a COUNT
# check - only deletes when the table exceeds the cap.
_RETENTION_SECONDS = 7 * 24 * 3600


def save_snapshots(
    symbol: str,
    metric: str,
    rows: Iterable[Tuple[float, Optional[float], Optional[Dict]]],
) -> int:
    """Insert a batch. ``rows`` = iterable of (t, value, extra_dict)."""
    conn = get_connection()
    payload = []
    for t, value, extra in rows:
        payload.append((
            symbol,
            metric,
            float(t),
            None if value is None else float(value),
            json.dumps(extra) if extra else None,
        ))
    if not payload:
        return 0
    conn.executemany(
        "INSERT INTO metric_snapshots (symbol, metric, t, value, extra) VALUES (?, ?, ?, ?, ?)",
        payload,
    )
    conn.commit()
    return len(payload)


def prune_old(now: Optional[float] = None) -> int:
    """Delete rows older than the retention window. Returns row count deleted."""
    now = now or time.time()
    cutoff = now - _RETENTION_SECONDS
    conn = get_connection()
    cur = conn.execute("DELETE FROM metric_snapshots WHERE t < ?", (cutoff,))
    conn.commit()
    return cur.rowcount or 0


def fetch_range(
    symbol: str,
    metric: str,
    start: float,
    end: float,
    limit: int = 5000,
) -> List[Dict]:
    """Fetch snapshots for a symbol+metric in [start, end] by unix seconds."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT t, value, extra FROM metric_snapshots
        WHERE symbol = ? AND metric = ? AND t BETWEEN ? AND ?
        ORDER BY t ASC
        LIMIT ?
        """,
        (symbol.upper(), metric, start, end, limit),
    ).fetchall()
    out: List[Dict] = []
    for r in rows:
        entry = {"t": r["t"], "value": r["value"]}
        if r["extra"]:
            try:
                entry["extra"] = json.loads(r["extra"])
            except Exception:
                pass
        out.append(entry)
    return out
