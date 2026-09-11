"""
Nexus - Realized vs Implied Volatility Spread.

Computes:
  - Realized vol (RV): annualized stdev of log returns over a closes series
  - Implied vol (IV): Deribit DVOL index (or any externally provided annualized %)
  - Spread = IV − RV (percentage points, both annualized)

A persistently positive spread ⇒ options are pricing fear above what spot has
delivered (premium-seller environment). Persistently negative ⇒ spot is more
volatile than options expect (premium-buyer environment).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional


_SECONDS_PER_YEAR = 365 * 24 * 3600


def _interval_seconds(interval: str) -> int:
    unit = interval[-1].lower()
    try:
        n = int(interval[:-1])
    except ValueError:
        return 900
    if unit == "m":
        return n * 60
    if unit == "h":
        return n * 3600
    if unit == "d":
        return n * 86400
    return 900


def realized_volatility(closes: List[float], interval: str = "15m") -> Optional[float]:
    """Annualized realized vol (%), Parkinson-free close-to-close estimator."""
    if not closes or len(closes) < 8:
        return None
    rets: List[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev <= 0 or cur <= 0:
            continue
        rets.append(math.log(cur / prev))
    if len(rets) < 4:
        return None
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1 if n > 1 else 1)
    std_per_bar = math.sqrt(var)
    bars_per_year = _SECONDS_PER_YEAR / max(1, _interval_seconds(interval))
    return std_per_bar * math.sqrt(bars_per_year) * 100.0


def compute_spread(
    closes: List[float],
    iv_pct: Optional[float],
    interval: str = "15m",
) -> Dict:
    """Return {rv, iv, spread, regime} where all vols are annualized percent."""
    rv = realized_volatility(closes, interval=interval)
    if rv is None or iv_pct is None:
        return {
            "rv": rv,
            "iv": iv_pct,
            "spread": None,
            "regime": "insufficient_data",
            "interval": interval,
            "sample_size": len(closes),
        }
    spread = iv_pct - rv
    # Classify
    if spread >= 15:
        regime = "iv_rich"            # premium sellers favored
    elif spread >= 5:
        regime = "iv_premium"
    elif spread <= -15:
        regime = "iv_cheap"            # premium buyers favored (spot whippy)
    elif spread <= -5:
        regime = "iv_discount"
    else:
        regime = "fair"
    return {
        "rv": round(rv, 2),
        "iv": round(iv_pct, 2),
        "spread": round(spread, 2),
        "regime": regime,
        "interval": interval,
        "sample_size": len(closes),
    }
