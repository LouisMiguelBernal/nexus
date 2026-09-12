# Research Log

Append-only record of every hypothesis tested and every promotion decision. The pipeline (`backend/research/pipeline.py`, Phase 2) writes an entry per run; humans add the reasoning. **No signal earns composite weight without an entry here.**

Promotion gate: see `docs/adr/0006-promotion-gate.md`. Gate changes bump `GATE_VERSION` and are logged below.

## Entry format

```
## <run_id> — <date> — <experiment name>
Hypothesis: one sentence.
Strategy / params / data range / bar interval / symbols.
Trials in family (N for DSR): …
Results: net Sharpe (5+1 bps) · DSR · hit-rate · expectancy · max DD · turnover · n_trades · per-regime Sharpe · WFO folds passing · CPCV median / P(<0)
Verdict: UNVALIDATED | CANDIDATE | PROMOTED | REJECTED — gate vN, criteria failed: …
Notes: what we learned, what to try next.
Artifacts: research/results/<run_id>/report.md
```

## Signal status board

| Signal | Status | Last run | Gate |
|---|---|---|---|
| ofi | UNVALIDATED | — | — |
| vwap_deviation | UNVALIDATED | — | — |
| funding_arb | UNVALIDATED | — | — |
| cross_exchange_spread | UNVALIDATED | — | — |
| liquidation_cascade | UNVALIDATED | — | — |
| delta_divergence | UNVALIDATED | — | — |
| smart_money_flow | UNVALIDATED | — | — |
| vol_regime | UNVALIDATED | — | — |
| tsmom | UNVALIDATED | — | — |
| oi_momentum | UNVALIDATED | — | — |
| funding_carry | UNVALIDATED | — | — |
| squeeze | UNVALIDATED | — | — |
| zone tier: bronze / silver / golden / platinum | UNVALIDATED | — | — |

The current `WEIGHTS_BY_REGIME` (`backend/computation/alpha_engine.py`) are **asserted, not fitted**; every alpha payload reports `weights_source: "asserted"` until the first fitted artifact ships.

## Entries

*(none yet — Phase 2 produces run #1)*
