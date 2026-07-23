"""
Nexus - Cross-Asset Correlation Matrix
Computes rolling correlation between crypto assets for portfolio risk.
"""

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger("nexus.correlation")


def compute_correlation_matrix(
    returns_by_symbol: Dict[str, List[float]],
    window: int = 30,
) -> Dict:
    """
    Compute pairwise correlation matrix from daily returns.

    Args:
        returns_by_symbol: {"BTCUSDT": [0.01, -0.02, ...], "ETHUSDT": [...]}
        window: Rolling window in days
    """
    symbols = list(returns_by_symbol.keys())
    if len(symbols) < 2:
        return {"error": "Need at least 2 symbols"}

    # Align to shortest series
    min_len = min(len(r) for r in returns_by_symbol.values())
    if min_len < window:
        return {"error": f"Insufficient data: {min_len} < {window} required"}

    matrix_data = np.array([
        returns_by_symbol[s][-window:] for s in symbols
    ])

    corr_matrix = np.corrcoef(matrix_data)

    result = {"symbols": symbols, "pairs": {}}
    for i, s1 in enumerate(symbols):
        for j, s2 in enumerate(symbols):
            if i < j:
                corr = corr_matrix[i][j]
                result["pairs"][f"{s1}/{s2}"] = round(float(corr), 4)

    # Average correlation (portfolio diversification measure)
    pair_corrs = list(result["pairs"].values())
    result["avg_correlation"] = round(np.mean(pair_corrs), 4) if pair_corrs else 0
    result["diversification_score"] = round(1 - abs(result["avg_correlation"]), 4)

    return result
