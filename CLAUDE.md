# High-Performance Multi-Role System (Quant / UI / Backend)

## Core Identity

Operate as a **hybrid execution engine**:

* **Quant (Rentech-style)** → alpha, statistical rigor, discipline
* **UI/UX (Figma-level)** → clarity, hierarchy, usability
* **Backend (Google-level)** → scalable, efficient, reliable systems

Output = **high-signal, low-noise, implementation-ready**

---

## Global Principles

### 1. Token Efficiency

* Minimize verbosity; maximize information density
* Use structure, bullets, abstraction
* Avoid repetition and filler

---

### 2. Precision

* No guessing → state assumptions
* Prefer quantified reasoning, models, trade-offs
* Avoid vague language

---

### 3. Output Structure (default)

**Objective → Insight → Implementation → Optimization → Risks**

---

## Quant Mode

* Think **alpha, not indicators**
* Edge = **statistical asymmetry + execution**
* Focus: features, regimes, cross-asset, microstructure
* Validate: overfitting, OOS robustness, costs

Output:

* compact math / pseudo-logic
* signal, pipeline, metrics

---

## UI/UX Mode

* **Clarity > creativity | hierarchy > decoration**
* Reduce cognitive load; guide attention

Use:

* grids, spacing, minimal functional color

Output:

* layout, components, flow (no fluff)

---

## Backend Mode

* **Scalable, efficient, reliable**
* Consider: time, memory, fault tolerance

Prefer:

* modular design, stateless services, clean APIs

Output:

* data flow, concise pseudocode, minimal abstraction

---

## Security Constraints

* No access/inference of:

  * `.env`, secrets, keys, private configs
* No simulation or extraction of sensitive data

Assume all secrets are **inaccessible**

---

## Reasoning Framework

**Decompose → Abstract → Optimize → Execute**

---

## Communication

* Direct, technical, structured
* No filler or unnecessary explanation
* Prioritize clarity + execution

---

## Failure Avoidance

* No overengineering / underspecification
* No generic or low-signal output

---

## Default Behavior

* Infer intent → proceed with best assumption
* Ask only critical clarifications

---

## Goal

* **Max insight per token**
* **Actionable, production-ready output**
* **Consistent high-level performance**

---

## Nexus - Ground-Truth Invariants (post-P0, 2026-04-24)

Source of truth for code state. Update when code changes; never let docs drift.
Revamp status, target architecture and decisions: `docs/ARCHITECTURE.md`, `docs/adr/`, `CHANGELOG.md`.

### Risk engines

* `backend/risk/var.py` - **three-method VaR**:
  * `historical()` - empirical quantile
  * `parametric_t()` - Student-t (df fit from kurtosis) with EWMA σ (λ=0.94)
  * `monte_carlo(n_paths=500, n_steps=50, dist='student_t', df=4)`
  * `compute()` returns `{historical, monte_carlo, parametric, ensemble_max, stressed_var, liquidation_risk, inputs}`.
  * `ensemble_max` is the **Kelly denominator**.
  * `contribution_var(positions, returns_by_symbol)` - Euler-allocated marginal + component VaR.
* `backend/risk/kelly.py` - **vol- + correlation-adjusted Kelly**:
  * `b = avg_win / max(atr_pct, realized_vol_24h)` when vol supplied; falls back to classical `avg_win / avg_loss`.
  * Final fraction × `(1 − max|ρ_ij|)` vs open positions (ρ from `backend/risk/correlation.py`).
  * Half-Kelly default; caps: `max_position_pct`, `max_leverage`, `margin_buffer`.
  * Backward-compatible: vol/corr args optional.
* `backend/risk/correlation.py` - **wired** into Kelly (was orphaned pre-P0).
* `backend/risk/circuit_breaker.py` - event triggers exist (`on_var_breach`, `on_correlation_snapshot`, `on_ws_gap_report`, `on_funding_zscore`, `on_vpin`) and are subscribed via `wire_circuit_breaker`; the threshold path (`update(equity)`, `daily_reset()`) has **no caller yet**, and a trip latches for the process lifetime. Phase 1 of the revamp feeds equity, scopes WS trips to Binance, and adds auto-clear + Telegram.

### Alpha engine

* `backend/computation/alpha_engine.py` - **regime-conditional weights**:
  * `WEIGHTS_BY_REGIME` = 5 regimes × 12 signals (the 8 legacy factors + `tsmom`, `oi_momentum`, `funding_carry`, `squeeze`; each row sums to 1.0). Weights are asserted, not fitted - Phase 2 replaces them with a fitted artifact (`docs/adr/0006-promotion-gate.md`).
  * `generate_composite(..., klines=...)` classifies via `RegimeClassifier` and selects the row.
  * Result includes `regime` + `weights_used`.
  * Legacy `SIGNAL_WEIGHTS` kept as the `insufficient_data` fallback.
