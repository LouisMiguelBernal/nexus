"""
Nexus - Cross-asset correlation matrix.

Pearson correlation of log returns across the set of tracked symbols. Input is
{symbol: [closes]} - typically the last N kline closes at a common interval.

Timestamped inputs are inner-joined on open_time; plain closes fall back to
tail alignment by count. Symbols with too few bars are dropped.
The matrix is symmetric with 1.0 on the diagonal; off-diagonal cells are clamped
to [-1, 1].
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def _log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        p0, p1 = closes[i - 1], closes[i]
        if p0 <= 0 or p1 <= 0:
            continue
        out.append(math.log(p1 / p0))
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
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
    for x, y in zip(xs, ys):  # noqa: B905
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


def _to_pairs(values: Sequence[Any]) -> list[tuple[int, float]] | None:
    """Normalise one symbol's input to (open_time, close) pairs, or None for
    plain closes (legacy, count-aligned)."""
    if not values:
        return []
    first = values[0]
    if isinstance(first, dict):
        return [
            (int(v["open_time"]), float(v["close"]))
            for v in values
            if isinstance(v, dict) and v.get("open_time") is not None and v.get("close")
        ]
    if isinstance(first, (tuple, list)) and len(first) == 2:
        return [(int(t), float(c)) for t, c in values if c is not None and float(c) > 0]
    return None


def correlation_matrix(series: dict[str, Sequence[Any]], min_bars: int = 20) -> dict:
    """Compute a full symmetric correlation matrix of log returns.

    Accepted per-symbol inputs:

    - ``[close, ...]`` - legacy, aligned by count (tail-aligned to the shortest
      series). Only correct when every series is complete and ends on the same bar.
    - ``[(open_time, close), ...]`` or kline dicts - inner-joined on ``open_time``,
      so a bar missing on one symbol no longer shifts its returns against the rest.

    Returns:
        {"symbols": [...], "matrix": [[r, ...], ...], "n_bars": int,
         "aligned_by": "timestamp" | "count"}
    """
    pairs_by_symbol: dict[str, list[tuple[int, float]]] = {}
    plain_by_symbol: dict[str, list[float]] = {}
    for sym, values in series.items():
        pairs = _to_pairs(values)
        if pairs is None:
            plain_by_symbol[sym] = [float(c) for c in values]
        else:
            pairs_by_symbol[sym] = pairs

    returns: dict[str, list[float]] = {}
    if pairs_by_symbol:
        aligned_by = "timestamp"
        by_ts = {sym: dict(pairs) for sym, pairs in pairs_by_symbol.items() if len(pairs) >= min_bars + 1}
        if by_ts:
            common = sorted(set.intersection(*(set(points) for points in by_ts.values())))
            for sym, points in by_ts.items():
                r = _log_returns([points[t] for t in common])
                if len(r) >= min_bars:
                    returns[sym] = r
    else:
        aligned_by = "count"
        for sym, closes in plain_by_symbol.items():
            r = _log_returns(closes)
            if len(r) >= min_bars:
                returns[sym] = r

    if not returns:
        return {"symbols": [], "matrix": [], "n_bars": 0, "aligned_by": aligned_by}

    # Tail-align to the shortest return series (a no-op after a timestamp join).
    common_n = min(len(v) for v in returns.values())
    aligned = {s: v[-common_n:] for s, v in returns.items()}

    symbols = sorted(aligned.keys())
    mat: list[list[float]] = []
    for a in symbols:
        row: list[float] = []
        for b in symbols:
            if a == b:
                row.append(1.0)
            else:
                row.append(round(_pearson(aligned[a], aligned[b]), 4))
        mat.append(row)

    return {"symbols": symbols, "matrix": mat, "n_bars": common_n, "aligned_by": aligned_by}


def pairwise_sorted(matrix: dict, limit: int = 10) -> list[dict]:
    """Flatten the upper triangle and return top |r| pairs."""
    symbols = matrix.get("symbols", [])
    m = matrix.get("matrix", [])
    out: list[tuple[str, str, float]] = []
    for i, a in enumerate(symbols):
        for j in range(i + 1, len(symbols)):
            b = symbols[j]
            out.append((a, b, m[i][j]))
    out.sort(key=lambda t: abs(t[2]), reverse=True)
    return [{"a": a, "b": b, "corr": c} for a, b, c in out[:limit]]
