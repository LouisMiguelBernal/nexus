"""
Nexus - Combinatorial Purged Cross-Validation (CPCV)

Reference
---------
López de Prado, M. (2018). "Advances in Financial Machine Learning",
Ch. 12. CPCV generates multiple backtest paths by leaving out every
`k-k_test` subset from a `k`-partitioned time series, purging and
embargoing neighboring observations on each side of every test block.

Compared to walk-forward, CPCV returns a *distribution* of OOS paths
instead of a single one - essential for deflated Sharpe and PBO
(Probability of Backtest Overfitting) estimation downstream.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Sequence


@dataclass
class CPCVPath:
    path_idx: int
    test_groups: List[int]
    oos_returns: List[float]
    sharpe: float


def _sharpe(returns: Sequence[float], annualization: float = math.sqrt(365)) -> float:
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std <= 1e-12:
        return 0.0
    return (mean / std) * annualization


def combinatorial_purged_cv(
    n_samples: int,
    fit: Callable[[Sequence[int]], Any],
    score: Callable[[Any, Sequence[int]], List[float]],
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo: int = 10,
    annualization: float = math.sqrt(365),
) -> Dict[str, Any]:
    """Run CPCV.

    Parameters
    ----------
    n_samples
        Total observations (index 0 … n_samples-1).
    fit / score
        Strategy closures (same contract as walk_forward).
    n_groups
        Number of equal-sized contiguous blocks to split the series into.
    n_test_groups
        Blocks held out per path. C(n_groups, n_test_groups) paths generated.
    embargo
        Observations to drop on each side of every test block (purge window
        sized to ≥ 2× max signal lookback per the plan).
    """
    if n_samples < n_groups * 2:
        return {"paths": [], "n_paths": 0, "reason": "too few samples"}

    group_size = n_samples // n_groups
    boundaries = [(g * group_size, (g + 1) * group_size if g < n_groups - 1 else n_samples)
                  for g in range(n_groups)]

    paths: List[CPCVPath] = []
    combos = list(itertools.combinations(range(n_groups), n_test_groups))

    for p_idx, test_groups in enumerate(combos):
        test_idx: List[int] = []
        for g in test_groups:
            s, e = boundaries[g]
            test_idx.extend(range(s, e))

        purged: set = set()
        for g in test_groups:
            s, e = boundaries[g]
            purged.update(range(max(0, s - embargo), min(n_samples, e + embargo)))

        train_idx = [i for i in range(n_samples) if i not in purged]
        if len(train_idx) < 30 or len(test_idx) < 5:
            continue

        model = fit(train_idx)
        oos = list(score(model, test_idx))
        paths.append(CPCVPath(
            path_idx=p_idx,
            test_groups=list(test_groups),
            oos_returns=oos,
            sharpe=_sharpe(oos, annualization),
        ))

    sharpes = [p.sharpe for p in paths]
    mean_s = sum(sharpes) / len(sharpes) if sharpes else 0.0
    var_s = (sum((s - mean_s) ** 2 for s in sharpes) / max(len(sharpes) - 1, 1)) if len(sharpes) >= 2 else 0.0

    return {
        "paths": [asdict(p) for p in paths],
        "n_paths": len(paths),
        "mean_path_sharpe": mean_s,
        "std_path_sharpe": math.sqrt(var_s) if var_s > 0 else 0.0,
        "min_path_sharpe": min(sharpes) if sharpes else 0.0,
        "max_path_sharpe": max(sharpes) if sharpes else 0.0,
        "params": {
            "n_groups": n_groups,
            "n_test_groups": n_test_groups,
            "embargo": embargo,
        },
    }
