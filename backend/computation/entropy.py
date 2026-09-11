"""
Nexus - Market Entropy

Shannon entropy of return-sign sequence over a rolling window. Combined with
Hurst, gives a 2D regime map:

  low entropy  + high |drift|  → strong trend
  low entropy  + low  |drift|  → range with structure
  high entropy + any drift     → choppy / unpredictable

Normalized to [0, 1] so it composes with other layer scores cleanly.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np


def _shannon(probs: np.ndarray) -> float:
    p = probs[probs > 0]
    if p.size == 0:
        return 0.0
    return float(-(p * np.log2(p)).sum())


def sign_entropy(returns: Sequence[float], k_bins: int = 3) -> Optional[float]:
    """Normalized entropy of return *signs* (down/flat/up) over the window.

    k_bins=3 (down/flat/up). Flat bucket uses tolerance = 0.1·σ to avoid
    classifying every micro-tick as a unique event. Returns None on empty.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 8:
        return None
    sigma = float(arr.std(ddof=0))
    tol = 0.1 * sigma
    up = (arr > tol).sum()
    dn = (arr < -tol).sum()
    flat = arr.size - up - dn
    counts = np.array([dn, flat, up], dtype=float)
    probs = counts / counts.sum()
    H = _shannon(probs)
    H_max = math.log2(k_bins)
    return float(H / H_max) if H_max > 0 else 0.0


def entropy_score(H_norm: Optional[float]) -> float:
    """Map normalized entropy ∈ [0,1] to alpha layer ∈ [-1,+1].

    Low entropy = structure = +1 (trending or coherent). High entropy = chop = -1.
    Inverted because the alpha framework treats positive as "edge present".
    """
    if H_norm is None:
        return 0.0
    return max(-1.0, min(1.0, (0.6 - H_norm) / 0.3))
