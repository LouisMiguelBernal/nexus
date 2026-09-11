"""
Nexus - Absorption sampler

Wires the existing AbsorptionDetector into a 5-second rolling sampler so the
Matrix Engine's "ABSORPTION" row shows live state instead of the inline
single-shot heuristic in /api/orderflow.

For each symbol we keep a tiny buffer of recent trades (last 5s, in CVDComputer
format), and on each tick call AbsorptionDetector.analyze_window() once. The
last non-None result is cached on the detector for endpoint reads.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Mapping

from backend.computation.absorption import AbsorptionDetector

logger = logging.getLogger("nexus.absorption_sampler")


def _trades_in_window(deltas, window_s: float) -> list[dict]:
    cutoff_ms = (time.time() - window_s) * 1000
    return [
        {
            "price": d["price"],
            "qty": d["qty"],
            "usd": d.get("usd", d["price"] * d["qty"]),
            # delta sign carries side: +ve = taker buy, -ve = taker sell
            "is_buyer_maker": d["delta"] < 0,
        }
        for d in deltas
        if d["ts"] >= cutoff_ms
    ]


async def absorption_sample_loop(
    detectors: Mapping[str, AbsorptionDetector],
    cvd_computers,
    interval_s: float = 5.0,
) -> None:
    while True:
        try:
            for sym, det in list(detectors.items()):
                cvd = cvd_computers.get(sym)
                if not cvd:
                    continue
                deltas = list(cvd._deltas)  # noqa: SLF001 - internal but stable
                if len(deltas) < 20:
                    continue
                trades = _trades_in_window(deltas, window_s=interval_s)
                if len(trades) < 10:
                    continue
                price_start = trades[0]["price"]
                price_end = trades[-1]["price"]
                try:
                    result = det.analyze_window(
                        trades, price_start=price_start, price_end=price_end,
                        window_seconds=int(interval_s),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("absorption %s analyze_window: %s", sym, exc)
                    continue
                # Cache last result + ts on detector for /api/matrix consumers.
                det._last_result = result  # type: ignore[attr-defined]
                det._last_sample_ts = time.time()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.error("absorption_sample_loop error: %s", exc)
        await asyncio.sleep(interval_s)
