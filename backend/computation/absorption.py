"""
Nexus - Order Absorption Detection
Detects large orders being filled without moving price (smart money accumulation).
"""

import time
import logging
from collections import deque
from typing import Dict, List, Optional

logger = logging.getLogger("nexus.absorption")


class AbsorptionDetector:
    """Detects absorption patterns from trade flow data."""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self._windows: deque = deque(maxlen=500)  # Rolling 1-second windows

    def analyze_window(
        self,
        trades: list,
        price_start: float,
        price_end: float,
        window_seconds: int = 5,
    ) -> Optional[Dict]:
        """
        Analyze a time window for absorption.
        Absorption = high volume + minimal price movement.
        """
        if not trades or price_start <= 0:
            return None

        total_volume = sum(t.get("usd", t.get("qty", 0) * t.get("price", 0)) for t in trades)
        buy_volume = sum(
            t.get("usd", t.get("qty", 0) * t.get("price", 0))
            for t in trades if not t.get("is_buyer_maker", True)
        )
        sell_volume = total_volume - buy_volume
        price_change_pct = abs(price_end - price_start) / price_start * 100

        # Absorption: high volume relative to price movement
        if total_volume == 0 or price_change_pct > 0.05:
            return None

        volume_per_pct = total_volume / max(price_change_pct, 0.001)

        window_data = {
            "timestamp": time.time(),
            "total_volume": total_volume,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "price_change_pct": price_change_pct,
            "volume_per_pct": volume_per_pct,
        }
        self._windows.append(window_data)

        # Check if this window is exceptional (top 10% by volume/pct ratio)
        if len(self._windows) < 10:
            return None

        ratios = sorted([w["volume_per_pct"] for w in self._windows], reverse=True)
        threshold_90 = ratios[max(len(ratios) // 10, 1)]

        if volume_per_pct >= threshold_90:
            side = "bid_absorption" if buy_volume > sell_volume else "ask_absorption"
            return {
                "type": side,
                "description": f"Large {'buying' if side == 'bid_absorption' else 'selling'} absorbed without price impact",
                "total_volume_usd": round(total_volume, 2),
                "price_change_pct": round(price_change_pct, 5),
                "buy_sell_ratio": round(buy_volume / max(sell_volume, 1), 3),
                "strength": min(volume_per_pct / threshold_90, 5.0),
                "price": price_end,
            }
        return None
