"""
Nexus - Cumulative Volume Delta (CVD) Computation
Computed from Binance aggTrade stream.
buyer_maker=True → sell pressure (passive buyer)
buyer_maker=False → buy pressure (aggressive buyer / taker)
"""

import time
import logging
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nexus.cvd")


class CVDComputer:
    """Computes CVD and detects divergence from price."""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        # Store raw deltas with timestamps for multi-timeframe
        self._deltas: deque = deque(maxlen=50000)

    def ingest_trade(self, price: float, qty: float, is_buyer_maker: bool, timestamp_ms: int):
        """
        Ingest a single aggregated trade.
        is_buyer_maker=True → sell pressure (taker sold)
        is_buyer_maker=False → buy pressure (taker bought)
        """
        usd_value = price * qty
        delta = -usd_value if is_buyer_maker else usd_value
        self._deltas.append({
            "delta": delta,
            "price": price,
            "qty": qty,
            "usd": usd_value,
            "ts": timestamp_ms,
        })

    def ingest_trades_batch(self, trades: list):
        """Ingest multiple trades from the data store."""
        for t in trades:
            self.ingest_trade(
                price=t["price"],
                qty=t["qty"],
                is_buyer_maker=t["is_buyer_maker"],
                timestamp_ms=t["time"],
            )

    def get_cvd(self, timeframe_minutes: int = 60) -> Dict:
        """
        Compute CVD for a given timeframe window.
        Returns cumulative delta, buy volume, sell volume, net.

        Strict null contract: when there is no data, every numeric metric is
        `None` and `available=False`. Distinguishes "no flow" (real signal,
        zeros) from "no data" (cold start / stalled feed).
        """
        if not self._deltas:
            return {"cvd": None, "buy_volume": None, "sell_volume": None,
                    "net_delta": None, "trade_count": 0, "available": False}

        cutoff = (time.time() - timeframe_minutes * 60) * 1000
        relevant = [d for d in self._deltas if d["ts"] >= cutoff]

        if not relevant:
            return {"cvd": None, "buy_volume": None, "sell_volume": None,
                    "net_delta": None, "trade_count": 0, "available": False}

        buy_vol = sum(d["usd"] for d in relevant if d["delta"] > 0)
        sell_vol = sum(d["usd"] for d in relevant if d["delta"] < 0)
        cvd = sum(d["delta"] for d in relevant)

        return {
            "cvd": round(cvd, 2),
            "buy_volume": round(buy_vol, 2),
            "sell_volume": round(abs(sell_vol), 2),
            "net_delta": round(cvd, 2),
            "trade_count": len(relevant),
            "available": True,
        }

    def get_multi_timeframe(self) -> Dict[str, Dict]:
        """Get CVD across multiple timeframes."""
        return {
            "5m": self.get_cvd(5),
            "15m": self.get_cvd(15),
            "1h": self.get_cvd(60),
            "4h": self.get_cvd(240),
        }

    def get_cvd_histogram(self, timeframe_minutes: int = 60, bins: int = 30) -> List[Dict]:
        """Get CVD as time-bucketed histogram for charting."""
        if not self._deltas:
            return []

        cutoff = (time.time() - timeframe_minutes * 60) * 1000
        relevant = [d for d in self._deltas if d["ts"] >= cutoff]

        if not relevant:
            return []

        min_ts = relevant[0]["ts"]
        max_ts = relevant[-1]["ts"]
        if min_ts == max_ts:
            return [{"time": min_ts, "buy": 0, "sell": 0, "net": 0}]

        bin_size = (max_ts - min_ts) / bins
        histogram = []
        for i in range(bins):
            bin_start = min_ts + i * bin_size
            bin_end = bin_start + bin_size
            bin_trades = [d for d in relevant if bin_start <= d["ts"] < bin_end]
            buy = sum(d["usd"] for d in bin_trades if d["delta"] > 0)
            sell = sum(d["usd"] for d in bin_trades if d["delta"] < 0)
            histogram.append({
                "time": int(bin_start),
                "buy": round(buy, 2),
                "sell": round(abs(sell), 2),
                "net": round(buy - abs(sell), 2),
            })

        return histogram

    def detect_divergence(self, prices: List[float], timeframe_minutes: int = 60) -> Optional[Dict]:
        """
        Detect CVD divergence from price action.
        - Bearish: price rising + CVD flat/falling = manufactured pump
        - Bullish: price falling + CVD rising = absorption, smart money buying
        """
        cvd_data = self.get_cvd(timeframe_minutes)
        if not prices or len(prices) < 2:
            return None

        price_change = (prices[-1] - prices[0]) / prices[0]
        cvd_val = cvd_data["cvd"]

        # Normalize CVD relative to volume
        total_vol = cvd_data["buy_volume"] + cvd_data["sell_volume"]
        if total_vol == 0:
            return None
        cvd_normalized = cvd_val / total_vol  # -1 to +1

        divergence = None
        if price_change > 0.002 and cvd_normalized < -0.1:
            divergence = {
                "type": "bearish_divergence",
                "description": "Price rising + CVD falling = manufactured pump, no real buyers",
                "leverage_context": "High liquidation risk for longs near resistance",
                "price_change_pct": round(price_change * 100, 3),
                "cvd_normalized": round(cvd_normalized, 4),
                "strength": min(abs(cvd_normalized) * 100, 100),
            }
        elif price_change < -0.002 and cvd_normalized > 0.1:
            divergence = {
                "type": "bullish_divergence",
                "description": "Price falling + CVD rising = absorption, smart money buying dip",
                "leverage_context": "Short squeeze risk if support holds",
                "price_change_pct": round(price_change * 100, 3),
                "cvd_normalized": round(cvd_normalized, 4),
                "strength": min(abs(cvd_normalized) * 100, 100),
            }

        return divergence
