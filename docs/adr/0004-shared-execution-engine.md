# ADR 0004: One execution engine for backtest and paper; risk chain in the only order path

Status: accepted · 2026-09-11

## Context

`POST /api/blofin/order` passes the request body straight to a synchronous ccxt client with no macro-gate, circuit-breaker, Kelly or leverage check, no auth, no `clientOrderId`, no orders table and no reconciliation. The backtest package is empty, and the reachable "backtest" counts price wiggles. Nothing guarantees that what is backtested is what would be traded.

## Decision

Following NautilusTrader's design: a single `ExecutionEngine(clock, feed, adapter, risk_chain, store, bus)` runs strategies in both modes. Backtest injects `SimClock` + `HistoricalFeed` + `SimulatedExchange`; paper injects `LiveClock` + `LiveFeed` + `BloFinPaper` (ccxt async, `demo` forced). Strategies see only a `StrategyContext`. `engine.submit(intent)` is the **only** path to a venue and always runs `KillSwitch → MacroGate → CircuitBreaker → ExposureCap → LeverageCap → Sanity`, persisting each verdict in `risk_decisions`. Orders follow an explicit state machine with an idempotent `client_order_id`; a `ReconcileService` diffs venue state every 10 s.

Live trading is not implemented. `LiveGuard` refuses `demo=False` unless an acknowledgement hash, ≥ 30 days of passing paper metrics, and a data-dir flag all exist.

## Consequences

- Backtest results mean something about paper behaviour: same fills logic, same funding accrual, same sizing, same gates.
- Every rejected or modified order is explainable after the fact.
- The old order route is deleted (404), which is intentional: there must be no second path.
