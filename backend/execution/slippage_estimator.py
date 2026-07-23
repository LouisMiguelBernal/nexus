"""
Nexus - Empirical Slippage Estimator

Fits an intraday slippage surface from observed fills vs mid. Complements
`cost_model.py` (which is a *prior* square-root model) by producing a
data-driven posterior.

Inputs are lightweight - one row per executed trade:

    {
      "symbol":      str,
      "venue":       str,
      "side":        "buy" | "sell",
      "notional":    float,   # USD notional of the fill
      "fill_price":  float,
      "mid_at_send": float,   # mid price at order submission
      "adv_notional": float,  # 24h USD volume (for participation rate),
      "ts":          float,   # unix seconds (optional),
    }

Output: fitted coefficients (intercept + slope on sqrt(participation))
plus goodness-of-fit. The slope maps 1-to-1 to the `eta` parameter in
`CostModel.impact_bps`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


@dataclass
class SlippageFit:
    n: int
    alpha_bps: float          # intercept
    eta: float                # slope on sqrt(participation)
    r_squared: float
    residual_std_bps: float


def _signed_slippage_bps(fill_price: float, mid: float, side: str) -> float:
    if mid <= 0 or fill_price <= 0:
        return 0.0
    sign = 1.0 if side == "buy" else -1.0
    # Positive value = price moved *against* the taker.
    return sign * (fill_price - mid) / mid * 10_000.0


def fit_slippage(trades: Sequence[Dict]) -> Optional[SlippageFit]:
    """OLS fit: slippage_bps ~ alpha + eta · sqrt(participation)."""
    xs: List[float] = []
    ys: List[float] = []
    for t in trades:
        notional = float(t.get("notional", 0.0))
        adv = float(t.get("adv_notional", 0.0))
        if notional <= 0 or adv <= 0:
            continue
        participation = min(1.0, notional / adv)
        xs.append(math.sqrt(participation))
        ys.append(_signed_slippage_bps(
            float(t["fill_price"]), float(t["mid_at_send"]), str(t["side"])
        ))

    n = len(xs)
    if n < 10:
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 1e-12:
        return None
    eta = sxy / sxx
    alpha = mean_y - eta * mean_x

    preds = [alpha + eta * x for x in xs]
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, preds))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    resid_std = math.sqrt(ss_res / max(n - 2, 1))

    return SlippageFit(
        n=n,
        alpha_bps=round(alpha, 4),
        eta=round(eta, 4),
        r_squared=round(r2, 4),
        residual_std_bps=round(resid_std, 4),
    )


def predict_slippage_bps(fit: SlippageFit, participation: float) -> float:
    p = max(0.0, min(1.0, participation))
    return fit.alpha_bps + fit.eta * math.sqrt(p)
