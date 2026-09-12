"""
Nexus - world poller: owns freshness for the cross-asset and geo layers.

The house rule this file exists to satisfy: **the request path never fetches an
upstream; background pollers own freshness.** Every ``/api/world/*`` snapshot
route reads what this loop last published.

Cadence is set by what actually moves:

  board / regime   every ``CROSS_ASSET_POLL_SECONDS``  - daily-bar cross-asset
                   data; polling faster buys nothing and risks a Yahoo 429
  macro (FRED)     every 30 min - series publish daily at best
  geo              every ``GEO_POLL_SECONDS``

Each section refreshes independently and failure-isolated: a Yahoo outage must
not stop the geo score reaching the macro gate, and vice versa. On failure the
previous snapshot stays published - stale beats blank - and ``updated_at`` stops
advancing, which is what the UI reads to show age.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.computation import cross_regime
from backend.config import (
    CROSS_ASSET_POLL_SECONDS,
    CROSS_ASSET_UNIVERSE,
    GEO_POLL_SECONDS,
    REGIME_PROXIES,
)
from backend.crossasset import fred as xa_fred
from backend.crossasset import yahoo as xa_yahoo
from backend.geo import instability as geo_instability
from backend.geo import sources as geo_sources
from backend.geo import worldmonitor as geo_wm

logger = logging.getLogger("nexus.jobs.world")

MACRO_POLL_SECONDS = 1800.0

# Maturities for the Treasury curve, in ascending order.
_CURVE = [("^IRX", "13W", 0.25), ("^FVX", "5Y", 5.0), ("^TNX", "10Y", 10.0), ("^TYX", "30Y", 30.0)]


class WorldState:
    """
    Snapshot holder shared by the poller and the ``/api/world`` router.

    Plain attributes, replaced wholesale on each refresh. Readers get either the
    old dict or the new one, never a half-written one - which is all the
    consistency a single-writer snapshot needs.
    """

    def __init__(self) -> None:
        self.board: dict[str, list[dict]] = {}
        self.macro: dict[str, Any] = {}
        self.regime: dict[str, Any] = {}
        self.geo: dict[str, Any] = {}
        self.proxies: dict[str, dict] = {}
        self.updated_at: dict[str, float] = {}

    def quote(self, symbol: str) -> dict | None:
        for rows in self.board.values():
            for row in rows:
                if row.get("symbol") == symbol:
                    return row
        return None


# ---------------------------------------------------------------------------
# Section refreshers
# ---------------------------------------------------------------------------


async def refresh_board(state: WorldState) -> None:
    """Every tracked cross-asset instrument, grouped, plus the regime proxies."""
    pairs = [(sym, name) for group in CROSS_ASSET_UNIVERSE.values() for sym, name in group]
    quotes = await xa_yahoo.fetch_quotes(pairs)
    if not quotes:
        logger.warning("cross-asset board refresh returned nothing; keeping previous")
        return

    by_symbol = {q["symbol"]: q for q in quotes}
    board: dict[str, list[dict]] = {}
    for group, members in CROSS_ASSET_UNIVERSE.items():
        board[group] = [
            {**by_symbol[sym], "group": group, "asset_class": "cross_asset"}
            for sym, _ in members
            if sym in by_symbol
        ]

    state.board = board
    state.proxies = {name: by_symbol[sym] for name, sym in REGIME_PROXIES.items() if sym in by_symbol}
    state.updated_at["board"] = time.time()

    # The regime read is a pure function of the board, so derive it here rather
    # than paying for a second fetch on its own timer.
    roro = cross_regime.risk_appetite(state.proxies)
    state.regime = {
        "risk_appetite": roro,
        "stress": cross_regime.macro_stress(state.proxies, roro),
        "proxies": {
            name: {
                "symbol": q["symbol"],
                "price": q["price"],
                "change_pct": q["change_pct"],
            }
            for name, q in state.proxies.items()
        },
    }
    state.updated_at["regime"] = time.time()


async def refresh_macro(state: WorldState) -> None:
    """FRED indicator board plus the live Treasury curve off the quote board."""
    indicators = await xa_fred.fetch_macro_board()

    curve = []
    for symbol, label, years in _CURVE:
        q = state.quote(symbol)
        curve.append(
            {
                "symbol": symbol,
                "label": label,
                "years": years,
                "yield": q.get("price") if q else None,
                "change": q.get("change") if q else None,
            }
        )

    short = curve[0]["yield"]
    long = curve[2]["yield"]
    spread = (long - short) if isinstance(short, (int, float)) and isinstance(long, (int, float)) else None

    state.macro = {
        "indicators": indicators,
        "curve": curve,
        "curve_spread": round(spread, 3) if spread is not None else None,
        # 10Y under 13W: the classic inversion. Stated once here so no consumer
        # has to rediscover the sign convention.
        "inverted": (spread < 0) if spread is not None else None,
    }
    state.updated_at["macro"] = time.time()


async def refresh_geo(state: WorldState, macro_gate=None) -> None:
    """
    Global-event snapshot -> composite instability -> macro gate.

    This is the write that can change position sizing, so it is deliberately the
    last thing the function does and it is skipped entirely when no source
    answered: publishing ``None`` restores calendar-only gating rather than
    inventing a safe-looking zero.
    """
    snapshot = await geo_sources.fetch_all()
    enrichment = await geo_wm.fetch_instability()
    score = geo_instability.compute(snapshot, enrichment)

    state.geo = {**snapshot, "risk": score, "enrichment": enrichment}
    state.updated_at["geo"] = time.time()

    if macro_gate is not None:
        try:
            macro_gate.set_geo_risk(
                score.get("score"),
                band=score.get("band", "unknown"),
                reason=score.get("reason"),
            )
        except Exception as e:  # a gate write must never kill the poller  # noqa: BLE001
            logger.error("failed to publish geo risk to macro gate: %s", e)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


async def _safe(name: str, coro) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("world poller: %s refresh failed: %s", name, e)


async def run(state: WorldState, macro_gate=None) -> None:
    """
    Long-running poll loop. Started from the FastAPI lifespan and cancelled on
    shutdown. Sections are staggered so a cold start does not fire forty Yahoo
    requests and a geo fan-out in the same instant.
    """
    logger.info(
        "world poller starting (board %.0fs, macro %.0fs, geo %.0fs)",
        CROSS_ASSET_POLL_SECONDS,
        MACRO_POLL_SECONDS,
        GEO_POLL_SECONDS,
    )

    await _safe("board", refresh_board(state))
    await _safe("geo", refresh_geo(state, macro_gate))
    await _safe("macro", refresh_macro(state))

    last = {"board": time.time(), "geo": time.time(), "macro": time.time()}

    while True:
        try:
            await asyncio.sleep(15)
            now = time.time()

            if now - last["board"] >= CROSS_ASSET_POLL_SECONDS:
                await _safe("board", refresh_board(state))
                last["board"] = now
            if now - last["geo"] >= GEO_POLL_SECONDS:
                await _safe("geo", refresh_geo(state, macro_gate))
                last["geo"] = now
            if now - last["macro"] >= MACRO_POLL_SECONDS:
                await _safe("macro", refresh_macro(state))
                last["macro"] = now

        except asyncio.CancelledError:
            logger.info("world poller stopped")
            raise
        except Exception as e:  # noqa: BLE001
            logger.error("world poller loop error: %s", e)
            await asyncio.sleep(30)
