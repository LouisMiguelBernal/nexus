# NEXUS - Product Vision & Non-Negotiables

> **This file is the source of truth for what Nexus is.**
> AI assistants (Copilot, Cursor, Claude, etc.) MUST read this before making
> architectural suggestions. Do NOT rename the project, do NOT swap the
> architecture, do NOT propose alternate code names ("Sentinel", "Aegis",
> whatever). This is Nexus.

---

## What Nexus IS

**Nexus is a personal, institutional-grade crypto derivatives research &
execution terminal.** One operator (the user), running locally on Windows,
pinned to the taskbar as a standalone Electron app.

Think: **Bloomberg Terminal × Renaissance Technologies × BlackRock Aladdin**,
but for one trader, free, and focused on USDT-M perpetual futures.

## What Nexus IS NOT

- ❌ A SaaS platform / multi-tenant product
- ❌ A social/community trading app
- ❌ A copy-trading or signal-selling service
- ❌ A "bot marketplace"
- ❌ "Project Sentinel" or any other name
- ❌ A TradingView clone - we do NOT build chart libraries, we analyze flow
- ❌ An arbitrage bot or auto-trader (phase-gated; humans approve trades)

---

## The Pillars (never remove these)

1. **Golden Zone Engine** - cross-exchange liquidity zone detection
   (bronze/silver/golden/platinum tiers across Binance, Bybit, OKX, Gate)
2. **Alpha Engine** - 8-factor composite signal:
   - Order Flow Imbalance (OFI)
   - VWAP Deviation
   - Funding Arbitrage
   - Cross-Exchange Spread
   - Liquidation Cascade
   - Delta Divergence
   - Smart Money Flow
   - Volatility Regime Shift
3. **Liquidity Heatmap** - 2D price × time order book visualization with
   wall/void/absorption detection
4. **Smart Money Tracker** - whale detection, iceberg orders,
   accumulation/distribution flow
5. **Macro Gate** - FOMC/CPI/NFP event risk gate that throttles position
   sizing and leverage during known volatility windows. Since 2026-09 it also
   takes a **geopolitical risk tier** from the World layer and applies whichever
   of the two constraints is tighter.
6. **World Layer** - cross-asset context (OpenBB-shaped: index / rates /
   currency / commodity / sector / equity / options / screener / FRED macro) and
   global-event intelligence (worldmonitor-shaped: seismic, disasters, space
   weather, conflict wires). Feeds two engines: risk appetite conditions the
   alpha engine's regime weight selection, and the composite geo score feeds the
   Macro Gate. **Context only - nothing here is tradable.**

## Tabs (UI contract)

Primary layers, then drill-downs. Alt+N switches.

```
ALT+1  EXECUTION       - chart, matrix engine, order ticket (paper)
ALT+2  SIGNALS         - composite score, signal matrix, smart money, regime
ALT+3  LIQUIDITY MAP   - heatmap + depth profile + walls/voids/clusters
ALT+4  RESEARCH        - brief, funding, squeeze, macro, regime, Kelly, zones
ALT+5  ORDER FLOW      - CVD multi-tf, volume profile, absorption, whale trades
ALT+6  ALERTS & NEWS   - alert history, news feed, watchlist, AI brief
ALT+7  SYSTEM DOCS     - architecture and method reference
ALT+8  RISK            - VaR ensemble, Kelly, circuit breaker, stress
ALT+9  JOURNAL         - trade calendar, stats, portfolio, AI analysis
ALT+0  WORLD           - cross-asset board, FRED macro, Treasury curve,
                         geopolitical risk, global-event wire
```

## Non-Negotiable Stack

