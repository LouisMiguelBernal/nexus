"""
Nexus - Liquidation imbalance index.

Aggregates long vs short liquidation USD flow across Binance / OKX
over a trailing window and publishes an imbalance ratio:

    imbalance = (long_liq_usd - short_liq_usd) / (long_liq_usd + short_liq_usd)

Positive ⇒ long liquidations dominate (downside cascade).
Negative ⇒ short liquidations dominate (short squeeze).

Side semantics differ per exchange - we normalize to {long_liq, short_liq}:

    Binance USDT-M forceOrder:
        order side = BUY  → short liquidation (liq engine buys to cover short)
        order side = SELL → long  liquidation
    OKX liquidation-orders details.side:
        Same as Binance - it's the force-order side.
"""

from __future__ import annotations

import time
from collections import deque


def _classify_binance(side: str) -> str:
    s = (side or "").upper()
    if s == "BUY":
        return "short_liq"
    if s == "SELL":
        return "long_liq"
    return ""


def _classify_okx(side: str) -> str:
    # OKX details.side is the force-order side (same as Binance convention)
    return _classify_binance(side)


class LiquidationAggregator:
    """Windowed liquidation flow tracker across exchanges."""

    def __init__(self, symbol: str, window_seconds: int = 300, max_samples: int = 360):
        self.symbol = symbol
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        # Events: (ts_seconds, bucket, usd)
        self._events: deque[tuple[float, str, float]] = deque(maxlen=5_000)
        # Sampled series: (t, long_usd, short_usd, imbalance)
        self._samples: deque[tuple[float, float, float, float]] = deque(maxlen=max_samples)
        # Exchange cursors to avoid double counting
        self._cursors: dict[str, int] = {"binance": 0, "okx": 0}

    # ---- ingestion ------------------------------------------------------
    def _ingest_one(self, bucket: str, price: float, qty: float, ts_ms: float) -> None:
        if not bucket or price <= 0 or qty <= 0:
            return
        usd = price * qty
        ts = ts_ms / 1000.0 if ts_ms > 1e12 else float(ts_ms or time.time())
        self._events.append((ts, bucket, usd))

    def ingest_binance(self, liquidations: list[dict]) -> None:
        self._ingest_exchange("binance", liquidations, _classify_binance)

    def ingest_okx(self, liquidations: list[dict]) -> None:
        self._ingest_exchange("okx", liquidations, _classify_okx)

    def _ingest_exchange(self, name: str, liquidations: list[dict], classifier) -> None:
        cursor = self._cursors.get(name, 0)
        # Liquidations list grows append-only; new = tail beyond cursor
        new_len = len(liquidations)
        if new_len <= cursor:
            # Deque may have rolled over - fall back to last 100
            if new_len < cursor:
                cursor = max(0, new_len - 100)
            else:
                return
        for rec in list(liquidations)[cursor:]:
            bucket = classifier(rec.get("side", ""))
            price = float(rec.get("price") or 0)
            qty = float(rec.get("qty") or 0)
            ts = rec.get("time") or 0
            self._ingest_one(bucket, price, qty, ts)
        self._cursors[name] = new_len

    # ---- sampling -------------------------------------------------------
    def sample(self) -> dict:
        now = time.time()
        # Sample window for the canonical 5m metric.
        cutoff = now - self.window_seconds
        # Retention cutoff for the raw event deque - keep up to 1h so the
        # wider-window fallbacks (15m, 1h) in summary().windowed_flow() have
        # data to read. Maxlen=5000 already bounds memory.
        retention_cutoff = now - max(self.window_seconds, 3600)
        while self._events and self._events[0][0] < retention_cutoff:
            self._events.popleft()
        long_usd = 0.0
        short_usd = 0.0
        for ts, bucket, usd in self._events:
            if ts < cutoff:
                continue
            if bucket == "long_liq":
                long_usd += usd
            elif bucket == "short_liq":
                short_usd += usd
        total = long_usd + short_usd
        imb = ((long_usd - short_usd) / total) if total > 0 else 0.0
        self._samples.append((now, long_usd, short_usd, imb))
        return {
            "time": now,
            "long_usd": round(long_usd, 2),
            "short_usd": round(short_usd, 2),
            "total_usd": round(total, 2),
            "imbalance": round(imb, 4),
            "window_seconds": self.window_seconds,
        }

    def latest(self) -> dict | None:
        if not self._samples:
            return None
        t, lu, su, imb = self._samples[-1]
        return {
            "time": t,
            "long_usd": round(lu, 2),
            "short_usd": round(su, 2),
            "imbalance": round(imb, 4),
        }

    def series(self, limit: int = 180) -> list[dict]:
        data = list(self._samples)[-limit:]
        return [
            {"time": t, "long_usd": round(lu, 2), "short_usd": round(su, 2), "imbalance": round(imb, 4)}
            for t, lu, su, imb in data
        ]

    def windowed_flow(self, window_seconds: int) -> dict:
        """Compute long_usd / short_usd / imbalance directly from `_events`
        for an arbitrary lookback window (independent of `self.window_seconds`).

        Used by the multi-window summary so the frontend can fall back to a
        wider lens when the canonical 5m window is genuinely empty.
        """
        now = time.time()
        cutoff = now - window_seconds
        long_usd = 0.0
        short_usd = 0.0
        for ts, bucket, usd in self._events:
            if ts < cutoff:
                continue
            if bucket == "long_liq":
                long_usd += usd
            elif bucket == "short_liq":
                short_usd += usd
        total = long_usd + short_usd
        imb = ((long_usd - short_usd) / total) if total > 0 else None
        return {
            "window_seconds": window_seconds,
            "long_usd": round(long_usd, 2),
            "short_usd": round(short_usd, 2),
            "total_usd": round(total, 2),
            "imbalance": round(imb, 4) if imb is not None else None,
            "available": total > 0,
        }

    def summary(self) -> dict:
        if not self._samples:
            return {
                "count": 0,
                # Strict null contract: no samples = no signal, not "0%".
                "imbalance": None,
                "long_usd": None,
                "short_usd": None,
                "total_usd": None,
                "bias": "no_data",
                "cascade": False,
                "available": False,
                "windows": {
                    "5m": self.windowed_flow(300),
                    "15m": self.windowed_flow(900),
                    "1h": self.windowed_flow(3600),
                },
            }
        _, lu, su, imb = self._samples[-1]
        total = lu + su
        # Cascade: ≥ $5M total in window and |imbalance| ≥ 0.6
        cascade = bool(total >= 5_000_000 and abs(imb) >= 0.6)
        if imb >= 0.4:
            bias = "long_cascade"
        elif imb >= 0.15:
            bias = "longs_bleeding"
        elif imb <= -0.4:
            bias = "short_squeeze"
        elif imb <= -0.15:
            bias = "shorts_bleeding"
        else:
            bias = "balanced"
        # Multi-window flow: lets the UI widen the lens when 5m is quiet.
        # Each entry includes `available: bool` so frontend can swap windows.
        windows = {
            "5m": self.windowed_flow(300),
            "15m": self.windowed_flow(900),
            "1h": self.windowed_flow(3600),
        }
        # If the canonical 5m window is empty but a wider one has flow, pick
        # the smallest non-empty window as the surfaced fallback. This keeps
        # the LiqCard informative during slow markets without lying.
        active_window = "5m"
        if not windows["5m"]["available"]:
            if windows["15m"]["available"]:
                active_window = "15m"
            elif windows["1h"]["available"]:
                active_window = "1h"
        # When neither 5m nor wider has flow, surface null (not 0).
        if total <= 0 and not any(w["available"] for w in windows.values()):
            return {
                "count": len(self._samples),
                "imbalance": None,
                "long_usd": None,
                "short_usd": None,
                "total_usd": None,
                "bias": "quiet",
                "cascade": False,
                "available": False,
                "active_window": active_window,
                "windows": windows,
            }
        return {
            "count": len(self._samples),
            "imbalance": round(imb, 4),
            "long_usd": round(lu, 2),
            "short_usd": round(su, 2),
            "total_usd": round(total, 2),
            "bias": bias,
            "cascade": cascade,
            "window_seconds": self.window_seconds,
            "available": True,
            "active_window": active_window,
            "windows": windows,
        }


