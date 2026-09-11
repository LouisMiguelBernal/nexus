"""
Nexus - FRED macro series (keyless).

``fredgraph.csv`` is the same file the public FRED charts download: no API key,
no registration, one series per call. ``FRED_API_KEY`` stays supported as a
faster JSON path when the user has one configured, but nothing here requires
it - which is what keeps the "zero paid APIs" invariant true for the macro
screen.

Series arrive at wildly different frequencies (daily DGS10, weekly MORTGAGE30US,
monthly CPI, quarterly GDP), so the year-over-year comparison is done **by date**
rather than by a fixed index offset. A 13-row lookback is a year of monthlies and
three years of quarterlies; getting that wrong silently reports a 3-year change
as annual growth.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import httpx

from backend.config import FRED_CSV, FRED_MACRO_SERIES

logger = logging.getLogger("nexus.crossasset.fred")

_CACHE: Dict[str, Tuple[float, List[Dict]]] = {}
_TTL = 6 * 3600.0  # FRED publishes daily at best; six hours is generous


def _parse_csv(text: str) -> List[Dict]:
    """FRED CSV is ``observation_date,SERIES`` with '.' for missing values."""
    out: List[Dict] = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            value = float(parts[1])
        except (TypeError, ValueError):
            continue  # '.' placeholder rows
        out.append({"date": parts[0], "value": value})
    return out


async def fetch_series(series_id: str) -> List[Dict]:
    """One FRED series, most recent 240 observations, TTL-cached."""
    now = time.time()
    hit = _CACHE.get(series_id)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(FRED_CSV.format(series_id=series_id))
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        points = _parse_csv(resp.text)[-240:]
    except Exception as e:
        logger.warning("FRED %s failed: %s", series_id, e)
        # Stale beats empty: a macro card that was right an hour ago is more
        # useful than a blank one.
        return hit[1] if hit else []

    _CACHE[series_id] = (now, points)
    return points


def _nearest_year_ago(points: List[Dict], iso_date: str) -> Optional[Dict]:
    """
    The observation closest to one year before ``iso_date``. Returns None when
    the series does not reach back that far, so a young series reports no YoY
    rather than a wrong one.
    """
    try:
        latest = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    target = date(latest.year - 1, latest.month, min(latest.day, 28))

    best: Optional[Dict] = None
    best_gap = 10**9
    for p in points:
        try:
            gap = abs((datetime.strptime(p["date"], "%Y-%m-%d").date() - target).days)
        except ValueError:
            continue
        if gap < best_gap:
            best_gap, best = gap, p
    # More than a quarter off the mark is not a year-over-year comparison.
    return best if best_gap <= 92 else None


async def fetch_macro_board() -> List[Dict]:
    """Every configured series with its latest reading, MoM delta and YoY."""
    import asyncio

    ids = [s[0] for s in FRED_MACRO_SERIES]
    settled = await asyncio.gather(*(fetch_series(i) for i in ids), return_exceptions=True)

    board: List[Dict] = []
    for (series_id, label, unit, wants_yoy), result in zip(FRED_MACRO_SERIES, settled):
        points = result if isinstance(result, list) else []
        latest = points[-1] if points else None
        prev = points[-2] if len(points) > 1 else None
        year_ago = _nearest_year_ago(points, latest["date"]) if latest else None

        yoy = None
        if wants_yoy and latest and year_ago and year_ago["value"]:
            yoy = (latest["value"] - year_ago["value"]) / year_ago["value"] * 100.0

        board.append({
            "id": series_id,
            "label": label,
            "unit": unit,
            "available": bool(points),
            "latest": latest["value"] if latest else None,
            "latest_date": latest["date"] if latest else None,
            "change_abs": (latest["value"] - prev["value"]) if latest and prev else None,
            "change_yoy": yoy,
            "points": points[-120:],
        })
    return board
