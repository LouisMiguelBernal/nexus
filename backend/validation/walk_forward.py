"""
Nexus - Walk-Forward Validation (anchored expanding window)

Train on an expanding window (min `train_min_days`), test on the next
`test_days`, step forward by `step_days`, with an `embargo_days` gap
between train and test to prevent label leakage.

Signature is strategy-agnostic: caller supplies a `fit(train_df)` →
`model` and `score(model, test_df)` → pnl-series closure. Returns per-
fold performance plus aggregate stats.

Reference
---------
López de Prado, M. (2018). "Advances in Financial Machine Learning",
Ch. 7. Embargo rationale: Ch. 7 §3.2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Protocol, Sequence


class _HasIndex(Protocol):
    def __getitem__(self, key: Any) -> Any: ...
    def __len__(self) -> int: ...


@dataclass
class Fold:
    fold_idx: int
    train_start: float
    train_end: float
    test_start: float
    test_end: float
    n_train: int
    n_test: int
    sharpe: float
    mean_return: float
    std_return: float
    hit_rate: float
    pnl_sum: float


def _sharpe(returns: Sequence[float], annualization: float = math.sqrt(365)) -> float:
    """Annualized Sharpe (daily-bar convention; caller scales annualization)."""
    if not returns:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    if n < 2:
        return 0.0
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std <= 1e-12:
        return 0.0
    return (mean / std) * annualization


def walk_forward(
    timestamps: Sequence[float],
    fit: Callable[[Sequence[int]], Any],
    score: Callable[[Any, Sequence[int]], List[float]],
    *,
    train_min_days: float = 90.0,
    test_days: float = 30.0,
    step_days: float = 7.0,
    embargo_days: float = 5.0,
    annualization: float = math.sqrt(365),
) -> Dict[str, Any]:
    """Execute anchored walk-forward validation.

    Parameters
    ----------
    timestamps
        Sorted unix timestamps for each observation. Length must equal the
        sample count the `fit` / `score` closures consume.
    fit(train_indices) -> model
        Trains on the integer indices provided; returns an opaque model.
    score(model, test_indices) -> list[float]
        Returns per-bar pnl or return series for the test window.

    Returns
    -------
    {
      "folds":        [Fold, ...],
      "oos_returns":  [flat concatenated test returns],
      "oos_sharpe":   annualized Sharpe of concatenated OOS stream,
      "mean_fold_sharpe": ...,
      "hit_rate":     overall hit rate,
      "n_folds":      int,
    }
    """
    if not timestamps:
        return {"folds": [], "oos_returns": [], "oos_sharpe": 0.0, "n_folds": 0}

    day_s = 86400.0
    t0 = timestamps[0]
    t_end = timestamps[-1]

    folds: List[Fold] = []
    oos_all: List[float] = []
    train_end_t = t0 + train_min_days * day_s

    fold_idx = 0
    while train_end_t + (embargo_days + test_days) * day_s <= t_end:
        test_start_t = train_end_t + embargo_days * day_s
        test_end_t = test_start_t + test_days * day_s

        train_idx = [i for i, t in enumerate(timestamps) if t0 <= t < train_end_t]
        test_idx = [i for i, t in enumerate(timestamps) if test_start_t <= t < test_end_t]

        if len(train_idx) < 30 or len(test_idx) < 5:
            train_end_t += step_days * day_s
            continue

        model = fit(train_idx)
        test_returns = list(score(model, test_idx))
        oos_all.extend(test_returns)

        mean_r = sum(test_returns) / len(test_returns) if test_returns else 0.0
        fold_std = (
            math.sqrt(sum((r - mean_r) ** 2 for r in test_returns) / max(len(test_returns) - 1, 1))
            if len(test_returns) >= 2 else 0.0
        )
        hit = sum(1 for r in test_returns if r > 0) / len(test_returns) if test_returns else 0.0

        folds.append(Fold(
            fold_idx=fold_idx,
            train_start=t0,
            train_end=train_end_t,
            test_start=test_start_t,
            test_end=test_end_t,
            n_train=len(train_idx),
            n_test=len(test_idx),
            sharpe=_sharpe(test_returns, annualization),
            mean_return=mean_r,
            std_return=fold_std,
            hit_rate=hit,
            pnl_sum=sum(test_returns),
        ))

        fold_idx += 1
        train_end_t += step_days * day_s

    overall_hit = sum(1 for r in oos_all if r > 0) / len(oos_all) if oos_all else 0.0
    mean_fold_sharpe = sum(f.sharpe for f in folds) / len(folds) if folds else 0.0

    return {
        "folds": [asdict(f) for f in folds],
        "oos_returns": oos_all,
        "oos_sharpe": _sharpe(oos_all, annualization),
        "mean_fold_sharpe": mean_fold_sharpe,
        "hit_rate": overall_hit,
        "n_folds": len(folds),
        "params": {
            "train_min_days": train_min_days,
            "test_days": test_days,
            "step_days": step_days,
            "embargo_days": embargo_days,
        },
    }
