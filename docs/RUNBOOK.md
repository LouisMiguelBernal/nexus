# Nexus Runbook

How to operate Nexus and what to do when it goes red. Entries marked **(today)** describe the current behaviour; **(target)** describes what the revamp phases deliver.

## Ports and processes

| Component | Address | Owner |
|---|---|---|
| Frontend | `http://localhost:3000` | Electron spawns `next start` (packaged) or `next dev` |
| Backend | `http://127.0.0.1:8001` | Electron spawns `python -m uvicorn backend.main:app`. A launcher installed before 2026-09-12 still passes `--host 0.0.0.0`; reinstall to get loopback-only. |
| Ollama | `http://localhost:11434` | Ollama tray app (`ollama app.exe`) owns the server; Electron spawns one only if the port is closed |

## Start / stop

- Desktop: launch **Nexus** (installed at `%LOCALAPPDATA%\Programs\Nexus`). The tray menu has *Health Check*, *Restart Backend*, *Quit*.
- Development: `just dev-backend` and `just dev-frontend` in two terminals.
- Full stop: tray → *Quit*. Electron kills the backend and Next process trees on quit. Ollama is left running by design.

## Health

- `GET /healthz` — unauthenticated liveness: `status`, `version`, `git_sha`, `uptime_s`. If this answers, the event loop is alive.
- `GET /api/health` (token required when auth is on) — full diagnostics: `websockets`, `ws_gap_report`, `llm` (live Ollama probe: `server_down | model_missing | ready_cold | ready_warm`), `circuit_breaker`, `version`, `git_sha`. Always HTTP 200 **(today)**.
- **(target, Phase 1)** `GET /readyz` → 200 `READY`/`DEGRADED` or 503 `NOT_READY` with `reasons[]`; `GET /metrics` Prometheus text.
- `just doctor` checks the interpreter, build stamp, data dir, SQLite, token, `.env`, both ports, Ollama + model, AI deps, and probes Binance/FRED with strict TLS (`--offline` to skip the network).

## API token

- Lives at `NEXUS_DATA_DIR/api_token` (default `data/api_token`); `NEXUS_API_TOKEN` in the environment overrides it.
- The desktop app generates it on first launch and hands it to the backend and the renderer. For development: `python -m backend.ops.auth` (or `just dev-backend`).
- No token → auth is **disabled** and the backend logs `API auth DISABLED` at every start. Delete the file to rotate; restart both backend and app.
- A 401 from the UI means the renderer and backend disagree on the token: restart the app so both re-read the file.

## Failure playbooks

### AI brief shows nothing / "Brief failed"
1. `curl http://localhost:11434/api/tags` — connection refused means the server is down.
2. Check whether the tray is alive with a dead server: `Get-Process "*ollama*"`. If `ollama app` exists but nothing listens on 11434, **quit the tray and relaunch it** (`%LOCALAPPDATA%\Programs\Ollama\ollama app.exe`). A fresh launch binds in ~2 s.
   - Known cause: **Ollama auto-upgrades in place** (see `%LOCALAPPDATA%\Ollama\upgrade.log`); the surviving tray instance then logs `ollama server not ready after retries` in `app.log` forever. Observed 2026-09-11 after the 0.33.3 → 0.34.0 upgrade.
3. First call after > 30 min idle reloads the model (~85 s on this GPU). The backend budgets 300 s per call and keeps the model resident for 30 min (`OLLAMA_CONFIG.keep_alive`); it also warms the model ~8 s after startup.
4. The UI surfaces `brief_error`; a blank card with no error means the frontend build is stale (next section).

### Frontend edits do not appear in the app
The packaged app serves a **production build**. Run `just build-frontend`, then relaunch Nexus. The status bar shows the frontend's `version · sha` and a `BUILD MISMATCH` badge when the backend reports a different one.

### Backend not responding
Tray → *Restart Backend*. If port 8001 is held by an orphan: `Get-NetTCPConnection -LocalPort 8001` → `Stop-Process -Id <pid>`. Electron also reclaims 3000/8001 on startup.

### Binance REST banned (418 / -1003)

