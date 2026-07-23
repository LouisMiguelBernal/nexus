"""
Nexus - Market Regime Classifier
Classifies current market into regimes for walk-forward backtesting.
Uses simple heuristics first; XGBoost model is Phase 5+.
"""

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger("nexus.regime")

REGIMES = {
    "trending_bull": "Strong uptrend with expanding volume",
    "trending_bear": "Strong downtrend with expanding volume",
    "ranging": "Sideways consolidation within defined range",
    "volatile": "High volatility without clear direction",
    "low_liq": "Low liquidity / thin order books",
}


class RegimeClassifier:
    """Classify current market regime from OHLCV data."""

    def __init__(self):
        self._current_regime = "ranging"

    def classify(
        self,
        closes: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
    ) -> Dict:
        """
        Classify regime from recent candle data.
        Expects at least 20 candles.
        """
        if len(closes) < 20:
            return {"regime": "insufficient_data", "confidence": 0}

        closes_arr = np.array(closes[-50:])
        volumes_arr = np.array(volumes[-50:])
        highs_arr = np.array(highs[-50:])
        lows_arr = np.array(lows[-50:])

        # Trend: linear regression slope on closes
        x = np.arange(len(closes_arr))
        slope = np.polyfit(x, closes_arr, 1)[0]
        slope_pct = slope / closes_arr.mean() * 100

        # Volatility: ATR as percentage of price
        atr_values = highs_arr - lows_arr
        atr_pct = np.mean(atr_values[-14:]) / closes_arr[-1] * 100

        # Volume trend
        vol_recent = np.mean(volumes_arr[-10:])
        vol_older = np.mean(volumes_arr[-30:-10]) if len(volumes_arr) >= 30 else vol_recent
        vol_expansion = vol_recent / max(vol_older, 1e-10)

        # Range: price range as % of mean
        price_range = (np.max(closes_arr[-20:]) - np.min(closes_arr[-20:])) / closes_arr.mean() * 100

        # Classify
        confidence = 0.5
        if abs(slope_pct) > 0.5 and vol_expansion > 1.2:
            regime = "trending_bull" if slope_pct > 0 else "trending_bear"
            confidence = min(0.5 + abs(slope_pct) / 5, 0.95)
        elif atr_pct > 3.0:
            regime = "volatile"
            confidence = min(0.5 + atr_pct / 10, 0.90)
        elif price_range < 2.0 and abs(slope_pct) < 0.2:
            regime = "ranging"
            confidence = 0.7
        elif vol_recent < vol_older * 0.3:
            regime = "low_liq"
            confidence = 0.6
        else:
            regime = "ranging"
            confidence = 0.5

        self._current_regime = regime

        return {
            "regime": regime,
            "description": REGIMES.get(regime, ""),
            "confidence": round(confidence, 3),
            "slope_pct": round(slope_pct, 4),
            "atr_pct": round(atr_pct, 4),
            "vol_expansion": round(vol_expansion, 3),
            "price_range_pct": round(price_range, 3),
        }
