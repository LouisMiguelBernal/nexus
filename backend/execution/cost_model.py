"""
Nexus - Transaction Cost Model

Components
----------
1. **Fees** - per-symbol, per-venue, taker/maker schedule (basis points).
2. **Market impact** - square-root model (Almgren-Chriss family):

       impact_bps = eta · sqrt(participation_rate) · sigma_bps
       participation_rate = trade_notional / ADV_notional

   where `eta` is the asset-specific impact coefficient (default 10,
   loosely calibrated to liquid USDT perps - override per symbol via
   `impact_coefficients` in config).

Separation of concerns
----------------------
This module only *estimates* cost; it does not execute. `validation/
cost_sensitivity.py` consumes `estimate_cost_bps()` to deflate OOS
Sharpes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional


# Default fee schedule in basis points. Override per-symbol at runtime.
_DEFAULT_FEES_BPS = {
    "binance": {"taker": 4.0, "maker": 2.0},
    "okx":     {"taker": 5.0, "maker": 2.0},
    "mexc":    {"taker": 5.0, "maker": 0.0},
    "blofin":  {"taker": 6.0, "maker": 2.0},
}

# Impact coefficient. η=10 on a sqrt model ≈ 3 bps at 1% ADV participation
# if sigma_bps=100 - a sane first-pass for BTC/ETH perps.
_DEFAULT_IMPACT_ETA = 10.0


@dataclass
class CostEstimate:
    fee_bps: float
    impact_bps: float
    total_bps: float
    participation_rate: float
    venue: str
    maker_or_taker: str


class CostModel:
    def __init__(
        self,
        fees_bps: Optional[Dict[str, Dict[str, float]]] = None,
        impact_coefficients: Optional[Dict[str, float]] = None,
        default_eta: float = _DEFAULT_IMPACT_ETA,
    ):
        self.fees_bps = fees_bps or dict(_DEFAULT_FEES_BPS)
        self.impact_coefficients = impact_coefficients or {}
        self.default_eta = default_eta

    def fee_bps(self, venue: str, side: str = "taker") -> float:
        schedule = self.fees_bps.get(venue.lower(), {})
        return float(schedule.get(side, 5.0))

    def impact_bps(
        self,
        symbol: str,
        trade_notional: float,
        adv_notional: float,
        sigma_bps: float,
    ) -> float:
        """Square-root impact model."""
        if adv_notional <= 0 or trade_notional <= 0:
            return 0.0
        participation = min(1.0, trade_notional / adv_notional)
        eta = float(self.impact_coefficients.get(symbol.upper(), self.default_eta))
        return eta * math.sqrt(participation) * max(sigma_bps, 0.0) / 100.0
        # /100 converts the sigma_bps · sqrt(participation) product into bps
        # of expected slippage - calibrate eta accordingly.

    def estimate_cost_bps(
        self,
        *,
        venue: str,
        maker_or_taker: str,
        symbol: str,
        trade_notional: float,
        adv_notional: float,
        sigma_bps: float,
    ) -> CostEstimate:
        fee = self.fee_bps(venue, maker_or_taker)
        impact = self.impact_bps(symbol, trade_notional, adv_notional, sigma_bps)
        participation = trade_notional / adv_notional if adv_notional > 0 else 0.0
        return CostEstimate(
            fee_bps=round(fee, 3),
            impact_bps=round(impact, 3),
            total_bps=round(fee + impact, 3),
            participation_rate=round(participation, 6),
            venue=venue,
            maker_or_taker=maker_or_taker,
        )
