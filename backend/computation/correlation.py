"""
Nexus - Cross-asset correlation matrix.

Pearson correlation of log returns across the set of tracked symbols. Input is
{symbol: [closes]} - typically the last N kline closes at a common interval.

We align series by length (tail-align) and drop any symbol with too few bars.
The matrix is symmetric with 1.0 on the diagonal; off-diagonal cells are clamped
to [-1, 1].
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple


def _log_returns(closes: List[float]) -> List[float]:
    out: List[float] = []
    for i in range(1, len(closes)):
        p0, p1 = closes[i - 1], closes[i]
        if p0 <= 0 or p1 <= 0:
            continue
        out.append(math.log(p1 / p0))
    return out


def _pearson(xs: List[float], ys: List[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    xs = xs[-n:]
    ys = ys[-n:]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = 0.0
    dx2 = 0.0
    dy2 = 0.0
    for x, y in zip(xs, ys):
        a = x - mx
        b = y - my
        num += a * b
        dx2 += a * a
        dy2 += b * b
    denom = math.sqrt(dx2 * dy2)
    if denom <= 0:
        return 0.0
    r = num / denom
    if r > 1:
        return 1.0
    if r < -1:
        return -1.0
    return r


def correlation_matrix(series: Dict[str, List[float]], min_bars: int = 20) -> Dict:
    """Compute a full symmetric correlation matrix from closes.

    Returns:
        {
          "symbols": [...],
          "matrix": [[r, ...], ...],
          "n_bars": int,     # common return length used
        }
    """
    # Convert to log returns, filter undersized series
    returns: Dict[str, List[float]] = {}
    for sym, closes in series.items():
        r = _log_returns(closes or [])
        if len(r) >= min_bars:
            returns[sym] = r

    if not returns:
        return {"symbols": [], "matrix": [], "n_bars": 0}

    # Tail-align to the shortest series so all pairs share timestamps
    common = min(len(v) for v in returns.values())
    aligned = {s: v[-common:] for s, v in returns.items()}

    symbols = sorted(aligned.keys())
    mat: List[List[float]] = []
    for a in symbols:
        row: List[float] = []
        for b in symbols:
            if a == b:
                row.append(1.0)
            else:
                row.append(round(_pearson(aligned[a], aligned[b]), 4))
        mat.append(row)

    return {"symbols": symbols, "matrix": mat, "n_bars": common}


def pairwise_sorted(matrix: Dict, limit: int = 10) -> List[Dict]:
    """Flatten the upper triangle and return top |r| pairs."""
    symbols = matrix.get("symbols", [])
    m = matrix.get("matrix", [])
    out: List[Tuple[str, str, float]] = []
    for i, a in enumerate(symbols):
        for j in range(i + 1, len(symbols)):
            b = symbols[j]
            out.append((a, b, m[i][j]))
    out.sort(key=lambda t: abs(t[2]), reverse=True)
    return [{"a": a, "b": b, "corr": c} for a, b, c in out[:limit]]
