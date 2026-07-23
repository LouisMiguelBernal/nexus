"""
Nexus - Background OI Poller

The OITracker.fetch_all() call seeds the rolling _history deque used by
get_trend() and roc_zscore(). Without periodic refresh that deque only fills
when an HTTP endpoint that calls fetch_all() is hit by the frontend - which is
why "OI Δ 1H" was stuck at 0 in the Matrix Engine. This loop refreshes every
30s (Binance/OKX OI endpoints rate-limit cheaply at this cadence) and also
samples funding so the term-structure factor has real data.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Mapping

from backend.computation.oi_analysis import OITracker
from backend.computation.funding import FundingTracker

logger = logging.getLogger("nexus.oi_poller")


async def oi_poll_loop(
    oi_trackers: Mapping[str, OITracker],
    funding_trackers: Mapping[str, FundingTracker] | None = None,
    interval_s: int = 30,
) -> None:
    """Refresh OI (and funding if provided) snapshots for every tracked symbol.

    Runs forever. Catches per-symbol exceptions so a single venue failure for
    a single symbol cannot stall the loop.
    """
    while True:
        try:
            for sym, tracker in list(oi_trackers.items()):
                try:
                    await tracker.fetch_all()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("oi poll %s: %s", sym, exc)
            if funding_trackers:
                for sym, ft in list(funding_trackers.items()):
                    try:
                        await ft.fetch_all()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("funding poll %s: %s", sym, exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("oi_poll_loop tick error: %s", exc)
        await asyncio.sleep(interval_s)
