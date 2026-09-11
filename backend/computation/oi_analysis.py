"""
Nexus - Open Interest Analysis
Tracks OI trends across exchanges and generates signals.
"""

import math
import time
import logging
from collections import deque
from typing import Dict, List, Optional

import httpx

from backend.config import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_ENDPOINTS,
    OKX_BASE,
)
from backend.ingestion.rate_guard import (
    BINANCE_FUTURES_HOST,
    record_response,
    record_success,
    should_skip,
)

logger = logging.getLogger("nexus.oi_analysis")


OI_SIGNALS = {
    "oi_rising_price_rising": "Healthy trend - new money entering long",
    "oi_rising_price_falling": "Bearish - new money entering short",
    "oi_falling_price_rising": "Short squeeze - shorts closing, weak trend",
    "oi_falling_price_falling": "Long liquidation cascade in progress",
}


class OITracker:
    """Tracks open interest across exchanges."""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self._history: deque = deque(maxlen=1000)
        self._last_oi: Dict[str, float] = {}

    async def fetch_binance_oi(self) -> Optional[float]:
        # Skip entirely while Binance has us rate-limit banned - hammering the
        # endpoint during a ban only extends it.
        if should_skip(BINANCE_FUTURES_HOST):
            return None
        try:
            url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['oi']}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={"symbol": self.symbol})
                if record_response(BINANCE_FUTURES_HOST, resp.status_code, resp.text):
                    return None
                record_success(BINANCE_FUTURES_HOST)
                data = resp.json()
                oi = float(data.get("openInterest", 0))
                self._last_oi["binance"] = oi
                return oi
        except Exception as e:
            logger.error(f"Binance OI fetch error: {e}")
            return None

    async def fetch_okx_oi(self) -> Optional[float]:
        try:
            inst_id = self.symbol.replace("USDT", "-USDT-SWAP")
            url = f"{OKX_BASE}/api/v5/public/open-interest"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={"instType": "SWAP", "instId": inst_id})
                data = resp.json()
                items = data.get("data", [])
                if items:
                    oi = float(items[0].get("oi", 0))
                    self._last_oi["okx"] = oi
                    return oi
        except Exception as e:
            logger.error(f"OKX OI fetch error: {e}")
        return None

    async def fetch_all(self) -> Dict[str, float]:
        """Fetch OI from all exchanges concurrently.

        Graceful degradation: if a venue's call fails on this tick, that
        venue is OMITTED from the snapshot total - we do NOT zero-fill
        missing venues, which would poison the rolling history with
        artificial drops every time one feed flickers. The snapshot
        records which venues actually contributed via `sources`.
        """
        import asyncio
        results = await asyncio.gather(
            self.fetch_binance_oi(),
            self.fetch_okx_oi(),
            return_exceptions=True,
        )
        venues = ("binance", "okx")
        per_venue = {}
        sources = []
        for venue, result in zip(venues, results):
            ok = isinstance(result, (int, float)) and result is not None and result > 0
            if ok:
                per_venue[venue] = float(result)
                sources.append(venue)
            else:
                # Don't fabricate - leave the field absent. UI shows N/A.
                per_venue[venue] = None

        snapshot = {
            "timestamp": time.time(),
            "binance": per_venue["binance"],
            "okx": per_venue["okx"],
            "total": sum(v for v in per_venue.values() if v is not None),
            "sources": sources,
            "venue_count": len(sources),
        }
        # Only append to rolling history if at least one venue contributed.
        # An all-empty tick would otherwise distort ROC z-score baselines.
        if sources:
            self._history.append(snapshot)
        return snapshot

    def get_trend(self, lookback_minutes: int = 60) -> Dict:
        """Analyze OI trend over the lookback period."""
        if len(self._history) < 2:
            return {"trend": "insufficient_data", "change_pct": 0}

        cutoff = time.time() - lookback_minutes * 60
        recent = [h for h in self._history if h["timestamp"] >= cutoff]
        if len(recent) < 2:
            return {"trend": "insufficient_data", "change_pct": 0}

        first_total = recent[0]["total"]
        last_total = recent[-1]["total"]
        if first_total == 0:
            return {"trend": "insufficient_data", "change_pct": 0}

        change_pct = (last_total - first_total) / first_total * 100
        trend = "rising" if change_pct > 0.5 else "falling" if change_pct < -0.5 else "flat"

        return {
            "trend": trend,
            "change_pct": round(change_pct, 3),
            "first_total": round(first_total, 2),
            "last_total": round(last_total, 2),
            "samples": len(recent),
        }

    # ------------------------------------------------------------------
    # OI-momentum factor (P1-5) - Liu & Tsyvinski (AER 2021)
    # ------------------------------------------------------------------

    def roc_zscore(self, window: str = "4h", *, baseline_window: str = "7d") -> Dict:
        """Rate-of-change z-score of total OI.

        The numerator is the log ROC over `window`; the denominator is the
        standard deviation of log ROCs over `baseline_window` - so a +2σ
        value means the current OI acceleration is two std devs above the
        recent distribution of same-window accelerations.

        Parameters are parsed as `{n}h` or `{n}d`; defaults 4h / 7d match
        the plan's factor spec.
        """
        def _parse(s: str) -> float:
            s = s.strip().lower()
            if s.endswith("h"):
                return float(s[:-1]) * 3600
            if s.endswith("d"):
                return float(s[:-1]) * 86400
            if s.endswith("m"):
                return float(s[:-1]) * 60
            return float(s)  # seconds

        w_s = _parse(window)
        base_s = _parse(baseline_window)
        now = time.time()

        if len(self._history) < 3:
            return {
                "zscore": 0.0,
                "roc_pct": 0.0,
                "window": window,
                "baseline_window": baseline_window,
                "samples": len(self._history),
                "score": 0.0,
                "direction": "flat",
                "reason": "insufficient_data",
            }

        def _oi_at(target_ts: float) -> Optional[float]:
            """Find the history sample closest to target_ts (nearest neighbor)."""
            best = None
            best_dt = None
            for h in self._history:
                dt = abs(h["timestamp"] - target_ts)
                if best_dt is None or dt < best_dt:
                    best_dt = dt
                    best = h
            return best["total"] if best else None

        current_oi = self._history[-1]["total"]
        past_oi = _oi_at(now - w_s)
        if not current_oi or not past_oi:
            return {"zscore": 0.0, "roc_pct": 0.0, "samples": len(self._history),
                    "score": 0.0, "direction": "flat", "reason": "no valid reference OI"}

        current_log_roc = math.log(current_oi / past_oi) if past_oi > 0 else 0.0

        # Build the baseline distribution of log ROCs over non-overlapping
        # windows spanning `baseline_window`.
        cutoff = now - base_s
        baseline: List[float] = []
        # Walk through history sampling roughly every `w_s` seconds.
        last_ts = None
        last_oi = None
        for h in self._history:
            if h["timestamp"] < cutoff:
                continue
            if last_ts is None or (h["timestamp"] - last_ts) >= w_s * 0.9:
                if last_oi and last_oi > 0 and h["total"] > 0:
                    baseline.append(math.log(h["total"] / last_oi))
                last_ts = h["timestamp"]
                last_oi = h["total"]

        if len(baseline) < 5:
            return {
                "zscore": 0.0,
                "roc_pct": round((math.expm1(current_log_roc)) * 100, 4),
                "window": window,
                "baseline_window": baseline_window,
                "samples": len(baseline),
                "score": 0.0,
                "direction": "flat",
                "reason": "baseline too thin",
            }

        n = len(baseline)
        mean = sum(baseline) / n
        var = sum((x - mean) ** 2 for x in baseline) / max(n - 1, 1)
        std = math.sqrt(var) if var > 0 else 0.0
        z = (current_log_roc - mean) / std if std > 1e-12 else 0.0

        roc_pct = math.expm1(current_log_roc) * 100
        # Compress to alpha-compatible [-1, +1] score.
        score = max(-1.0, min(1.0, z / 3.0))
        direction = "long" if score > 0.1 else ("short" if score < -0.1 else "flat")

        return {
            "zscore": round(z, 4),
            "roc_pct": round(roc_pct, 4),
            "window": window,
            "baseline_window": baseline_window,
            "samples": n,
            "mean_log_roc": round(mean, 6),
            "std_log_roc": round(std, 6),
            "score": round(score, 4),
            "direction": direction,
        }

    def classify_signal(self, price_change_pct: float) -> Dict:
        """
        Classify OI + price action into a signal.
        price_change_pct: price change over same period as OI lookback.
        """
        oi_trend = self.get_trend()
        oi_rising = oi_trend["change_pct"] > 0.5
        price_rising = price_change_pct > 0.1

        if oi_rising and price_rising:
            key = "oi_rising_price_rising"
        elif oi_rising and not price_rising:
            key = "oi_rising_price_falling"
        elif not oi_rising and price_rising:
            key = "oi_falling_price_rising"
        else:
            key = "oi_falling_price_falling"

        return {
            "signal": key,
            "description": OI_SIGNALS[key],
            "oi_trend": oi_trend,
            "price_change_pct": round(price_change_pct, 3),
        }