| Layer       | Tech                                             |
| ----------- | ------------------------------------------------ |
| Backend     | Python 3.12+, FastAPI, asyncio, websockets       |
| Frontend    | Next.js 16, React 19, TypeScript, Tailwind v4    |
| Shell       | Electron 36 (one-click launch, system tray)      |
| Database    | SQLite (local, no cloud)                         |
| AI          | Ollama + Gemma 4 (LOCAL inference, no OpenAI)    |
| Sentiment   | FinBERT (local CUDA inference)                   |
| Exchanges   | Binance, Bybit, OKX, Gate (ingestion)            |
| Trading     | BloFin via CCXT (paper first - Phase 6 for live) |
| Alerts      | Telegram bot                                     |
| Macro data  | FRED (keyless CSV), Fear & Greed, Yahoo (all free) |
| Cross-asset | Yahoo v8/v10 - equities, ETFs, FX, futures, rates |
| Global events | USGS, GDACS, NASA EONET, NOAA SWPC, RSS wires   |
| Geo enrich  | worldmonitor.app - OPTIONAL, degrades to local    |

## Non-Negotiable Design Rules

- **Bloomberg-style dark UI** - data-dense 10-12px, amber accent `#f0a500`,
  CSS variables for theming. No modal-heavy UX. No empty white space.
- **Local-first** - no mandatory cloud services. Runs on the user's machine.
- **Zero paid APIs** - CoinGlass removed, Whale Alert removed, CryptoPanic
  removed. Replaced with RSS, FRED, CMC free tier, Finnhub free tier.
- **Read-only until Phase 6** - paper trading only until the user explicitly
  promotes to live. `BINANCE_TESTNET=True` and `BLOFIN_DEMO=True` are defaults.
- **Philippines/PLDT-compatible** - ISP blocks Binance/Bybit/OKX. SSL
  auto-fallback + DNS workarounds (urllib sync in thread) are required.
- **Secrets only in .env** - NEVER hardcoded. NEVER committed. NEVER
  programmatically modified by agents.

## File Structure (canonical)

```
E:\nexus\
├── backend\                  Python FastAPI
│   ├── main.py               app + lifespan + endpoints
│   ├── config.py             endpoints, thresholds, symbols
│   ├── computation\          alpha_engine, liquidity_heatmap, smart_money,
│   │                         cvd, regime, cross_regime, squeeze, absorption
│   ├── crossasset\           yahoo, fred, equity  (context, never tradable)
│   ├── geo\                  sources, worldmonitor, instability
│   ├── ingestion\            binance_ws, bybit_ws, okx_ws, gate_ws, ws_manager
│   ├── intelligence\         gemma4, finbert, news, macro
│   ├── trading\              blofin (paper), risk engine, kelly
│   └── storage\              sqlite db, zones table, alerts table
├── frontend\                 Next.js + React + Electron
│   ├── src\app\              Next.js app router
│   ├── src\components\       Header, TabBar, StatusBar, tabs\*
│   ├── electron\             main.js - self-contained launcher + tray
│   └── package.json
├── Nexus.bat                 One-click batch launcher
├── Nexus.vbs                 VBS wrapper (hides console)
├── .env                      SECRETS - never committed
└── NEXUS_VISION.md           THIS FILE
```

## What "Project Sentinel" would be (if an AI ever suggests it)

> Probably a Copilot hallucination spun up from generic "security monitoring
> terminal" patterns in its training data. **Reject it.** This project is
> Nexus. If the suggestion involves renaming, restructuring into microservices,
> adding auth/multi-user, adding a cloud backend, or replacing the local
> FastAPI with something "scalable" - the AI is off-track. Redirect it to
> this file.

## Phase Roadmap (locked)

- **Phase 1** ✅ Golden Zone Engine + multi-exchange ingestion
- **Phase 2** ✅ Alerts + Telegram + news
- **Phase 3** ✅ Alpha Engine + Liquidity Heatmap + Smart Money + Bloomberg UI
- **Phase 4** ✅ Electron standalone shell + one-click launch
- **Phase 5** 🚧 Backtest engine + paper trading validation on BloFin
- **Phase 6** 🔒 Live trading (requires explicit user promotion)

---

*Last updated: 2026-09-09 - v0.3.0 (World layer added)*
