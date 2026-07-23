"""
Nexus - Vol-Scaled Time-Series Momentum (TSMOM)

Reference
---------
Moskowitz, T., Ooi, Y., Pedersen, L. (2012).
"Time Series Momentum". Journal of Financial Economics 104(2).

Signal
------
    raw    = sign(r_{t−12m ··· t−1m})               # skip-one formation
    scale  = target_vol_annual / realized_vol_annual
    signal = raw · clamp(scale, 0, max_scale)        ∈ [-max_scale, +max_scale]

For crypto perps we compress the formation window from months to hours
(the microstructure equivalent of the cross-asset 12-1m rule):

    formation : last `formation_hours` of returns, excluding the last
                `skip_hours` (default 12h formation, 1h skip on 1h bars).
    realized_vol : std of `vol_hours` of returns, annualized.

Target vol
----------
target_vol = 0.15 (annualized, equivalent to 15 %). Consistent with AQR /
Pedersen vol-targeting - crypto-specific levels (e.g. 0.50) can be passed
by callers; 0.15 matches the plan's reference parameterization.

Output contract (alpha_engine-compatible)
-----------------------------------------
    {
      "score":      [-1, +1] (tanh-saturated at max_scale),
      "raw":        signed formation return,
      "scale":      vol_target / realized_vol,
      "realized_vol_annual": ...,
      "target_vol": ...,
      "confidence": [0, 1] based on sample sufficiency,
      "direction":  "long" | "short" | "flat",
    }
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

# Annualization for hourly bars: sqrt(24 · 365) ≈ 93.3
_HOURLY_ANNUALIZATION = math.sqrt(24 * 365)


def _returns_from_closes(closes: Sequence[float]) -> List[float]:
    out: List[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev > 0:
            out.append((curr - prev) / prev)
    return out


def _std(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)  # sample std
    return math.sqrt(var) if var > 0 else 0.0


def compute_tsmom(
    closes_1h: Sequence[float],
    *,
    formation_hours: int = 12,
    skip_hours: int = 1,
    vol_hours: int = 72,
    target_vol_annual: float = 0.15,
    max_scale: float = 2.0,
) -> Dict:
    """Vol-scaled TSMOM on 1h closes.

    Parameters
    ----------
    closes_1h
        Sequence of 1h close prices (oldest → newest). Must be at least
        max(formation_hours + skip_hours + 1, vol_hours + 1) long for a
        valid signal.
    """
    need = max(formation_hours + skip_hours + 1, vol_hours + 1)
    if len(closes_1h) < need:
        return {
            "score": 0.0,
            "raw": 0.0,
            "scale": 0.0,
            "realized_vol_annual": 0.0,
            "target_vol": target_vol_annual,
            "confidence": 0.0,
            "direction": "flat",
            "reason": f"insufficient bars ({len(closes_1h)} < {need})",
        }

    # Formation return: from closes[-(formation+skip+1)] to closes[-(skip+1)].
    p_start = closes_1h[-(formation_hours + skip_hours + 1)]
    p_end = closes_1h[-(skip_hours + 1)]
    if p_start <= 0:
        return {
            "score": 0.0,
            "raw": 0.0,
            "scale": 0.0,
            "realized_vol_annual": 0.0,
            "target_vol": target_vol_annual,
            "confidence": 0.0,
            "direction": "flat",
            "reason": "invalid formation price",
        }
    formation_return = (p_end - p_start) / p_start

    rets = _returns_from_closes(closes_1h[-vol_hours - 1:])
    realized_vol_h = _std(rets)
    realized_vol_annual = realized_vol_h * _HOURLY_ANNUALIZATION

    if realized_vol_annual <= 1e-8:
        return {
            "score": 0.0,
            "raw": round(formation_return, 6),
            "scale": 0.0,
            "realized_vol_annual": 0.0,
            "target_vol": target_vol_annual,
            "confidence": 0.0,
            "direction": "flat",
            "reason": "flat realized vol",
        }

    raw_sign = 1.0 if formation_return > 0 else (-1.0 if formation_return < 0 else 0.0)
    scale = max(0.0, min(max_scale, target_vol_annual / realized_vol_annual))
    signed = raw_sign * scale
    # Saturate to [-1, +1] for the alpha composite (composite weights expect
    # unit-bounded scores; callers that want the raw scaled sizing read `scale`).
    score = max(-1.0, min(1.0, signed / max_scale))

    confidence = min(1.0, len(closes_1h) / (need * 2))
    direction = "long" if signed > 0 else ("short" if signed < 0 else "flat")

    return {
        "score": round(score, 4),
        "raw": round(formation_return, 6),
        "scale": round(scale, 4),
        "realized_vol_annual": round(realized_vol_annual, 6),
        "target_vol": target_vol_annual,
        "confidence": round(confidence, 4),
        "direction": direction,
        "formation_hours": formation_hours,
        "skip_hours": skip_hours,
        "vol_hours": vol_hours,
    }


def tsmom_portfolio(
    closes_by_symbol: Dict[str, Sequence[float]],
    **kwargs,
) -> Dict[str, Dict]:
    """Convenience: run TSMOM across a universe. Returns `{symbol: compute_tsmom(...)}`."""
    return {sym: compute_tsmom(closes, **kwargs) for sym, closes in closes_by_symbol.items()}
