# ADR 0001: Keep `backend/` as the Python package root

Status: accepted · 2026-09-11

## Context

The revamp decomposes a 3,395-line `backend/main.py` into `core/`, `data/`, `strategy/`, `risk/`, `execution/`, `research/`, `api/`, `services/`, `ops/`. A rename to a `nexus/` package was considered.

## Decision

Keep `backend/`. Add the new subpackages inside it. `backend/main.py` becomes a shim (`from backend.app import create_app; app = create_app()`) so the uvicorn target `backend.main:app` never changes.

## Consequences

- 116 modules that import `backend.*`, the test conftest, the Electron launcher and the documented invariants keep working unchanged.
- Module moves are verbatim (`ingestion/*` → `data/feeds/*` re-exported), which keeps Phase 1 diffs reviewable.
- The name is slightly less pretty than `nexus/`. Not worth the churn; a rename buys no boundary.
