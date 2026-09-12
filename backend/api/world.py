"""
Nexus - /api/world/* : cross-asset context + global-event intelligence.

Two classes of route, and they follow different rules on purpose:

  * **Poller-owned** (``/board``, ``/macro``, ``/regime``, ``/geo``) read a
    snapshot the background loop refreshed. The request path never touches an
    upstream. This is the pattern the July latency fix established - hot routes
    that re-fetched REST per poll took the terminal from 0.2s to 25s.

  * **On-demand** (``/chart``, ``/fundamentals``, ``/screener``, ``/options``,
    ``/search``) are user-initiated and unbounded in symbol space, so they
    cannot be pre-polled. They get a TTL cache plus single-flight instead, so a
    double-click or two mounted panels cost one upstream call.

Everything served here is tagged ``asset_class: cross_asset`` at the source.
Nexus trades USDT-M perps; nothing on this router is a tradable symbol, and no
response from it may be routed into a perp code path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.config import CROSS_ASSET_UNIVERSE
from backend.crossasset import equity as xa_equity
from backend.crossasset import yahoo as xa_yahoo

logger = logging.getLogger("nexus.api.world")

# Range -> interval. Yahoo rejects mismatched pairs (5y at 5m granularity).
_INTERVAL_FOR = {
    "1d": "5m",
    "5d": "15m",
    "1mo": "1d",
    "3mo": "1d",
    "6mo": "1d",
    "1y": "1d",
    "2y": "1wk",
    "5y": "1wk",
    "max": "1mo",
}


def make_router(*, state) -> APIRouter:
    """
    Build the world router bound to a state object exposing:

      - ``state.board``      grouped cross-asset quotes (poller-owned)
      - ``state.macro``      FRED series board (poller-owned)
      - ``state.regime``     risk appetite + stress (poller-owned)
      - ``state.geo``        global-event snapshot + instability (poller-owned)
      - ``state.updated_at`` per-section epoch seconds
    """
    router = APIRouter(prefix="/api/world", tags=["world"])

    _cache: dict[str, tuple[float, Any]] = {}
    _locks: dict[str, asyncio.Lock] = {}

    async def cached(key: str, ttl: float, factory):
        """TTL cache + single-flight for the on-demand routes."""
        hit = _cache.get(key)
        now = time.time()
        if hit and (now - hit[0]) < ttl:
            return hit[1]

        lock = _locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = _cache.get(key)  # another caller may have filled it while we waited
            if hit and (time.time() - hit[0]) < ttl:
                return hit[1]
            value = await factory()
            _cache[key] = (time.time(), value)
            return value

    def _age(section: str) -> float | None:
        ts = (getattr(state, "updated_at", None) or {}).get(section)
        return round(time.time() - ts, 1) if ts else None

    # -----------------------------------------------------------------------
    # Poller-owned snapshots
    # -----------------------------------------------------------------------

    @router.get("/board")
    async def board():
        """Cross-asset quote board, grouped by asset class."""
        return {
            "groups": list(CROSS_ASSET_UNIVERSE.keys()),
            "quotes": getattr(state, "board", None) or {},
            "age_seconds": _age("board"),
        }

    @router.get("/macro")
    async def macro():
        """FRED indicator board plus the live Treasury curve."""
        return {
            "indicators": (getattr(state, "macro", None) or {}).get("indicators", []),
            "curve": (getattr(state, "macro", None) or {}).get("curve", []),
            "curve_spread": (getattr(state, "macro", None) or {}).get("curve_spread"),
            "inverted": (getattr(state, "macro", None) or {}).get("inverted"),
            "age_seconds": _age("macro"),
        }

    @router.get("/regime")
    async def regime():
        """Cross-asset risk appetite and macro stress, with component axes."""
        snapshot = getattr(state, "regime", None) or {}
        return {**snapshot, "age_seconds": _age("regime")}

    @router.get("/geo")
    async def geo():
        """Global-event snapshot and the composite instability score."""
        snapshot = getattr(state, "geo", None) or {}
        return {**snapshot, "age_seconds": _age("geo")}

    # -----------------------------------------------------------------------
    # On-demand
    # -----------------------------------------------------------------------

    @router.get("/chart/{symbol}")
    async def chart(symbol: str, range: str = Query("6mo"), interval: str | None = None):
        if range not in _INTERVAL_FOR:
            raise HTTPException(400, f"unsupported range {range}")
        resolved = interval or _INTERVAL_FOR[range]
        key = f"chart:{symbol}:{range}:{resolved}"
        data = await cached(key, 60.0, lambda: xa_yahoo.fetch_candles(symbol, range, resolved))
        return {**data, "range": range, "interval": resolved, "asset_class": "cross_asset"}

    @router.get("/fundamentals/{symbol}")
    async def fundamentals(symbol: str):
        return await cached(f"fund:{symbol}", 900.0, lambda: xa_equity.fetch_fundamentals(symbol))

    @router.get("/screener")
    async def screener(id: str = Query("most_actives"), count: int = Query(40, le=100)):
        return await cached(f"screen:{id}:{count}", 180.0, lambda: xa_equity.fetch_screen(id, count))

    @router.get("/options/{symbol}")
    async def options(symbol: str, expiry: int | None = None):
        return await cached(
            f"opt:{symbol}:{expiry or 'front'}", 60.0, lambda: xa_equity.fetch_chain(symbol, expiry)
        )

    @router.get("/search")
    async def search(q: str = Query(..., min_length=1), limit: int = Query(10, le=25)):
        if len(q.strip()) < 1:
            return {"q": q, "results": []}
        results = await cached(f"search:{q.lower()}:{limit}", 600.0, lambda: xa_yahoo.search(q, limit))
        return {"q": q, "results": results}

    return router
