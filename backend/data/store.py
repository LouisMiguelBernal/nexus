"""Async SQLite store: one writer, WAL readers, numbered migrations.

``storage/db.py`` holds a single ``sqlite3`` connection opened with
``check_same_thread=False`` and no lock, and every caller runs it on the
asyncio event loop - including a ``commit()`` per symbol every two seconds
from the trade-ingest loop. Under WAL an ``fsync`` there stalls WebSocket
message processing.

This module moves all of that off the loop (ADR 0003):

- one **writer** connection, serialised by an ``asyncio.Lock``, so SQLite's
  single-writer model is respected explicitly rather than by luck;
- one **reader** connection - under WAL a reader never blocks on the writer;
- schema changes as numbered ``migrations/NNNN_*.sql`` files applied once and
  recorded, so the database is reproducible from an empty file (which the
  packaged app's first run depends on).

The SQL itself is unchanged from ``storage/*``; only the transport differs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger("nexus.store")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

Params = Sequence[Any] | dict[str, Any]


class Migration:
    __slots__ = ("name", "path", "version")

    def __init__(self, version: int, name: str, path: Path) -> None:
        self.version = version
        self.name = name
        self.path = path

    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def __repr__(self) -> str:
        return f"<Migration {self.version:04d}_{self.name}>"


def split_sql(script: str) -> list[str]:
    """Split a migration into individual statements.

    Deliberately NOT ``executescript``: that issues an implicit COMMIT before
    it runs, which silently ends the surrounding transaction and makes a
    migration non-atomic. Splitting lets each migration run inside one real
    transaction - SQLite's DDL is transactional, so a half-applied schema is
    impossible. ``sqlite3.complete_statement`` is the stdlib's own splitter and
    understands string literals and BEGIN...END trigger bodies.
    """
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    remainder = [ln for ln in buffer.splitlines() if ln.strip() and not ln.strip().startswith("--")]
    if remainder:
        raise ValueError(f"migration ends with an incomplete statement: {remainder[0][:80]}")
    return statements


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    """Return migrations sorted by version. Rejects duplicate or malformed names."""
    root = directory or MIGRATIONS_DIR
    found: dict[int, Migration] = {}
    for path in sorted(root.glob("*.sql")):
        match = _MIGRATION_RE.match(path.name)
        if match is None:
            raise ValueError(f"migration filename must be NNNN_lower_snake.sql: {path.name}")
        version = int(match.group(1))
        if version in found:
            raise ValueError(
                f"duplicate migration version {version}: {found[version].path.name} and {path.name}"
            )
        found[version] = Migration(version, match.group(2), path)
    return [found[v] for v in sorted(found)]


class Store:
    """Async SQLite access. Construct, ``await connect()``, ``await migrate()``.

    Every write goes through :meth:`execute` / :meth:`executemany` /
    :meth:`transaction`, which hold ``_write_lock``. Reads use a separate
    connection and take no lock.
    """

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._writer: aiosqlite.Connection | None = None
        self._reader: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        # The task currently holding the writer. A plain Lock is not reentrant,
        # so `await store.execute(...)` inside `async with store.transaction()`
        # deadlocked with no timeout - the natural way to write a multi-statement
        # unit, and a trap worth removing before Phase 3 writes orders that way.
        self._writer_owner: asyncio.Task[Any] | None = None
        self.writes = 0
        self.reads = 0

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> None:
        if self._writer is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = await self._open()
        # A second read-write connection: under WAL it reads the last committed
        # snapshot without waiting on the writer, which is the whole point.
        self._reader = await self._open()
        logger.info("sqlite connected: %s", self.path)

    async def _open(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path, isolation_level=None)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL is the documented-safe pairing with WAL: a crash can lose the
        # last commits, never the database. FULL would put an fsync in the path
        # of every metric snapshot.
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return conn

    async def close(self) -> None:
        for conn in (self._reader, self._writer):
            if conn is not None:
                await conn.close()
        self._reader = None
        self._writer = None
        logger.info("sqlite closed: %s", self.path)

    @property
    def connected(self) -> bool:
        return self._writer is not None

    def _w(self) -> aiosqlite.Connection:
        if self._writer is None:
            raise RuntimeError("Store.connect() has not been awaited")
        return self._writer

    def _r(self) -> aiosqlite.Connection:
        if self._reader is None:
            raise RuntimeError("Store.connect() has not been awaited")
        return self._reader

    # -- migrations ----------------------------------------------------------

    async def migrate(self, directory: Path | None = None) -> int:
        """Apply every unapplied migration in order. Returns the resulting version."""
        migrations = discover_migrations(directory)
        async with self._write_lock:
            writer = self._w()
            await writer.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at REAL NOT NULL
                )
                """
            )
            cursor = await writer.execute("SELECT version FROM schema_migrations")
            applied = {int(row[0]) for row in await cursor.fetchall()}
            await cursor.close()

            for migration in migrations:
                if migration.version in applied:
                    continue
                started = time.monotonic()
                try:
                    await writer.execute("BEGIN")
                    for statement in split_sql(migration.sql()):
                        await writer.execute(statement)
                    await writer.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                        (migration.version, migration.name, time.time()),
                    )
                    await writer.execute("COMMIT")
                except Exception:
                    # suppress: a failed ROLLBACK must never replace the real error
                    with contextlib.suppress(sqlite3.Error):
                        await writer.execute("ROLLBACK")
                    logger.exception("migration %s failed; database left at the previous version", migration)
                    raise
                logger.info(
                    "applied migration %04d_%s in %.0fms",
                    migration.version,
                    migration.name,
                    (time.monotonic() - started) * 1000,
                )
        return await self.schema_version()

    async def schema_version(self) -> int:
        rows = await self.fetch_all("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations")
        return int(rows[0]["v"]) if rows else 0

    # -- writes --------------------------------------------------------------

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[tuple[aiosqlite.Connection, bool]]:
        """Acquire the writer, reentrantly for the task that already holds it.

        Yields ``(connection, joined)`` where ``joined`` is True when this call
        is nested inside an open transaction owned by the same task - the
        caller must then not issue its own BEGIN/COMMIT.
        """
        current = asyncio.current_task()
        if self._writer_owner is not None and self._writer_owner is current:
            yield self._w(), True
            return
        async with self._write_lock:
            self._writer_owner = current
            try:
                yield self._w(), False
            finally:
                self._writer_owner = None

    async def execute(self, sql: str, params: Params = ()) -> int:
        """Run one writing statement. Returns the number of rows affected.

        Always ``rowcount``, never ``lastrowid``: sqlite3 leaves ``lastrowid``
        holding the last INSERT's rowid, so a DELETE or UPDATE used to report
        that stale id instead of the row count - a 3-row DELETE returned 5.
        Use :meth:`insert` when you want the new row's id.
        """
        async with self._write() as (writer, _joined):
            cursor = await writer.execute(sql, params)
            try:
                self.writes += 1
                return int(cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else 0)
            finally:
                await cursor.close()

    async def insert(self, sql: str, params: Params = ()) -> int:
        """Run an INSERT and return the new ``lastrowid``."""
        async with self._write() as (writer, _joined):
            cursor = await writer.execute(sql, params)
            try:
                self.writes += 1
                return int(cursor.lastrowid or 0)
            finally:
                await cursor.close()

    async def executemany(self, sql: str, rows: Iterable[Params]) -> int:
        """Run one statement over many parameter sets in a single transaction."""
        payload = list(rows)
        if not payload:
            return 0
        async with self._write() as (writer, joined):
            if not joined:
                await writer.execute("BEGIN")
            try:
                await writer.executemany(sql, payload)
                if not joined:
                    await writer.execute("COMMIT")
            except Exception:
                if not joined:
                    with contextlib.suppress(sqlite3.Error):
                        await writer.execute("ROLLBACK")
                raise
            self.writes += len(payload)
            return len(payload)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Hold the writer for several statements, committed or rolled back together.

        Reentrant: ``execute``/``executemany`` called inside the block join this
        transaction instead of deadlocking on the writer lock. Phase 3 needs
        this - an order and its state transition must land atomically.
        """
        async with self._write() as (writer, joined):
            if joined:
                yield writer  # already inside an outer transaction
                return
            await writer.execute("BEGIN")
            try:
                yield writer
            except Exception:
                with contextlib.suppress(sqlite3.Error):
                    await writer.execute("ROLLBACK")
                raise
            await writer.execute("COMMIT")
            self.writes += 1

    # -- reads ---------------------------------------------------------------

    async def fetch_all(self, sql: str, params: Params = ()) -> list[dict[str, Any]]:
        cursor = await self._r().execute(sql, params)
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        self.reads += 1
        return [dict(row) for row in rows]

    async def fetch_one(self, sql: str, params: Params = ()) -> dict[str, Any] | None:
        cursor = await self._r().execute(sql, params)
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        self.reads += 1
        return dict(row) if row is not None else None

    async def fetch_value(self, sql: str, params: Params = ()) -> Any:
        row = await self.fetch_one(sql, params)
        return None if row is None else next(iter(row.values()), None)

    # -- introspection -------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "path": str(self.path),
            "connected": self.connected,
            "size_bytes": size,
            "schema_version": await self.schema_version() if self.connected else None,
            "writes": self.writes,
            "reads": self.reads,
            "write_lock_held": self._write_lock.locked(),
        }
