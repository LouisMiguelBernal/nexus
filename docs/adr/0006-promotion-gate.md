# ADR 0006: Signal promotion gate (GATE_VERSION 1)

Status: accepted · 2026-09-11 · revisit after research run #1

## Context

Twelve alpha signals and four zone tiers drive the composite score with weights that were asserted, never fitted, and no measured Sharpe, hit-rate or drawdown exists for any of them. The only quantitative rule in the codebase — *Sharpe ≥ 0.8 at 5 bps fees + 1 bps slippage* — lives in a docstring (`validation/cost_sensitivity.py`) and is applied by nothing. `validation/` already implements walk-forward, CPCV, deflated Sharpe, regime stratification and cost sweeps.

## Decision

A signal (or zone tier) is **PROMOTED** only if all of Part A hold on the backtest and, subsequently, Part B holds on 30 days of paper trading. Otherwise it is **REJECTED** (fails A) or **CANDIDATE** (passes A, awaiting B). Anything never run is **UNVALIDATED**.

**Part A — backtest** (net of taker 4 bps / maker 2 bps, funding accrual, slippage from `execution/cost_model.py`, liquidation modelled):

1. Walk-forward concatenated out-of-sample net Sharpe ≥ **0.8** at 5 bps fee + 1 bps slippage (train ≥ 90 d, test 30 d, step 7 d, embargo 5 d).
2. Cost sweep: Sharpe ≥ **0.5** at 10 + 5 bps; worst grid cell ≥ **0.3**.
3. Deflated Sharpe ratio ≥ **0.95** with N = all trials in the signal's family.
4. Walk-forward: ≥ 6 folds; ≥ 60 % of folds with Sharpe > 0; mean fold Sharpe ≥ 0.5.
5. CPCV: median path Sharpe ≥ 0.5; P(path Sharpe < 0) ≤ 0.20.
6. Regime-stratified: Sharpe ≥ 0 in at least 3 of 5 regimes; none below −0.5.
7. Max drawdown ≤ 20 % at 3× leverage; ≥ 200 out-of-sample trades; mean holding ≥ 2 bars.

**Part B — paper confirmation** (BloFin demo, ≥ 30 days): realised slippage ≤ 1.5× modelled; paper Sharpe ≥ backtest Sharpe − 1.0; limit-order fill rate ≥ 80 %; zero unreconciled orders.

**Composite behaviour.** Until run #1: asserted weights, every signal badged UNVALIDATED. After: REJECTED signals get weight 0 (still reported), CANDIDATE signals keep their fitted weight, PROMOTED signals are the only ones allowed to size paper orders. `NEXUS_ALPHA_INCLUDE_UNPROMOTED` re-enables everything for research views.

**Weights.** Fitted per regime by non-negative least squares with shrinkage toward equal weight, on training folds only, and shipped as an artifact carrying `train_range`, `fitted_at`, `gate_version`; the engine asserts `train_range.end < now`. The `±60 STRONG` threshold is replaced by the artifact's `strong_threshold` (80th percentile of |composite| on train).

## Consequences

- "No signal passes" is a valid, expected outcome of run #1 and would be the most valuable result the system has produced so far.
- Thresholds are opinionated starting points; they change only via a new `GATE_VERSION` and a log entry.
- N-trial accounting is mandatory: every parameter set run against the same family raises the bar for DSR.