* `backend/computation/cvd.py` - **notional-signed** multi-TF (Σ p·q with side). Do not "fix"; already correct.
* `backend/computation/regime.py` - consumed by `alpha_engine.py` (was orphaned pre-P0).

### Ingestion

* `backend/ingestion/ws_manager.py` - **gap-fill tracking** (P0-4):
  * `WSConnection` stamps `_last_event_time` per message; records `_disconnect_started_at` on failure.
  * On successful reconnect, if outage > 1s: appends to bounded `_gap_log` (cap 64) and awaits `on_gap(name, gap_start, gap_end)` if wired.
  * Exposes `last_event_time`, `seconds_since_last_event`, `gap_log`.
  * `WSManager.gap_report(name=None)` for `/api/health` and `monitoring.staleness`.
  * Per-venue REST backfill into live buffers is the **consumer's** job (hook, not policy).

### Cross-asset + geo layer (added 2026-09-09)

* `backend/crossasset/` - **OpenBB-shaped context, keyless**:
  * `yahoo.py` - v8 chart (open) for quotes/OHLCV; `fetch_gated()` mints and
    rotates the cookie+crumb pair for v10 quoteSummary / v7 options / v1
    screener. Registered with `rate_guard` under the `query1/query2` hosts.
  * `fred.py` - `fredgraph.csv`, **no API key**. YoY is computed **by date**
    (`_nearest_year_ago`), never by a fixed index offset: these series are
    variously daily/weekly/monthly/quarterly, so `points[-13]` is a year for
    monthlies and three years for GDP.
  * `equity.py` - fundamentals / screener / option chain + `max_pain()`. All
    three return `{"available": False, "reason": ...}` on refusal, never raise.
  * Yahoo no longer populates `grossProfit` / `operatingIncome` on
    quoteSummary (0 and null for every issuer); `income` reports revenue, net
    income and derived net margin instead.

* `backend/geo/` - **worldmonitor-shaped, local-first**:
  * `sources.py` - USGS, GDACS, EONET, NOAA SWPC + `GEO_RSS` wires.
    GDACS severity is read from `<gdacs:alertlevel>`. **Do not infer it from
    the text** - every item in that feed contains the substring "red", so a
    naive check scores all 385 as red alerts and pins the composite at 100.
  * `worldmonitor.py` - optional enrichment. Never raises, 30-min cache, 1-hour
    cooldown after failure, off with `WORLDMONITOR_ENABLED=0`.
  * `instability.py` - composite 0-100. **Unavailable is not zero**: weights
    renormalise over reporting components and the score is `None` when none
    report. Spikes immediately, decays slowly (`_DECAY_LAMBDA`).

* `backend/computation/cross_regime.py` - `risk_appetite()` (-100..+100 RORO)
  and `adjust_regime()`. The regime **vocabulary never grows**: it returns only
  labels `WEIGHTS_BY_REGIME` keys on. Macro may tip a *low-confidence* `ranging`
  to `volatile` and scale confidence on divergence; it never decides direction.
  `macro_stress` is a soft-max, not a mean - a VIX of 38 must not read as
  moderate merely because rates and the dollar are quiet.

* **The conditioning hook lives in `computation/regime.py`**
  (`set_conditioner`/`get_conditioner`), applied inside
  `RegimeClassifier.classify()`. There are four call sites (alpha engine,
  matrix router, `/api/alpha`, `/api/brief`); wrapping them individually is how
  the reported regime and the regime the weights came from drift apart.
  Registered only in `main.py` startup, so backtests keep a pure classifier.

* `backend/macro/gate.py` - `evaluate()` is now
  `_evaluate_calendar()` + `_apply_geo_overlay()`. The overlay takes the
  **tighter** value on every axis; it can never loosen a calendar restriction
  or re-open positions the calendar closed. `set_geo_risk(None)` restores
  calendar-only behaviour. `to_dict()` keeps every legacy key and adds
  `geo_score`, `geo_band`, `geo_tier`, `sources`.

* `backend/jobs/world_poller.py` + `backend/api/world.py` - poller owns
  freshness for `/api/world/{board,macro,regime,geo}`; the request path never
  fetches an upstream. `/chart`, `/fundamentals`, `/screener`, `/options`,
  `/search` are user-initiated so they use TTL cache + single-flight instead.

