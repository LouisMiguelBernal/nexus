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

## [0.3.0] - 2026-09-09
- World layer: cross-asset board, FRED macro, Treasury curve, geopolitical risk tier feeding the macro gate.
- Alpha engine at 12 signals x 5 regimes; VPIN; TSMOM and cross-sectional funding factors; validation library (walk-forward, CPCV, deflated Sharpe, cost sensitivity).
- Electron standalone shell with tray; Gemma 4 briefs with a model fallback chain and a live LLM health probe.
