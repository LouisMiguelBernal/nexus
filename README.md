# Nexus

Personal, institutional-grade crypto derivatives research and paper-execution terminal. One operator, one Windows machine, zero cloud, zero paid data.

Nexus ingests USDT-M perpetual-futures order flow from Binance, OKX and MEXC over WebSocket; detects cross-exchange liquidity zones; computes a regime-conditioned 12-signal alpha composite, VPIN/CVD/absorption order-flow metrics and a VaR/Kelly risk layer; gates all of it through a macro-event and geopolitical risk gate; and synthesises a daily brief with a local LLM (Ollama + Gemma 4) and FinBERT sentiment. Execution is paper-only on BloFin demo. Live trading is locked behind an explicit, evidence-based promotion gate.

> **Read-only research tool. Not financial advice. Paper trading only.**
> Status: v0.3.0, mid-revamp - see [CHANGELOG.md](CHANGELOG.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12+, FastAPI, asyncio, SQLite (WAL) |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind v4, lightweight-charts |
| Shell | Electron 36 - tray, one-click launch |
| AI | Ollama (`gemma4:e4b`) + FinBERT on local CUDA |
| Data | Binance / OKX / MEXC WebSocket, Deribit, FRED, Yahoo, RSS, USGS / GDACS / NOAA - all free |

## Quick start (development)

Prerequisites: Git, Node 24, Python 3.12 (`py -3.12`), [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), and [Ollama](https://ollama.com/) with `ollama pull gemma4:e4b`.

```
just setup                 # Python venv + lock, npm ci, git hooks
copy .env.example .env     # fill in the keys you have; every source degrades gracefully without one
just dev-backend           # http://127.0.0.1:8001   (terminal 1)
just dev-frontend          # http://localhost:3000    (terminal 2)
just check                 # lint, types, tests, frontend lint/typecheck/build - the CI gate
```

FinBERT needs torch: `just setup-ai` (CUDA wheels, ~2.5 GB). Without it, sentiment reports as unavailable and everything else runs.

## The one shipping fact you must know

The installed desktop app runs a **production build** of the frontend. Editing anything under `frontend/src` changes nothing in the app until you rebuild and relaunch:

```
just build-frontend
```

Phase 5 of the revamp makes the installer self-contained and stamps every build so a mismatch is shown in the status bar.

## Layout

```
backend/     FastAPI app - ingestion, computation, risk, ai, storage, tests
frontend/    Next.js app; electron/ holds the desktop launcher
docs/        ARCHITECTURE, RUNBOOK, RESEARCH_LOG, DATA_SOURCES, ADRs, design mockups
scripts/     maintenance scripts
data/        runtime data (SQLite, logs) - gitignored; set NEXUS_DATA_DIR to relocate
```

## Local API security

The backend listens on `127.0.0.1` only. When `data/api_token` exists - the desktop app creates it on first launch; `python -m backend.ops.auth` creates it for development - every `/api/*` request must carry `Authorization: Bearer <token>`. `/healthz` stays open. `just doctor` reports whether auth is enabled. Without a token the backend still runs and logs a warning on every start.

## Non-negotiables

Single operator. No SaaS, no cloud, no paid APIs. Secrets only in `.env` - never committed, never written by code. `BLOFIN_DEMO=True` and `BINANCE_TESTNET=True` until an explicit, gated promotion. Full statement of intent: [NEXUS_VISION.md](NEXUS_VISION.md).

## License

[AGPL-3.0](LICENSE).
