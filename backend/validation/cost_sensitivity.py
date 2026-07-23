"""
Nexus - Cost Sensitivity Sweep

Sweeps `(fee_bps, slippage_bps)` over the configured grid and recomputes
OOS Sharpe for each combination. The plan mandates pre-promotion any
factor must maintain Sharpe ≥ 0.8 at 5 bps fees + 1 bps slippage.

Usage
-----
    from backend.validation.cost_sensitivity import sweep_costs

    report = sweep_costs(
        returns=oos_returns,
        turnover=per_bar_turnover,
        fee_grid_bps=[0, 2, 5, 10],
        slip_grid_bps=[0, 1, 5],
    )
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence


def _sharpe(returns: Sequence[float], annualization: float = math.sqrt(365)) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    return (mean / std) * annualization if std > 1e-12 else 0.0


def apply_costs(
    returns: Sequence[float],
    turnover: Sequence[float],
    fee_bps: float,
    slip_bps: float,
) -> List[float]:
    """Deduct fee+slippage proportional to bar-level turnover (∈ [0, 1+])."""
    cost_per_unit_turnover = (fee_bps + slip_bps) / 10_000.0
    out: List[float] = []
    for r, tov in zip(returns, turnover):
        out.append(r - cost_per_unit_turnover * max(0.0, float(tov)))
    return out


def sweep_costs(
    returns: Sequence[float],
    turnover: Sequence[float],
    *,
    fee_grid_bps: Sequence[float] = (0, 2, 5, 10),
    slip_grid_bps: Sequence[float] = (0, 1, 5),
    annualization: float = math.sqrt(365),
    min_acceptable_sharpe: float = 0.8,
) -> Dict:
    if len(returns) != len(turnover):
        raise ValueError("returns and turnover length mismatch")

    grid: List[Dict] = []
    for fee in fee_grid_bps:
        for slip in slip_grid_bps:
            net = apply_costs(returns, turnover, fee, slip)
            sr = _sharpe(net, annualization)
            grid.append({
                "fee_bps": fee,
                "slippage_bps": slip,
                "sharpe": round(sr, 4),
                "mean_return": round(sum(net) / len(net), 8) if net else 0.0,
                "passes_threshold": sr >= min_acceptable_sharpe,
            })

    passes = [g for g in grid if g["passes_threshold"]]
    worst = min(grid, key=lambda g: g["sharpe"]) if grid else None
    best = max(grid, key=lambda g: g["sharpe"]) if grid else None
    return {
        "grid": grid,
        "n_combinations": len(grid),
        "n_pass": len(passes),
        "worst": worst,
        "best": best,
        "min_acceptable_sharpe": min_acceptable_sharpe,
    }
