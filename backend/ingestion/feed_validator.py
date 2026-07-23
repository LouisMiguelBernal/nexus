"""
Nexus - Per-Exchange Feed Validator

Computes a per-venue degradation factor in [0, 1] driven by:
  - staleness (time since last WS event)
  - mid-price outlier z-score vs cross-exchange median
  - missing book

degradation_factor = 1.0 → trusted, full weight
degradation_factor = 0.0 → exclude from fusion until recovered

Read-only over WSManager + per-exchange data stores. Does NOT touch
ws_manager.py connection logic - preserves SSL permissive fallback path.
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import EXCHANGE_WEIGHTS
from backend.ingestion.binance_ws import binance_data
from backend.ingestion.okx_ws import okx_data
from backend.ingestion.mexc_ws import mexc_data


# Map venue name -> WSManager connection name (binance has a different conn key)
_CONN_NAME = {
    "binance": "binance_futures",
    "okx": "okx",
    "mexc": "mexc",
}

_VENUES: List[Tuple[str, Any]] = [
    ("binance", binance_data),
    ("okx", okx_data),
    ("mexc", mexc_data),
]

# Staleness ramp: full weight under STALE_OK_S, zero past STALE_DEAD_S
STALE_OK_S = 5.0
STALE_DEAD_S = 30.0

# Outlier threshold (median absolute z); >4 → exclude
OUTLIER_Z_HARD = 4.0
OUTLIER_Z_SOFT = 2.0


def _venue_mid(store: Any, symbol: str) -> Optional[float]:
    book = store.order_books.get(symbol) if hasattr(store, "order_books") else None
    if not book:
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return None
    try:
        bb = float(bids[0][0]); ba = float(asks[0][0])
    except (TypeError, ValueError, IndexError):
        return None
    if bb <= 0 or ba <= 0:
        return None
    return (bb + ba) / 2.0


def _staleness_factor(seconds_since: Optional[float]) -> float:
    if seconds_since is None:
        return 0.5  # unknown - treat as half-weight
    if seconds_since <= STALE_OK_S:
        return 1.0
    if seconds_since >= STALE_DEAD_S:
        return 0.0
    return 1.0 - (seconds_since - STALE_OK_S) / (STALE_DEAD_S - STALE_OK_S)


def _spread_factor(book: Optional[dict]) -> float:
    """Tighter spread → higher factor. Caps at 1.0; falls off past 50bps."""
    if not book:
        return 0.5
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return 0.5
    try:
        bb = float(bids[0][0]); ba = float(asks[0][0])
    except (TypeError, ValueError):
        return 0.5
    if bb <= 0 or ba <= 0 or ba <= bb:
        return 0.5
    mid = (bb + ba) / 2.0
    bps = (ba - bb) / mid * 1e4
    if bps <= 1.0:
        return 1.0
    if bps >= 50.0:
        return 0.2
    return 1.0 - (bps - 1.0) / 49.0 * 0.8


def _volume_factor(store: Any, symbol: str) -> float:
    """Recent trade activity → higher confidence in feed."""
    trades = None
    if hasattr(store, "agg_trades"):
        trades = store.agg_trades.get(symbol)
    elif hasattr(store, "trades"):
        trades = store.trades.get(symbol)
    if not trades:
        return 0.4
    n = len(trades)
    if n >= 200:
        return 1.0
    if n <= 5:
        return 0.3
    return 0.3 + (n - 5) / 195.0 * 0.7


def _outlier_z(symbol: str) -> Dict[str, float]:
    """Per-venue absolute z-score of mid vs cross-exchange median."""
    mids: Dict[str, float] = {}
    for name, store in _VENUES:
        m = _venue_mid(store, symbol)
        if m is not None:
            mids[name] = m
    if len(mids) < 2:
        return {name: 0.0 for name in mids}
    values = list(mids.values())
    median = statistics.median(values)
    devs = [abs(v - median) for v in values]
    mad = statistics.median(devs)
    # MAD floor: when ≥2 venues agree to the cent, MAD collapses to 0. A bare
    # `median * 1e-6` floor turns a 0.01% cross-venue spread (normal!) into a
    # 70σ outlier and zeros out the degradation factor. 5 bps of the median is
    # the realistic noise floor - venues drifting under that are not outliers.
    mad_floor = median * 5e-4 if median > 0 else 1e-9
    mad = max(mad, mad_floor)
    return {
        name: abs(m - median) / (1.4826 * mad)
        for name, m in mids.items()
    }


def _outlier_factor(z: float) -> float:
    if z <= OUTLIER_Z_SOFT:
        return 1.0
    if z >= OUTLIER_Z_HARD:
        return 0.0
    return 1.0 - (z - OUTLIER_Z_SOFT) / (OUTLIER_Z_HARD - OUTLIER_Z_SOFT)


def evaluate_feeds(
    symbol: str,
    ws_manager: Optional[Any] = None,
) -> Dict[str, Dict[str, Any]]:
    """Compute per-venue health for `symbol`.

    Returns: {venue: {connected, last_event_age_s, mid, z, degradation,
                      static_weight, dynamic_weight, factors: {...}}}
    """
    sym = symbol.upper()

    gap = ws_manager.gap_report() if ws_manager is not None else {}
    z_by_venue = _outlier_z(sym)
    out: Dict[str, Dict[str, Any]] = {}

    for name, store in _VENUES:
        conn_key = _CONN_NAME[name]
        conn_state = gap.get(conn_key, {}) if isinstance(gap, dict) else {}
        seconds_since = conn_state.get("seconds_since_last_event")
        connected = bool(conn_state.get("connected", False))
        book = store.order_books.get(sym) if hasattr(store, "order_books") else None

        f_stale = _staleness_factor(seconds_since)
        f_spread = _spread_factor(book)
        f_volume = _volume_factor(store, sym)
        z = z_by_venue.get(name, 0.0)
        f_outlier = _outlier_factor(z)
        f_book = 1.0 if (book and book.get("bids") and book.get("asks")) else 0.0

        # Multiply factors; any one near-zero kills the feed.
        degradation = f_stale * f_spread * f_volume * f_outlier * f_book
        static_w = float(EXCHANGE_WEIGHTS.get(name, 0.0))
        dynamic_w = static_w * degradation

        out[name] = {
            "connected": connected,
            "last_event_age_s": seconds_since,
            "mid": _venue_mid(store, sym),
            "z": z,
            "degradation": round(degradation, 4),
            "static_weight": static_w,
            "dynamic_weight": round(dynamic_w, 6),
            "factors": {
                "staleness": round(f_stale, 3),
                "spread": round(f_spread, 3),
                "volume": round(f_volume, 3),
                "outlier": round(f_outlier, 3),
                "book": f_book,
            },
        }
    return out


def normalized_dynamic_weights(
    symbol: str,
    ws_manager: Optional[Any] = None,
) -> Dict[str, float]:
    """Per-venue dynamic weights renormalized to sum=1 across non-degraded feeds."""
    health = evaluate_feeds(symbol, ws_manager=ws_manager)
    raw = {name: h["dynamic_weight"] for name, h in health.items()}
    total = sum(raw.values())
    if total <= 0:
        return {name: 0.0 for name in raw}
    return {name: w / total for name, w in raw.items()}


def feed_health_summary(ws_manager: Optional[Any] = None, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """Aggregate /api/feed/health payload across watched symbols."""
    from backend.config import DEFAULT_SYMBOLS
    syms = symbols or DEFAULT_SYMBOLS
    snap = {sym: evaluate_feeds(sym, ws_manager=ws_manager) for sym in syms}
    # Per-venue rollup (average degradation across symbols)
    rollup: Dict[str, Dict[str, Any]] = {}
    for venue in [v for v, _ in _VENUES]:
        degs = [snap[s][venue]["degradation"] for s in syms if venue in snap[s]]
        ages = [snap[s][venue]["last_event_age_s"] for s in syms if snap[s][venue]["last_event_age_s"] is not None]
        connected_any = any(snap[s][venue]["connected"] for s in syms if venue in snap[s])
        rollup[venue] = {
            "connected": connected_any,
            "avg_degradation": round(sum(degs) / len(degs), 4) if degs else 0.0,
            "max_age_s": round(max(ages), 2) if ages else None,
            "static_weight": float(EXCHANGE_WEIGHTS.get(venue, 0.0)),
        }
    return {
        "timestamp": time.time(),
        "symbols": syms,
        "per_symbol": snap,
        "venues": rollup,
    }