Symptom: `/api/klines`, `/api/ticker`, `/api/symbols/search`, `/api/indicators` and `/api/research/brief` all return **502**, so the Trading tab chart is empty. Everything WebSocket-fed (price, book, tape, CVD) keeps working.

Confirm it in one call — the body names the deadline:

```bash
curl -s https://fapi.binance.com/fapi/v1/ping
```

`{"code":-1003,"msg":"Way too many requests; IP(x.x.x.x) banned until <epoch-ms>"}`

**The deadline moves forward on every request you make while banned.** Observed 2026-09-12: two endpoints reporting deadlines two minutes apart during a probe run. So:

- **Do not restart the backend to "fix" it.** `rate_guard` state is per-process, so a restart forgets the deadline and the pollers immediately re-hammer a host that is banning you — extending the ban. Wait it out.
- **Do not run `just contract-live`** while banned; it is a deliberate burst.
- `just doctor` reports `source:binance_fapi HTTP 418`, and `backend/data/binance_rest.py` logs `REST suspended for Ns more`.

Since 2026-09-12 the request path honours the guard: one 418 records the deadline and subsequent calls are refused locally instead of extending it. Before that, only the WS kline seed and the OI/funding pollers consulted it, and chart requests hammered straight through a ban.

Steady-state REST pressure worth knowing when tuning: `jobs/agg_trade_rest_poller.py` polls every 2 s per symbol whenever WS trades stall (5 symbols ≈ 150 calls/min), `oi_poll_loop` runs every 30 s across OI and funding, and `/api/crypto/strip` fans out to ten concurrent calls per request.

### WebSocket gaps
`/api/health.ws_gap_report` lists per-venue gaps (start, end, duration). Binance re-fetches klines on reconnect into a buffer keyed by `open_time`, so a backfill can no longer duplicate bars. OKX/MEXC are frequently blocked by the ISP (PLDT); their absence degrades zone confidence but is not an outage. **(target, Phase 1)** only a Binance outage can trip the circuit breaker; secondary venues mark `DEGRADED`.

### Circuit breaker shows `triggered: true`
**(today)** the breaker latches for the life of the process — any WS gap > 60 s on any venue, a VPIN ≥ 0.85 print, or |funding z| ≥ 3 trips it and only a backend restart clears it. The funding trigger no longer fires on cold start (the z-score needs ≥ 30 samples spanning ≥ 48 h, seeded from Binance history). **(target, Phase 1)** event trips auto-clear, loss trips reset at 00:00 UTC, and every trip sends a Telegram message.

### TLS "permissive" mode
Behind the ISP block, venue clients fall back from strict to permissive TLS. This now happens in one place (`backend/data/http.py`), logs `tls_downgrade host=…` at WARNING the first time per host, and is counted (`just doctor` reports it). Seeing it on a network that should not need it is a red flag.

### Free-tier quotas (CMC, Finnhub, OpenSky)
**(today)** no accounting; exhaustion shows up as a source silently going stale. **(target, Phase 1)** `data/quota.py` budgets per source and disables a source until reset instead of hammering it; the Sources panel shows the state.

## Data

- Runtime data lives in `NEXUS_DATA_DIR` (default `./data`, gitignored): `nexus.db` (+ `-wal`/`-shm`), `api_token`. Set the variable to relocate everything, e.g. under `%APPDATA%\Nexus`.
- Back up SQLite by copying `nexus.db`, `nexus.db-wal`, `nexus.db-shm` together while the backend is stopped, or use `sqlite3 data/nexus.db ".backup out.db"` while running. Never move the `.db` without its `-wal`.
- Logs: **(today)** stdout of the uvicorn process (visible in the Electron console; warnings are rate-limited per site in hot loops). **(target, Phase 1)** `NEXUS_DATA_DIR/logs/backend.jsonl`, JSON lines, 20 MB × 5.
- `.env` is never written by the application. Rotate keys by editing the file and restarting the backend.

## Escalation

Nothing in this system trades live. If a paper order misbehaves: `POST /api/execution/halt` **(target, Phase 3)** cancels open orders and rejects new ones; until then, stop the backend.