* `backend/geo/domains.py` - **cyber + aviation**:
  * `fetch_cyber` - CISA KEV. Counts *additions*, never catalogue size (which
    only grows and encodes nothing but elapsed time), and
    `_cyber_component` scores them against the catalogue's own trailing 30-day
    rate. A fixed threshold made an ordinary week read 80/100.
  * `fetch_aviation` - OpenSky anonymous states per watch region. Display-only
    and **not scored**: the deviation needs a baseline, and that baseline is
    built in memory over the session, so early readings say "warming up".

* `backend/geo/worldmonitor.py` - their REST API **requires a key**
  (`X-WorldMonitor-Key`), so set `WORLDMONITOR_API_KEY` to enable it; without
  one the status reads `no api key`, which is a different state from
  `unreachable` and the UI shows which. Operation paths come from their
  published sandbox index, not guesswork. `WORLDMONITOR_SANDBOX=1` reads their
  key-free fixtures for UI work; those payloads carry `sample: True` and
  `instability.py` refuses to score them - **sample numbers must never reach
  the macro gate.**

* `backend/crossasset/equity.py` - Yahoo's `openInterest` is currently
  unreliable: 0 on near expiries against ~485k contracts of same-day volume,
  two-digit totals on longer tenors. `_open_interest_is_credible()` gates it
  (OI on an established chain is normally >= one day's volume); when it fails,
  the put/call ratio falls back to a **volume** basis and says so via
  `put_call_basis`, and `max_pain` - an open-interest construct - returns None
  rather than guessing.

* Frontend: `WorldTab.tsx`, nav id `world`, **Alt+0**, with three sub-views -
  OVERVIEW (board, curve, FRED, geo, cyber, aviation), INSTRUMENT
  (`world/SymbolInspector.tsx`: search, candles, fundamentals, options) and
  SCREENER (`world/ScreenerPanel.tsx`). The overview's four feeds are gated by
  `enabled: view === "overview"` so the unseen views cost nothing.

* **Asset-class separation is a hard rule.** Every cross-asset row is tagged
  `asset_class: "cross_asset"` at the source. No symbol from this layer may
  reach a perp code path - that regression (typing "NVDA" binding the crypto
  tab to a nonexistent perp) is why stocks were removed in July 2026.

* Sources are verified from this machine before being added. Deliberately
  **not** used: ReliefWeb (v1 410, v2 403), GDELT DOC (hard 429s), the
  Google-News/Reuters proxy (parses fine, returns zero items). A source that
  silently never answers is worse than none - the score renormalises around it
  and nothing looks broken.

### Still-drift / known gaps (revamp phases in parentheses)

* `funding.py` - snapshot only; term structure pending. Rolling z-score window fills only from the 30 s poller, so cold starts over-trip |z|>3 (Phase 0 seeds it from funding history).
* `obi_tracker.py` - qty-based; notional + VPIN-clock pending.
* `oi_analysis.py` - trend only; cross-sectional ROC z-score pending.
* `squeeze_risk.py` - linear, regime-blind; its liquidation-distance term is never fed by `main.py`, so 25 % of the score is structurally 0 (Phase 0).
* `golden_zone.py` - `platinum` tier unreachable: `_classify_tier` requires a CoinGlass flag the call site never passes (Phase 0).
* `vpin.py`, `factors/{tsmom,xs_funding}.py` - **exist**. VPIN bucket size is a single $2M constant for every symbol (Phase 0 makes it per-symbol from 24 h volume). TSMOM is fed 15 m closes but annualises as 1 h bars (Phase 0).
* `validation/`, `execution/`, `monitoring/` - **exist** but are imported by nothing except tests (Phase 1 wires monitoring; Phase 2 wires validation into the research pipeline; Phase 2-3 build the execution engine).
* `backtesting/` - empty package; the only reachable backtest (`computation/backtest.py`) models no fees, funding, slippage or liquidation (Phase 2 replaces it).
* `monitoring/event_bus.py` - documents bounded queues but awaits handlers inline; no backpressure exists (Phase 1).
* `main.py` - 3,395-line monolith; five hand-rolled loops with unretained task handles; blocking SQLite and blocking ccxt on the event loop (Phase 1).
### Non-negotiables (see `NEXUS_VISION.md`)

* Read-only frontend; Kelly/VaR outputs are **advisory** until Phase 6.
* Local-first: Ollama + Gemma 4, FinBERT CUDA, SQLite. No paid APIs.
* Bloomberg-dark UI; silver `#c6c6c7` accent (institutional choice - not amber); 10-12px data-dense.
* Philippines/PLDT: SSL permissive fallback required in `ws_manager.py`.
* Secrets only in `.env`; never read, never written by agents.
