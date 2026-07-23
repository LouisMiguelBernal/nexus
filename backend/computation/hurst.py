"""
Nexus - Hurst Exponent (R/S analysis)

H ∈ (0, 1). Interpretation on log-returns:
  H > 0.55  → trending / persistent (autocorrelated)
  H ≈ 0.50  → random walk (efficient market hypothesis)
  H < 0.45  → mean-reverting / anti-persistent

Uses classical Hurst R/S over multiple lag windows, log-log regressed for the
exponent. O(N log N), pure NumPy, no scipy dependency.

References
----------
- Hurst, H. E. (1951). Long-term storage capacity of reservoirs. Trans. ASCE.
- Mandelbrot & Wallis (1969). Robustness of the rescaled range R/S.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np


def _rs_at_lag(x: np.ndarray, lag: int) -> float:
    """Mean rescaled-range R/S over non-overlapping segments of length *lag*."""
    n = x.size
    n_segments = n // lag
    if n_segments < 1:
        return float("nan")
    vals: list[float] = []
    for k in range(n_segments):
        seg = x[k * lag : (k + 1) * lag]
        mean = seg.mean()
        cum = np.cumsum(seg - mean)
        R = float(cum.max() - cum.min())
        S = float(seg.std(ddof=0))
        if S > 1e-12 and R > 0:
            vals.append(R / S)
    if not vals:
        return float("nan")
    return float(np.mean(vals))


def hurst_exponent(returns: Sequence[float], min_lag: int = 8, max_lag: int = 128) -> Optional[float]:
    """Estimate Hurst via R/S analysis on a returns series.

    Returns None when the series is too short or numerically degenerate.
    Caller should treat None as "insufficient data" - we never fabricate.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    # Need at least 4 R/S samples → arr.size ≥ 4*min_lag, and lag-doubling cap
    # of arr.size // 2 will naturally bound max_lag.
    if arr.size < max(48, min_lag * 4):
        return None

    eff_max = min(max_lag, arr.size // 4)
    lags = []
    rs_vals = []
    lag = min_lag
    while lag <= eff_max:
        rs = _rs_at_lag(arr, lag)
        if math.isfinite(rs) and rs > 0:
            lags.append(lag)
            rs_vals.append(rs)
        lag = int(lag * 1.5) + 1

    if len(lags) < 4:
        return None

    log_lags = np.log(lags)
    log_rs = np.log(rs_vals)
    # Slope of log(R/S) ~ H · log(lag) - least squares without intercept-bias.
    slope, _intercept = np.polyfit(log_lags, log_rs, 1)
    H = float(slope)
    # Clamp into theoretical bounds; numerical noise can push outside [0,1].
    return max(0.0, min(1.0, H))


def hurst_score(H: Optional[float]) -> float:
    """Map Hurst H ∈ [0,1] into an alpha-compatible signal in [-1, +1].

    +1: strongly trending. 0: random walk. -1: strongly mean-reverting.
    Center at 0.5; scale so |dev| of 0.15 saturates.
    """
    if H is None:
        return 0.0
    return max(-1.0, min(1.0, (H - 0.5) / 0.15))
