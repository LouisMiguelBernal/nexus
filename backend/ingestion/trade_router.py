"""
Nexus - Trade Source Router (Primary → Fallback)

Picks a single trade-stream source per symbol so CVD / smart-money / Alpha
don't double-count. Failover order: binance → okx → mexc, gated on the
feed_validator degradation factor and last-event age.

Trades from non-Binance venues are normalized to the canonical Binance
schema (`is_buyer_maker` boolean) so downstream consumers stay unchanged.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from backend.ingestion.binance_ws import binance_data
from backend.ingestion.okx_ws import okx_data
from backend.ingestion.mexc_ws import mexc_data
from backend.ingestion.feed_validator import evaluate_feeds


# Order matters - first acceptable source wins.
_TRADE_PRIORITY: Tuple[str, ...] = ("binance", "okx", "mexc")

# Health gates for promotion to primary
MIN_DEGRADATION = 0.3
MAX_AGE_S = 5.0

# Per-symbol active source + cursor (ms epoch of last forwarded trade)
_active_source: Dict[str, str] = {}
_cursor: Dict[str, int] = {}


def _is_acceptable(h: Dict[str, Any]) -> bool:
    if not h.get("connected", False):
        return False
    if (h.get("degradation") or 0.0) < MIN_DEGRADATION:
        return False
    age = h.get("last_event_age_s")
    if age is not None and age > MAX_AGE_S:
        return False
    return True


def _normalize_okx_trade(t: dict) -> Optional[dict]:
    try:
        price = float(t.get("price", 0))
        qty = float(t.get("qty", 0))
    except (TypeError, ValueError):
        return None
    if price <= 0 or qty <= 0:
        return None
    side = (t.get("side") or "").lower()
    # OKX 'side' = taker side. is_buyer_maker = taker is seller
    is_buyer_maker = side == "sell"
    return {
        "price": price,
        "qty": qty,
        "is_buyer_maker": is_buyer_maker,
        "time": int(t.get("time", time.time() * 1000)),
    }


def _normalize_mexc_trade(t: dict) -> Optional[dict]:
    try:
        price = float(t.get("price", 0))
        qty = float(t.get("qty", 0))
    except (TypeError, ValueError):
        return None
    if price <= 0 or qty <= 0:
        return None
    side = (t.get("side") or "").lower()
    is_buyer_maker = side == "sell"
    return {
        "price": price,
        "qty": qty,
        "is_buyer_maker": is_buyer_maker,
        "time": int(t.get("time", time.time() * 1000)),
    }


def _raw_trades(venue: str, symbol: str) -> List[dict]:
    if venue == "binance":
        return list(binance_data.agg_trades.get(symbol, []))
    if venue == "okx":
        normed: List[dict] = []
        for t in list(okx_data.trades.get(symbol, [])):
            n = _normalize_okx_trade(t)
            if n is not None:
                normed.append(n)
        return normed
    if venue == "mexc":
        normed = []
        for t in list(mexc_data.trades.get(symbol, [])):
            n = _normalize_mexc_trade(t)
            if n is not None:
                normed.append(n)
        return normed
    return []


def select_source(symbol: str, ws_manager: Optional[Any] = None) -> Optional[str]:
    """Choose primary trade source for `symbol` based on live health."""
    health = evaluate_feeds(symbol, ws_manager=ws_manager)
    for venue in _TRADE_PRIORITY:
        h = health.get(venue, {})
        if _is_acceptable(h):
            return venue
    return None


def fetch_new_trades(
    symbol: str,
    ws_manager: Optional[Any] = None,
) -> Tuple[Optional[str], List[dict]]:
    """Return `(active_source, list_of_new_trades_since_cursor)`.

    Source switch resets the cursor to avoid replaying historical trades from
    the new venue (each venue has independent timelines).
    """
    sym = symbol.upper()
    chosen = select_source(sym, ws_manager=ws_manager)
    if chosen is None:
        return None, []

    prev = _active_source.get(sym)
    if prev != chosen:
        _active_source[sym] = chosen
        # Reset cursor to "now" so we only forward fresh trades from the new
        # source - no historical replay from a different venue's deque.
        latest_ms = 0
        for t in _raw_trades(chosen, sym):
            ts = int(t.get("time", 0))
            if ts > latest_ms:
                latest_ms = ts
        _cursor[sym] = latest_ms
        return chosen, []

    cursor = _cursor.get(sym, 0)
    new_trades = [t for t in _raw_trades(chosen, sym) if int(t.get("time", 0)) > cursor]
    if new_trades:
        _cursor[sym] = int(new_trades[-1].get("time", cursor))
    return chosen, new_trades


def active_sources() -> Dict[str, str]:
    """Snapshot of current primary venue per symbol - for /api/feed/health."""
    return dict(_active_source)