def nearest_liquidation_distance_pct(
    liquidations: list[dict],
    mark_price: float,
    *,
    window_s: float = 3600.0,
    band_pct: float = 0.001,
    min_usd: float = 100_000.0,
    now: float | None = None,
) -> float | None:
    """Distance (in %) from ``mark_price`` to the nearest recent liquidation cluster.

    Recent forced-order flow is bucketed into ``band_pct``-wide price bands; a
    band with at least ``min_usd`` of liquidations within ``window_s`` counts as
    a cluster. Returns ``None`` when there is nothing to measure so callers fall
    back to the squeeze meter's neutral default instead of a fake zero.

    Feeds the squeeze meter's liquidation-proximity term, which `main.py` never
    supplied before - 25 of its 100 points were structurally zero.
    """
    if mark_price <= 0 or not liquidations:
        return None
    now_s = time.time() if now is None else now
    cutoff_ms = (now_s - window_s) * 1000.0
    bands: dict[int, float] = {}
    for ev in liquidations:
        try:
            price = float(ev.get("price") or 0.0)
            ts_ms = float(ev.get("time") or 0.0)
            usd = float(ev.get("usd_value") or price * float(ev.get("qty") or 0.0))
        except (TypeError, ValueError, AttributeError):
            continue
        if price <= 0 or ts_ms < cutoff_ms:
            continue
        idx = int(round((price / mark_price - 1.0) / band_pct))
        bands[idx] = bands.get(idx, 0.0) + usd
    nearest: float | None = None
    for idx, usd in bands.items():
        if usd < min_usd:
            continue
        dist = abs(idx) * band_pct * 100.0
        if nearest is None or dist < nearest:
            nearest = dist
    return nearest
