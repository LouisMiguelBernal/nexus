# Nexus Runbook

How to operate Nexus and what to do when it goes red. Entries marked **(today)** describe the current behaviour; **(target)** describes what the revamp phases deliver.

## Ports and processes

| Component | Address | Owner |
|---|---|---|
| Frontend | `http://localhost:3000` | Electron spawns `next start` (packaged) or `next dev` |
| Backend | `http://127.0.0.1:8001` (today `0.0.0.0` until Phase 0 lands) | Electron spawns `python -m uvicorn backend.main:app` |
| Ollama | `http://localhost:11434` | Ollama tray app (`ollama app.exe`) owns the server; Electron spawns one only if the port is closed |

## Start / stop

- Desktop: launch **Nexus** (installed at `%LOCALAPPDATA%\Programs\Nexus`). The tray menu has *Health Check*, *Restart Backend*, *Quit*.
- Development: `just dev-backend` and `just dev-frontend` in two terminals.
- Full stop: tray → *Quit*. Electron kills the backend and Next process trees on quit. Ollama is left running by design.

## Health

- **(today)** `GET /api/health` — always 200; read `websockets`, `ws_gap_report`, `llm` (live Ollama probe: `server_down | model_missing | ready_cold | ready_warm`), `circuit_breaker`.
- **(target, Phase 1)** `GET /readyz` → 200 `READY`/`DEGRADED` or 503 `NOT_READY` with `reasons[]`; `GET /healthz` liveness; `GET /metrics` Prometheus text.
- `just doctor` **(target, Phase 0)** checks env, ports, Ollama + model, DB, token and source reachability.

## Failure playbooks

### AI brief shows nothing / "Brief failed"
1. `curl http://localhost:11434/api/tags` — connection refused means the server is down.
2. Check whether the tray is alive with a dead server: `Get-Process "*ollama*"`. If `ollama app` exists but nothing listens on 11434, **quit the tray and relaunch it** (`%LOCALAPPDATA%\Programs\Ollama\ollama app.exe`). A fresh launch binds in ~2 s.
   - Known cause: **Ollama auto-upgrades in place** (see `%LOCALAPPDATA%\Ollama\upgrade.log`); the surviving tray instance then logs `ollama server not ready after retries` in `app.log` forever. Observed 2026-09-11 after the 0.33.3 → 0.34.0 upgrade.
3. First call after > 30 min idle reloads the model (~85 s on this GPU). The backend budgets 300 s per call and keeps the model resident for 30 min (`OLLAMA_CONFIG.keep_alive`).
4. The UI now surfaces `brief_error`; a blank card with no error means the frontend build is stale (next section).

### Frontend edits do not appear in the app
The packaged app serves a **production build**. Run `just build-frontend`, then relaunch Nexus. **(target, Phase 5)** the status bar shows `BUILD MISMATCH` when source and build diverge.

### Backend not responding
Tray → *Restart Backend*. If port 8001 is held by an orphan: `Get-NetTCPConnection -LocalPort 8001` → `Stop-Process -Id <pid>`. Electron also reclaims 3000/8001 on startup.

### Binance REST banned (418 / -1003)
`ingestion/rate_guard.py` parses `banned until <epoch-ms>` and suspends every call to that host until expiry (else 60 s → 600 s backoff). Do **not** restart the backend to "fix" it — restarting resets nothing on Binance's side and the pollers would re-hammer. Wait it out; the WebSocket feeds are unaffected.

### WebSocket gaps
`/api/health.ws_gap_report` lists per-venue gaps (start, end, duration). Binance re-fetches 100 klines on reconnect. OKX/MEXC are frequently blocked by the ISP (PLDT); their absence degrades zone confidence but is not an outage. **(target, Phase 1)** only a Binance outage can trip the circuit breaker; secondary venues mark `DEGRADED`.

### Circuit breaker shows `triggered: true`
**(today)** the breaker latches for the life of the process — any WS gap > 60 s on any venue trips it and only a backend restart clears it. **(target, Phase 1)** event trips auto-clear (feeds healthy 5 min; funding/VPIN/correlation 60 min), loss trips reset at 00:00 UTC, and every trip sends a Telegram message.

### TLS "permissive" mode
Behind the ISP block, the venue clients fall back from strict to permissive TLS. **(today)** silently. **(target, Phase 0)** `data/http.py` logs `tls_downgrade host=…` once per host and counts it in `/metrics`. Seeing it on a network that should not need it is a red flag.

### Free-tier quotas (CMC, Finnhub, OpenSky)
**(today)** no accounting; exhaustion shows up as a source silently going stale. **(target, Phase 1)** `data/quota.py` budgets per source and disables a source until reset instead of hammering it; the Sources panel shows the state.

## Data

- SQLite lives at `NEXUS_DATA_DIR/nexus.db` (**today** `./nexus.db` at the repo root, WAL mode). Back it up by copying `nexus.db`, `nexus.db-wal`, `nexus.db-shm` together while the backend is stopped, or use `sqlite3 nexus.db ".backup out.db"` while running.
- Logs: **(today)** stdout of the uvicorn process (visible in the Electron console). **(target, Phase 1)** `NEXUS_DATA_DIR/logs/backend.jsonl`, JSON lines, 20 MB × 5.
- `.env` is never written by the application. Rotate keys by editing the file and restarting the backend.

## Escalation

Nothing in this system trades live. If a paper order misbehaves: `POST /api/execution/halt` **(target, Phase 3)** cancels open orders and rejects new ones; until then, stop the backend.
