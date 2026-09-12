# ADR 0003: aiosqlite with one writer connection, off the event loop

Status: accepted · 2026-09-11

## Context

`storage/db.py` holds one global `sqlite3` connection (`check_same_thread=False`, no lock) and every write — including a `commit()` per symbol every 2 s from the trade-ingest loop — runs on the asyncio event loop thread. `fsync` latency stalls WebSocket message processing. The same connection is also reachable from a thread pool. Postgres was rejected: local-first, single operator, no service to run.

## Decision

`data/store.py` wraps `aiosqlite`: one writer connection behind an `asyncio.Lock`, read connections as needed, WAL mode, `PRAGMA synchronous=NORMAL`. Metric snapshots are batched and flushed by a service every 5 s instead of committed per symbol per tick. Schema changes go through numbered migrations (`data/migrations/000N_*.sql`) tracked in a `schema_version` table. The SQL itself is unchanged.

## Consequences

- No blocking I/O on the loop; verified by a soak with `PYTHONASYNCIODEBUG=1` reporting zero slow callbacks from `data/`.
- Write contention is serialised by design; throughput is bounded by SQLite's single-writer model, which is far above this system's needs (tens of writes per second).
- Migrations make the DB reproducible from an empty file, which the packaged app's first run relies on.
