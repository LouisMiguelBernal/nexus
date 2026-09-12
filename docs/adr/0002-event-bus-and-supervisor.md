# ADR 0002: Bounded event bus with synchronous publish, and a task supervisor

Status: accepted · 2026-09-11

## Context

`monitoring/event_bus.py` documents bounded per-subscriber queues with drop-oldest, but `publish()` awaits every handler inline through `asyncio.gather`: a slow subscriber blocks the producer loop. Eight background loops are started with `asyncio.create_task` in `lifespan()`; no handle is retained, nothing restarts a crashed loop, and shutdown cannot cancel them.

## Decision

- `core/bus.py`: `subscribe(topic, handler, *, maxsize=256, policy="drop_oldest" | "coalesce")` spawns one consumer task per subscriber. `publish()` is synchronous (`put_nowait`); on a full queue it drops the oldest event or replaces it (coalesce) and increments `nexus_bus_dropped_total{topic,subscriber}`. Wildcard topics (`market.trade.*`).
- `core/supervisor.py`: `Service(name, interval_s)` with `run_once()`/`run()`. The supervisor retains handles, restarts on exception with backoff 1→60 s + jitter, cancels and awaits with a 5 s deadline on shutdown, and exposes `status()` (`crash_count`, `last_error`) to `/readyz`.
- `while True` is banned from application code (checked by grep in `just check` from Phase 1).

## Consequences

- A slow consumer costs itself dropped events, never the producer. Drops are visible in metrics instead of invisible as latency.
- Every loop is restartable and observable. A bug in a loop is a metric and a log line, not a silently dead feature for the life of the process.
- Exactly-once delivery is not offered; consumers must tolerate gaps (they already do — every loop recomputes from current state).
