"""
Nexus - Squeeze Risk Meter
Combines funding + OI + L/S ratio + liquidation density into a single
probability score for long/short cascading liquidations.
"""

import logging
import time
from typing import Dict, Optional

import httpx

from backend.config import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_ENDPOINTS,
    LS_RATIO_THRESHOLDS,
    FUNDING_THRESHOLDS,
)
from backend.ingestion.rate_guard import (
    BINANCE_FUTURES_HOST,
    record_response,
    record_success,
    should_skip,
)

logger = logging.getLogger("nexus.squeeze_risk")


class SqueezeRiskMeter:
    """Computes long/short squeeze probability."""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self._ls_ratio: Optional[float] = None
        self._top_ls_ratio: Optional[float] = None

    async def fetch_ls_ratio(self) -> Optional[float]:
        """Fetch global long/short account ratio from Binance."""
        if should_skip(BINANCE_FUTURES_HOST):
            return None
        try:
            url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['ls_ratio']}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={
                    "symbol": self.symbol,
                    "period": "5m",
                    "limit": 1,
                })
                if record_response(BINANCE_FUTURES_HOST, resp.status_code, resp.text):
                    return None
                record_success(BINANCE_FUTURES_HOST)
                data = resp.json()
                if data:
                    self._ls_ratio = float(data[-1].get("longShortRatio", 1.0))
                    return self._ls_ratio
        except Exception as e:
            logger.error(f"L/S ratio fetch error: {e}")
        return None

    async def fetch_top_trader_ls(self) -> Optional[float]:
        """Fetch top trader long/short position ratio from Binance."""
        if should_skip(BINANCE_FUTURES_HOST):
            return None
        try:
            url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['top_ls']}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={
                    "symbol": self.symbol,
                    "period": "5m",
                    "limit": 1,
                })
                if record_response(BINANCE_FUTURES_HOST, resp.status_code, resp.text):
                    return None
                record_success(BINANCE_FUTURES_HOST)
                data = resp.json()
                if data:
                    self._top_ls_ratio = float(data[-1].get("longShortRatio", 1.0))
                    return self._top_ls_ratio
        except Exception as e:
            logger.error(f"Top trader L/S error: {e}")
        return None

    # Regime multipliers - squeeze risk in chop is structurally lower (no
    # cascading momentum), in volatile regimes structurally higher (tight
    # stops + thin liquidity), in trending regimes asymmetric (against-trend
    # squeezes far more dangerous than with-trend).
    _REGIME_MULT = {
        "trending_bull": {"long": 0.85, "short": 1.20},
        "trending_bear": {"long": 1.20, "short": 0.85},
        "ranging":       {"long": 0.80, "short": 0.80},
        "volatile":      {"long": 1.25, "short": 1.25},
        "low_liq":       {"long": 1.15, "short": 1.15},
        "insufficient_data": {"long": 1.0, "short": 1.0},
    }

    def compute(
        self,
        funding_rate_pct: float,
        oi_change_pct: float,
        ls_ratio: Optional[float] = None,
        nearest_liq_distance_pct: float = 5.0,
        regime: Optional[str] = None,
        vpin: Optional[float] = None,
    ) -> Dict:
        """
        Compute squeeze risk scores.

        Args:
            funding_rate_pct: Current weighted funding rate (%)
            oi_change_pct: OI change over last hour (%)
            ls_ratio: Long/short ratio (default uses last fetched)
            nearest_liq_distance_pct: Distance to nearest liquidation cluster (%)
            regime: regime label from RegimeClassifier (P1-3 - modulates risk)
            vpin: running VPIN (0..1); >0.85 = toxic flow → amplifies squeeze
        """
        ratio = ls_ratio or self._ls_ratio or 1.0

        # --- Long squeeze risk ---
        # High when: longs crowded, funding extreme positive, OI rising (overleveraged)
        long_crowd_score = min(max((ratio - 1.0) / 0.8, 0), 1) * 30  # Max 30
        long_funding_score = min(max(funding_rate_pct / 0.10, 0), 1) * 25  # Max 25
        long_oi_score = min(max(oi_change_pct / 5.0, 0), 1) * 20  # Max 20
        long_liq_proximity = max(0, (5.0 - nearest_liq_distance_pct) / 5.0) * 25  # Max 25
        long_squeeze_risk = long_crowd_score + long_funding_score + long_oi_score + long_liq_proximity

        # --- Short squeeze risk ---
        # High when: shorts crowded, funding extreme negative, OI rising
        short_crowd_score = min(max((1.0 - ratio) / 0.45, 0), 1) * 30
        short_funding_score = min(max(-funding_rate_pct / 0.10, 0), 1) * 25
        short_oi_score = min(max(oi_change_pct / 5.0, 0), 1) * 20
        short_liq_proximity = max(0, (5.0 - nearest_liq_distance_pct) / 5.0) * 25
        short_squeeze_risk = short_crowd_score + short_funding_score + short_oi_score + short_liq_proximity

        # --- Regime modulation (P1-3) ---
        regime_key = (regime or "insufficient_data").lower()
        mult = self._REGIME_MULT.get(regime_key, self._REGIME_MULT["insufficient_data"])
        long_squeeze_risk *= mult["long"]
        short_squeeze_risk *= mult["short"]

        # --- VPIN amplification (toxic flow) ---
        if vpin is not None and vpin > 0.85:
            # Toxic flow shifts squeeze probability up symmetrically.
            amp = 1.0 + min((vpin - 0.85) / 0.15, 1.0) * 0.25
            long_squeeze_risk *= amp
            short_squeeze_risk *= amp

        long_squeeze_risk = min(long_squeeze_risk, 100)
        short_squeeze_risk = min(short_squeeze_risk, 100)

        return {
            "long_squeeze_risk_pct": round(long_squeeze_risk, 1),
            "short_squeeze_risk_pct": round(short_squeeze_risk, 1),
            "dominant_risk": "long" if long_squeeze_risk > short_squeeze_risk else "short",
            "ls_ratio": round(ratio, 3),
            "funding_rate_pct": round(funding_rate_pct, 4),
            "oi_change_pct": round(oi_change_pct, 3),
            "nearest_liq_distance_pct": round(nearest_liq_distance_pct, 2),
            "regime": regime_key,
            "regime_mult": mult,
            "vpin": round(vpin, 4) if vpin is not None else None,
            "alert_level": "critical" if max(long_squeeze_risk, short_squeeze_risk) > 70
                          else "elevated" if max(long_squeeze_risk, short_squeeze_risk) > 40
                          else "normal",
        }
