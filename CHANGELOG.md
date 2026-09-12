# Changelog

All notable changes to Nexus are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: SemVer. The single source of the version number is the `VERSION` file.

## [Unreleased]

### Added
- Git repository at the real project root with a baseline commit. `.gitignore`/`.gitattributes` cover secrets, SQLite files, build output and installers.
- Tooling: `pyproject.toml` + `uv.lock`, `justfile`, pre-commit, GitHub Actions CI, `VERSION`, this changelog, root README and LICENSE.

### Changed
- Design mockups moved from `nexus app layout/` to `docs/design/`.

### Removed
- `scripts/health_check.py` (imported a removed config key; dead since the paid-API purge), `scripts/setup.sh` (wrong port), `notebooks/` (API liveness smoke test, superseded by `just doctor`), orphaned `nexus_root.db`.

### Fixed
- Platinum zone tier was unreachable (required a CoinGlass flag no caller passed); it now means 3+ venues, persisted >= 30 min, top decile of the cycle.
- Squeeze meter's liquidation-proximity term (25 of 100 points) was structurally zero; it is now fed from recent liquidation clusters.
- VPIN: whale prints are split across bucket boundaries instead of pinning VPIN at 1.0; bucket size is per symbol from 24h volume, refreshed hourly.
- Funding z-score no longer reads minutes of samples as a week (which tripped the circuit breaker on every cold start); history is seeded from Binance at startup.
- Correlation matrix joins bars on open_time instead of by count; the Kelly route's call had passed a non-existent kwarg and always raised, so its correlation haircut was silently 1.0.
- VaR uses scipy's Student-t quantile (the fallback was a scaled normal) and a fitted df in component VaR; the Euler-identity test asserted nothing and now does.
- TSMOM was fed 15m bars as if hourly; kline history is now an upsert-by-open_time buffer with resampling, so gap backfills cannot duplicate bars either.
- Twenty-two silent except-sites in main.py (DEBUG-level or `pass`) now warn; TLS fallback happens in one place and is logged and counted.
- The AI brief generator shares the app's LLM client (health was probing a client that never generated); FinBERT inference runs off the event loop.
- npm scripts call next/tsc/eslint/electron through `node` directly: npm's .cmd shims break on the `&` in this project's path.

### Security
- Backend binds 127.0.0.1 and requires a local bearer token on /api/* when one is configured (env or `data/api_token`); the Electron shell generates and injects it. `/diag` no longer returns an API-key prefix.

## [0.3.0] - 2026-09-09
- World layer: cross-asset board, FRED macro, Treasury curve, geopolitical risk tier feeding the macro gate.
- Alpha engine at 12 signals x 5 regimes; VPIN; TSMOM and cross-sectional funding factors; validation library (walk-forward, CPCV, deflated Sharpe, cost sensitivity).
- Electron standalone shell with tray; Gemma 4 briefs with a model fallback chain and a live LLM health probe.
