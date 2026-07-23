"""
Nexus - Liquidation Price Estimator
Accounts for cross-margin, isolated margin, and portfolio margin modes.
"""

import logging
from typing import Dict

logger = logging.getLogger("nexus.liquidation")


class MarginMode:
    ISOLATED = "isolated"
    CROSS = "cross"
    PORTFOLIO = "portfolio"


def estimate_liquidation_price(
    entry_price: float,
    leverage: float,
    position_side: str,  # "LONG" or "SHORT"
    margin_mode: str = MarginMode.ISOLATED,
    maintenance_margin_rate: float = 0.004,  # Binance default for BTC
    wallet_balance: float = 0.0,  # For cross/portfolio margin
    total_position_margin: float = 0.0,  # Margin allocated to this position
) -> Dict:
    """
    Estimate liquidation price for a leveraged position.

    For ISOLATED:
        LONG:  liq = entry * (1 - 1/leverage + mmr)
        SHORT: liq = entry * (1 + 1/leverage - mmr)

    For CROSS/PORTFOLIO:
        Uses wallet_balance as the full margin pool.
        Liq is further away because more collateral backs the position.
    """
    if leverage <= 0 or entry_price <= 0:
        return {"liquidation_price": 0, "error": "Invalid inputs"}

    mmr = maintenance_margin_rate
    side = position_side.upper()

    if margin_mode == MarginMode.ISOLATED:
        if side == "LONG":
            liq_price = entry_price * (1 - 1 / leverage + mmr)
        else:
            liq_price = entry_price * (1 + 1 / leverage - mmr)
    else:
        # Cross/Portfolio: effective leverage is lower due to shared collateral
        position_notional = entry_price * (total_position_margin * leverage) / entry_price if total_position_margin > 0 else entry_price
        effective_margin_ratio = wallet_balance / max(position_notional, 1)

        if side == "LONG":
            liq_price = entry_price * (1 - effective_margin_ratio + mmr)
        else:
            liq_price = entry_price * (1 + effective_margin_ratio - mmr)

    # Distance from entry to liquidation
    distance_pct = abs(liq_price - entry_price) / entry_price * 100

    return {
        "liquidation_price": round(liq_price, 2),
        "entry_price": entry_price,
        "leverage": leverage,
        "side": side,
        "margin_mode": margin_mode,
        "distance_pct": round(distance_pct, 4),
        "maintenance_margin_rate": mmr,
        "safe_at_current_price": True,  # Caller should compare with current price
    }


def compute_leverage_utilisation(
    total_collateral: float,
    total_position_notional: float,
    maintenance_margin_total: float,
) -> Dict:
    """
    Compute portfolio-level leverage utilisation.

    Returns:
        effective_leverage: position_value / collateral
        margin_ratio: maintenance_margin / collateral
        liquidation_buffer: how much more room before liquidation
    """
    if total_collateral <= 0:
        return {"error": "No collateral", "effective_leverage": 0}

    effective_leverage = total_position_notional / total_collateral
    margin_ratio = maintenance_margin_total / total_collateral
    liquidation_buffer = 1.0 - margin_ratio
    max_additional = total_collateral * (1 - margin_ratio) * 0.7  # 70% safety factor

    return {
        "total_collateral_usd": round(total_collateral, 2),
        "total_position_notional_usd": round(total_position_notional, 2),
        "effective_leverage": round(effective_leverage, 2),
        "margin_ratio": round(margin_ratio, 4),
        "margin_ratio_pct": round(margin_ratio * 100, 2),
        "liquidation_buffer_pct": round(liquidation_buffer * 100, 2),
        "max_additional_position_usd": round(max_additional, 2),
        "health": (
            "critical" if margin_ratio > 0.8
            else "warning" if margin_ratio > 0.6
            else "elevated" if margin_ratio > 0.4
            else "healthy"
        ),
    }
