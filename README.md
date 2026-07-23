# Nexus - Institutional Crypto Derivatives Terminal

A local-first, Bloomberg-style research and execution terminal for USDⓈ-M
perpetual futures. Multi-venue market data (Binance · OKX · MEXC), an 11-signal
alpha engine, a VaR/Kelly risk module with an event-driven circuit breaker,
liquidity-heatmap and order-flow analytics, and an optional local-AI research
brief - all rendered in a dark "obsidian" desktop UI.

> Runs entirely on your machine. Live market data streams from **public**
> exchange WebSockets, so the core terminal works with **no API keys**.

![status](https://img.shields.io/badge/status-v0.3-informational)
![python](https://img.shields.io/badge/python-3.11+-blue)
![node](https://img.shields.io/badge/node-18+-green)

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│  Frontend  ·  Next.js 16 + Electron   (port 3000)              │
│  Charts (lightweight-charts) · Matrix engine · Risk · Docs     │
└───────────────────────────────┬───────────────────────────────┘
                                │  REST / poll
┌───────────────────────────────┴───────────────────────────────┐
│  Backend  ·  FastAPI + asyncio        (port 8001)              │
│  WS ingestion → fusion → alpha → risk → circuit breaker        │
└───────────────────────────────────────────────────────────────┘
```

- **backend/** - FastAPI service: exchange ingestion, computation engines
  (alpha, VaR, OI, funding, liquidity, order flow), and the REST API.
- **frontend/** - Next.js UI wrapped as an Electron desktop app.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | backend (tested on 3.11-3.14) |
| Node.js | 18+ | frontend / Electron |
| Ollama | optional | only for the local-AI research brief ([ollama.com](https://ollama.com)) |

---

## Download

```bash
git clone https://github.com/LouisMiguelBernal/nexus.git
cd nexus
```

---

## Run (development)

Nexus is two processes - start the **backend** first, then the **frontend**.

### 1 · Backend (FastAPI, port 8001)

```bash
# from the repo root
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8001
```

The backend serves at `http://localhost:8001` - check `http://localhost:8001/api/health`.

### 2 · Frontend (Next.js, port 3000)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. That's it - live BTC/ETH/SOL data should start
streaming within a few seconds.

### 3 · Desktop app (Electron, optional)

Run the terminal as a standalone desktop window (auto-starts the servers):

```bash
cd frontend
npm run build          # production Next.js build
npm run electron:start # launch the Electron shell
```

To produce a Windows installer (`.exe`):

```bash
cd frontend
npm run electron:build   # output in frontend/dist-electron/
```

---

## Configuration (optional)

The core terminal needs **no keys**. To enable extras - the Trading Journal
(your own read-only account fills), news headlines, macro data, or Telegram
alerts - copy the template and fill in what you want:

```bash
cp .env.example backend/.env
```

Every variable is optional and the app degrades gracefully. **Use read-only
API keys only**, and never commit `backend/.env` (it is gitignored).

### Optional: local AI brief (Ollama)

The Research tab can synthesise a market brief with a local LLM. Install
[Ollama](https://ollama.com), then:

```bash
ollama pull gemma2:2b   # or any model you prefer
ollama serve
```

Without Ollama running, every other feature works normally; only the
"Generate AI Brief" button is unavailable.

---

## Tests

```bash
python -m pytest backend/tests
```

---

## Project layout

```
nexus/
├─ backend/            FastAPI service
│  ├─ main.py          app + REST routes
│  ├─ ingestion/       exchange WebSocket / REST feeds
│  ├─ computation/     alpha, OI, funding, liquidity, order flow
│  ├─ risk/            VaR, Kelly, circuit breaker
│  ├─ validation/      walk-forward / CPCV / deflated Sharpe
│  └─ tests/
├─ frontend/           Next.js + Electron UI
│  ├─ src/             app, components, lib
│  └─ electron/        desktop shell
├─ requirements.txt
└─ .env.example        config template (copy to backend/.env)
```

---

## Notes

- **Read-only by design.** Nexus analyses and surfaces market state; it does
  not place orders. The "Execute Order" control is a phase-gated placeholder.
- **Local-first.** No account, no cloud, no telemetry. Data lives in a local
  SQLite file that is created on first run and is gitignored.
- Outputs (VaR, position sizing, signals) are statistical estimates for
  research - **not financial advice**.

## License

Licensed under the **GNU Affero General Public License v3.0** - see
[`LICENSE`](LICENSE). If you run a modified version as a network service, the
AGPL requires you to make your source available to its users.
