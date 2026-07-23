"""
Nexus - Cross-Exchange Consolidated Order Book

Merges top-N depth from Binance/OKX/MEXC into a single book
keyed by binned price. Sizes are summed per-bin and tagged by source so
attribution survives the merge - institutional callers can see *which*
venues contribute to a given level.

This is the input layer for the weighted-mid engine and any cross-exchange
liquidity analytics. It is read-only over per-exchange `*_data.order_books`
state - it does not mutate venue buffers.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import BIN_SIZE_USD, EXCHANGE_WEIGHTS
from backend.ingestion.binance_ws import binance_data
from backend.ingestion.okx_ws import okx_data
from backend.ingestion.mexc_ws import mexc_data


_VENUES: List[Tuple[str, Any]] = [
    ("binance", binance_data),
    ("okx", okx_data),
    ("mexc", mexc_data),
]


def _bin_size(symbol: str) -> float:
    return BIN_SIZE_USD.get(symbol, BIN_SIZE_USD.get("DEFAULT", 0.1))


def _bin_price(price: float, size: float) -> float:
    if size <= 0:
        return price
    return round(price / size) * size


def _book_levels(book: Optional[dict], side: str) -> List[List[float]]:
    if not book:
        return []
    levels = book.get(side) or []
    out: List[List[float]] = []
    for lv in levels:
        if not lv or len(lv) < 2:
            continue
        try:
            p = float(lv[0]); q = float(lv[1])
        except (TypeError, ValueError):
            continue
        if p > 0 and q > 0:
            out.append([p, q])
    return out


def _merge_side(
    symbol: str,
    side: str,
    venue_weight_override: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Bin and merge a single side across venues.

    Returns: list of {price, size, weighted_size, sources: {venue: size}}
    """
    bin_size = _bin_size(symbol)
    weights = venue_weight_override if venue_weight_override is not None else EXCHANGE_WEIGHTS
    # bin_price -> { 'size': float, 'weighted_size': float, 'sources': {venue: size} }
    agg: Dict[float, Dict[str, Any]] = {}

    for name, store in _VENUES:
        book = store.order_books.get(symbol) if hasattr(store, "order_books") else None
        levels = _book_levels(book, side)
        if not levels:
            continue
        w = float(weights.get(name, 0.0))
        for price, qty in levels:
            bp = _bin_price(price, bin_size)
            slot = agg.get(bp)
            if slot is None:
                slot = {"price": bp, "size": 0.0, "weighted_size": 0.0, "sources": {}}
                agg[bp] = slot
            slot["size"] += qty
            slot["weighted_size"] += qty * w
            slot["sources"][name] = slot["sources"].get(name, 0.0) + qty

    rows = list(agg.values())
    reverse = side == "bids"
    rows.sort(key=lambda r: r["price"], reverse=reverse)
    return rows


def merge_books(
    symbol: str,
    depth: int = 20,
    venue_weight_override: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Build the consolidated book for `symbol`.

    Parameters
    ----------
    symbol : "BTCUSDT" etc.
    depth : top-N levels per side after binning + sort
    venue_weight_override : per-tick degraded weights from feed_validator

    Returns a dict with bids, asks, mid, spread, contributing venues.
    """
    sym = symbol.upper()
    bids = _merge_side(sym, "bids", venue_weight_override)[:depth]
    asks = _merge_side(sym, "asks", venue_weight_override)[:depth]

    contributors = sorted({
        v for row in (bids + asks) for v in row["sources"].keys()
    })
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    mid = (best_bid + best_ask) / 2.0 if (best_bid and best_ask) else None
    spread = (best_ask - best_bid) if (best_bid and best_ask) else None
    spread_bps = (spread / mid * 1e4) if (mid and spread is not None) else None

    return {
        "symbol": sym,
        "timestamp": time.time(),
        "depth": depth,
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread": spread,
        "spread_bps": spread_bps,
        "contributors": contributors,
    }
