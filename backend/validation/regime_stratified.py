"""
Nexus - Regime-Stratified Purged K-Fold

Stratifies folds by `regime.classify()` label so each fold contains a
representative mix of regimes. Combines the purge + embargo discipline
from López de Prado (2018) with stratified sampling to avoid the
"train on bull, test on bear" pathology.

Inputs are index-based and deterministic given the same regime labels
and seed.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RegimeFold:
    fold_idx: int
    train_indices: list[int]
    test_indices: list[int]
    regime_distribution_train: dict[str, int]
    regime_distribution_test: dict[str, int]


def _regime_counts(labels: Sequence[str], idx: Sequence[int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in idx:
        lbl = labels[i]
        counts[lbl] = counts.get(lbl, 0) + 1
    return counts


def regime_stratified_kfold(
    regime_labels: Sequence[str],
    *,
    k: int = 5,
    embargo: int = 10,
    seed: int = 42,
) -> list[RegimeFold]:
    """Build `k` regime-stratified folds with purge + embargo.

    Algorithm
    ---------
    1. Group observation indices by regime label.
    2. Shuffle each group and distribute round-robin into `k` test buckets.
    3. For each fold, `test = bucket_j`, `train = all_other_buckets` after
       excluding any index within `embargo` steps of the test block (purge).
    """
    n = len(regime_labels)
    if n == 0 or k < 2:
        return []

    rng = random.Random(seed)

    groups: dict[str, list[int]] = {}
    for i, lbl in enumerate(regime_labels):
        groups.setdefault(lbl, []).append(i)

    buckets: list[list[int]] = [[] for _ in range(k)]
    for lbl, idxs in groups.items():  # noqa: B007
        shuffled = list(idxs)
        rng.shuffle(shuffled)
        for j, idx in enumerate(shuffled):
            buckets[j % k].append(idx)

    folds: list[RegimeFold] = []
    for j in range(k):
        test_set = set(buckets[j])

        # Purge: drop any non-test index within `embargo` steps of any test idx.
        purged: set = set()
        if embargo > 0 and test_set:
            sorted_test = sorted(test_set)
            for t in sorted_test:
                for d in range(-embargo, embargo + 1):
                    purged.add(t + d)

        train = [i for i in range(n) if i not in test_set and i not in purged]
        test = sorted(test_set)

        folds.append(
            RegimeFold(
                fold_idx=j,
                train_indices=train,
                test_indices=test,
                regime_distribution_train=_regime_counts(regime_labels, train),
                regime_distribution_test=_regime_counts(regime_labels, test),
            )
        )

    return folds


def run_regime_stratified(
    regime_labels: Sequence[str],
    fit: Callable[[Sequence[int]], Any],
    score: Callable[[Any, Sequence[int]], list[float]],
    *,
    k: int = 5,
    embargo: int = 10,
    seed: int = 42,
) -> dict[str, Any]:
    """Build folds and evaluate. Returns per-fold returns + aggregate stats."""
    folds = regime_stratified_kfold(regime_labels, k=k, embargo=embargo, seed=seed)
    all_returns: list[float] = []
    fold_reports: list[dict[str, Any]] = []
    for fold in folds:
        model = fit(fold.train_indices)
        r = list(score(model, fold.test_indices))
        all_returns.extend(r)
        fold_reports.append(
            {
                **asdict(fold),
                "mean_return": (sum(r) / len(r)) if r else 0.0,
                "n_test_returns": len(r),
            }
        )

    hit = sum(1 for x in all_returns if x > 0) / len(all_returns) if all_returns else 0.0
    return {
        "folds": fold_reports,
        "all_returns": all_returns,
        "hit_rate": hit,
        "k": k,
        "embargo": embargo,
    }
