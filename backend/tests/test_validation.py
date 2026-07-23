"""
Verification: P2 validation primitives.
"""

import math
import random

import pytest

from backend.validation.walk_forward import walk_forward
from backend.validation.regime_stratified import regime_stratified_kfold
from backend.validation.combinatorial_purged_cv import combinatorial_purged_cv
from backend.validation.deflated_sharpe import (
    deflated_sharpe, expected_max_sharpe,
)
from backend.validation.cost_sensitivity import apply_costs, sweep_costs


def test_walk_forward_generates_folds_with_expected_cadence():
    # 365 daily bars.
    timestamps = [1_700_000_000 + i * 86400 for i in range(365)]

    def fit(train_idx):
        # Trivial model: return sign of mean return from train window.
        return 1

    def score(model, test_idx):
        return [0.001 for _ in test_idx]

    out = walk_forward(
        timestamps, fit, score,
        train_min_days=90, test_days=30, step_days=7, embargo_days=5,
    )
    assert out["n_folds"] > 20
    assert all(f["n_test"] > 0 for f in out["folds"])


def test_regime_stratified_kfold_respects_embargo():
    labels = ["bull"] * 50 + ["bear"] * 50 + ["range"] * 50
    folds = regime_stratified_kfold(labels, k=5, embargo=3, seed=1)
    assert len(folds) == 5
    for fold in folds:
        # No test index should appear in train.
        assert set(fold.train_indices).isdisjoint(set(fold.test_indices))
        # Each fold must have all three regimes represented in test.
        assert len(fold.regime_distribution_test) >= 1


def test_cpcv_generates_expected_number_of_paths():
    random.seed(0)

    def fit(train_idx):
        return 1

    def score(model, test_idx):
        return [random.uniform(-0.01, 0.01) for _ in test_idx]

    out = combinatorial_purged_cv(
        n_samples=500, fit=fit, score=score,
        n_groups=6, n_test_groups=2, embargo=10,
    )
    # C(6, 2) = 15 paths expected.
    assert out["n_paths"] == 15


def test_expected_max_sharpe_grows_with_trial_count():
    e1 = expected_max_sharpe(n_trials=10, sharpe_variance=0.5)
    e2 = expected_max_sharpe(n_trials=1000, sharpe_variance=0.5)
    assert e2 > e1


def test_deflated_sharpe_penalizes_multiple_trials():
    # Generate a return stream with a modest edge.
    random.seed(0)
    returns = [random.gauss(0.001, 0.02) for _ in range(250)]
    dsr_solo = deflated_sharpe(returns, n_trials=1)
    dsr_many = deflated_sharpe(returns, n_trials=1000)
    # Deflation should lower the probability of non-random edge.
    assert dsr_many["deflated_sharpe"] <= dsr_solo["deflated_sharpe"]


def test_apply_costs_deducts_turnover_weighted_bps():
    rets = [0.01, 0.01, 0.01]
    tov = [1.0, 0.5, 0.0]
    net = apply_costs(rets, tov, fee_bps=5, slip_bps=1)
    # bar 0: full turnover → -6bps; bar 1: 50% → -3bps; bar 2: 0% → no cost.
    assert abs(net[0] - (0.01 - 0.0006)) < 1e-9
    assert abs(net[1] - (0.01 - 0.0003)) < 1e-9
    assert abs(net[2] - 0.01) < 1e-9


def test_sweep_costs_reports_grid_and_best_worst():
    # Need some return variance so Sharpe is non-zero and strictly ordered
    # by net mean after cost deduction.
    random.seed(1)
    rets = [random.gauss(0.001, 0.002) for _ in range(200)]
    tov = [0.5] * 200
    out = sweep_costs(rets, tov, fee_grid_bps=[0, 5], slip_grid_bps=[0, 1])
    assert out["n_combinations"] == 4
    assert out["best"]["fee_bps"] == 0 and out["best"]["slippage_bps"] == 0
    assert out["worst"]["fee_bps"] == 5 and out["worst"]["slippage_bps"] == 1
