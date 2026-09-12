# Nexus Architecture

Status: **transitional**. This document describes the target architecture the revamp is moving toward, and marks what exists today. Decisions are recorded in `docs/adr/`. The phase roadmap and exit criteria live in the approved revamp plan (see `CHANGELOG.md` for what has landed).

## Principles

1. **Trust the numbers.** Every signal is backtested with fees, funding and slippage, and carries a measured, versioned verdict (`UNVALIDATED → CANDIDATE | PROMOTED | REJECTED`). Weights are fitted, not asserted.
2. **Nothing fails silently.** A blind `except Exception` needs a signed `# noqa: BLE001 reason=...`; failures log at `warning`+ with tracebacks; `/readyz` reflects reality.
3. **One engine.** Backtest and paper execution run the same `ExecutionEngine` and strategy code; only the clock, feed and venue adapter are swapped (NautilusTrader principle).
4. **Every order passes the risk chain.** There is exactly one path to a venue, and it runs `KillSwitch → MacroGate → CircuitBreaker → ExposureCap → LeverageCap → Sanity`, recording each verdict.
5. **Local, single-operator, free.** One process, SQLite, Ollama, no cloud, no paid data. See `NEXUS_VISION.md`.

## Runtime topology (today and target)

```
Electron shell (tray, launcher)
   ├─ frontend  : Next.js  → today `next start` on :3000 · target static export served from the asar over nexus://
   ├─ backend   : uvicorn  → 127.0.0.1:8001 (today 0.0.0.0 — fixed in Phase 0)
   └─ ollama    : localhost:11434 (gemma4:e4b), spawned only if absent
```

## Backend package layout (target; `[x]` = exists today)

```
backend/
  main.py        [x] shim → app.create_app()  (today: 3,395-line monolith, decomposed in Phase 1)
  app.py         [ ] create_app(): settings, logging, store, bus, supervisor, routers, lifespan
  config.py      [x] constants   settings.py [ ] pydantic-settings (ports, paths, token, flags)
  core/          [ ] bus · supervisor · clock (LiveClock/SimClock) · events (typed) · symbols (registry+LRU) · cache
  data/          [ ] http (single TLS helper) · store (aiosqlite, single writer) · migrations/ · history · archive · registry · quota
                     feeds/ ← ingestion/* [x] moved verbatim
  computation/   [x] pure math (golden_zone, alpha_engine, vpin, cvd, …) + indicators.py [ ] (TA lines lifted from main.py)
  strategy/      [ ] base (Strategy → OrderIntent) · context · alpha_composite · zone_reaction
  risk/          [x] kelly, var, correlation, circuit_breaker … + gate_chain.py [ ] + gates/ [ ]
  execution/     [x] cost_model, slippage_estimator + orders (state machine) [ ] · engine [ ] · portfolio [ ] · adapters/{sim,blofin} [ ] · reconcile [ ] · journal [ ]
  research/      [ ] backtest/{engine,metrics} · pipeline · experiments · weights · promotion · report · cli
  validation/    [x] walk_forward, combinatorial_purged_cv, deflated_sharpe, regime_stratified, cost_sensitivity, replay
  api/           [x] matrix, world  + [ ] health, market, derivatives, alpha, risk, execution, research, alerts, ai, ws
  ai/            [x] gemma4, finbert, brief_generator
  alerts/        [x] telegram, alert_types + dispatcher (dedupe/cooldown) [ ]
  services/      [ ] Service subclasses replacing the hand-rolled loops and jobs/*
  ops/           [ ] logging (structlog) · health (/healthz /readyz) · metrics (/metrics) · scheduler · auth · version · doctor
```

## Event flow (target)

```
venues (WS/REST) ─► data/feeds ─► core.bus  (typed events; bounded per-subscriber queues; drop_oldest | coalesce)
                                      │
      ┌───────────────┬───────────────┼─────────────────┬────────────────┐
  services/*     risk/circuit_     execution.engine    api/ws fanout     data/archive (opt-in)
  (ingest, liq,  breaker (event   (Strategy → Intent   (per-client        (JSONL.gz for
   matrix, alpha, trips + equity,  → RiskChain →        coalesced          validation/replay.py)
   zones, oi …)   auto-clear)      Adapter)             queues)
                                        │
                              SimulatedExchange | BloFinPaper
                                        │
                              data/store → orders · order_events · fills · positions · equity_snapshots · risk_decisions
```

**Bus contract.** `subscribe(topic, handler, *, maxsize=256, policy="drop_oldest")` spawns one consumer task per subscriber under the supervisor. `publish()` is synchronous (`put_nowait`); on a full queue it drops the oldest or replaces (coalesce) and increments `nexus_bus_dropped_total{topic,subscriber}`. Producers never block on consumers.

**Supervisor contract.** `Service(name, interval_s)` with `run_once()`/`run()`. Handles are retained; a crashing service is restarted with backoff 1→60 s + jitter; `stop_all()` cancels and awaits with a deadline; `status()` feeds `/readyz` and `/api/health.services`. `while True` does not appear in application code.

## Shared engine: backtest ≡ paper

| Mode | clock | feed | adapter | store |
|---|---|---|---|---|
| backtest | `SimClock` | `HistoricalFeed` (cursor-truncated; asserts `event.ts <= clock.now()`) | `SimulatedExchange` (fills, slippage via `cost_model`, funding accrual, liquidation) | in-memory / `research.sqlite` |
| paper | `LiveClock` | `LiveFeed` (bus subscriber) | `BloFinPaper` (ccxt async, demo forced) | `nexus.db` |

Strategies never import `time`, venues or raw feed state; they receive a `StrategyContext` (`clock`, `bars()`, `position`, `params`). `ctx.bars()` returns only `open_time < clock.now()`; a peeking strategy raises `LookAheadError` in tests. The cross-asset regime conditioner is registered only at live startup, so backtests use the pure classifier (`computation/regime.py`).

## Orders

States: `PENDING_RISK → REJECTED | ACCEPTED → SUBMITTED → ACKED → PARTIALLY_FILLED → FILLED | CANCEL_PENDING → CANCELED | EXPIRED | ERROR`. Illegal transitions raise. `client_order_id = "nx" + strategy[:4] + base32(uuid4)[:18]` is the idempotency key (resubmit → HTTP 409). A 10 s `ReconcileService` diffs venue open orders / positions / fills against local state, flags orphans, and drives `circuit_breaker.update(equity)`.

## Risk gate chain

`KillSwitch → MacroGate (macro/gate.py can_open_position + adjusted params) → CircuitBreaker (can_trade, leverage cap) → ExposureCap (Kelly with vol + correlation; max 3 positions / 5 open orders) → LeverageCap (min of macro, breaker, KELLY_CONFIG) → Sanity (limit ±2 % of mark, venue min notional, qty step, reduce-only when flat-closing)`. `MODIFY` decisions are applied and recorded; `POST /api/execution/orders` is the only entry and it calls `engine.submit()`.

## Streaming

`GET /ws/stream?token=…`; client `{"op":"sub","topics":[…]}`; server `{"t","ts","seq","d"}`, `$hb` every 15 s, `$gap` with drop counts. Snapshot topics (`ticker.*`, `book.*` at 4 Hz, `matrix.*`, `alpha.*`, `health`, `feeds`, `positions`, `breaker`) coalesce; append topics (`tape.*` batched 250 ms, `orders`, `fills`, `alerts`) drop-oldest with a gap marker. REST routes return the last snapshot, so the frontend migrates tab by tab.

## Research pipeline

`Experiment` → backtest per parameter set (each a `trial`, counted per signal family) → `walk_forward` (train ≥ 90 d, test 30 d, step 7 d, embargo 5 d) → `combinatorial_purged_cv` → `deflated_sharpe(n_trials=family)` → `sweep_costs` → `regime_stratified` → `promotion.decide()` → `promotions` row + `docs/RESEARCH_LOG.md` entry + `research/results/<run>/report.{md,json}`. The gate is in ADR 0006. `WEIGHTS_BY_REGIME` is fitted per regime by NNLS with shrinkage to equal weight and shipped as an artifact carrying its training range and fit date; every alpha payload reports `weights_source`.

## Live-trading gate (locked)

`BLOFIN_DEMO` and `BINANCE_TESTNET` stay `True`. `adapters/blofin.py::LiveGuard` refuses `demo=False` unless (a) `NEXUS_LIVE_TRADING_ACK` equals the sha256 of `docs/LIVE_TRADING_ACK.md`, (b) a strategy has ≥ 30 days of paper metrics passing gate Part B, and (c) a file flag exists in `NEXUS_DATA_DIR`. None of this is built; only the lock is.

## Data and paths

`NEXUS_DATA_DIR` (dev `./data`, packaged `%APPDATA%\Nexus`) holds `nexus.db`, `logs/`, `api_token`, `research/`. `.env` is read-only to the app (`NEXUS_ENV_FILE`). Versions come from the root `VERSION` file.
