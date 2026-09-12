"""data.store - migrations, single-writer serialisation, reads under WAL."""

import asyncio
import sqlite3

import pytest

from backend.data.store import Store, discover_migrations, split_sql


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    await s.migrate()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# migrations
# ---------------------------------------------------------------------------


def test_shipped_migrations_are_well_formed_and_ordered():
    migrations = discover_migrations()
    assert migrations, "no migrations found"
    versions = [m.version for m in migrations]
    assert versions == sorted(versions) and len(set(versions)) == len(versions)
    assert versions[0] == 1
    assert all(m.sql().strip() for m in migrations)


def test_malformed_migration_name_is_rejected(tmp_path):
    (tmp_path / "oops.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="NNNN_lower_snake"):
        discover_migrations(tmp_path)


def test_duplicate_migration_version_is_rejected(tmp_path):
    (tmp_path / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0001_b.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate migration version"):
        discover_migrations(tmp_path)


async def test_database_is_reproducible_from_an_empty_file(store):
    tables = {r["name"] for r in await store.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"zones", "zone_watchlist", "alerts", "trade_journal", "briefs", "metric_snapshots"} <= tables
    assert "alert_state" in tables
    assert await store.schema_version() == max(m.version for m in discover_migrations())


async def test_migrate_is_idempotent(store):
    version = await store.schema_version()
    assert await store.migrate() == version
    rows = await store.fetch_all("SELECT version FROM schema_migrations ORDER BY version")
    assert len(rows) == len({r["version"] for r in rows}), "no migration applied twice"


def test_split_sql_keeps_statements_whole():
    script = """
-- a leading comment
CREATE TABLE t (name TEXT);
INSERT INTO t (name) VALUES ('a; not a separator');
-- a trailing comment with no statement after it
"""
    statements = split_sql(script)
    assert len(statements) == 2, statements
    assert statements[1].endswith("('a; not a separator');")
    assert split_sql("-- comments only\n") == []
    with pytest.raises(ValueError, match="incomplete statement"):
        split_sql("CREATE TABLE unfinished (")


async def test_failed_migration_rolls_back_and_does_not_record(tmp_path):
    """A migration is atomic: a later statement failing undoes the earlier ones."""
    s = Store(tmp_path / "broken.db")
    await s.connect()
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE good (id INTEGER);", encoding="utf-8")
    (tmp_path / "0002_bad.sql").write_text(
        "CREATE TABLE bad (id INTEGER);\nNOT SQL AT ALL;\n", encoding="utf-8"
    )
    with pytest.raises(sqlite3.Error):
        await s.migrate(tmp_path)
    assert await s.schema_version() == 1, "the good migration stays applied"
    tables = {r["name"] for r in await s.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "good" in tables
    assert "bad" not in tables, "the failed migration's DDL must have rolled back"
    await s.close()


# ---------------------------------------------------------------------------
# reads and writes
# ---------------------------------------------------------------------------


async def test_execute_returns_lastrowid_and_reads_see_it(store):
    rowid = await store.execute(
        "INSERT INTO alerts (alert_type, symbol, message) VALUES (?, ?, ?)",
        ("zone_approach", "BTCUSDT", "near"),
    )
    assert rowid > 0
    row = await store.fetch_one("SELECT * FROM alerts WHERE id = ?", (rowid,))
    assert row is not None and row["symbol"] == "BTCUSDT"
    assert await store.fetch_value("SELECT COUNT(*) FROM alerts") == 1


async def test_executemany_is_one_transaction(store):
    rows = [("BTCUSDT", "obi", float(i), float(i) / 10, None) for i in range(500)]
    written = await store.executemany(
        "INSERT INTO metric_snapshots (symbol, metric, t, value, extra) VALUES (?, ?, ?, ?, ?)", rows
    )
    assert written == 500
    assert await store.fetch_value("SELECT COUNT(*) FROM metric_snapshots") == 500
    assert await store.executemany("INSERT INTO metric_snapshots VALUES (?,?,?,?,?,?)", []) == 0


async def test_concurrent_writers_are_serialised_and_none_are_lost(store):
    """Three tasks x 200 inserts: SQLite's single-writer model is respected."""

    async def writer(tag: str) -> None:
        for i in range(200):
            await store.execute(
                "INSERT INTO metric_snapshots (symbol, metric, t, value) VALUES (?, ?, ?, ?)",
                (tag, "obi", float(i), float(i)),
            )

    await asyncio.gather(writer("A"), writer("B"), writer("C"))
    assert await store.fetch_value("SELECT COUNT(*) FROM metric_snapshots") == 600
    per_symbol = await store.fetch_all(
        "SELECT symbol, COUNT(*) AS n FROM metric_snapshots GROUP BY symbol ORDER BY symbol"
    )
    assert [r["n"] for r in per_symbol] == [200, 200, 200]


async def test_reads_are_not_blocked_by_a_held_write_transaction(store):
    """WAL: the reader connection answers while the writer holds a transaction."""
    await store.execute("INSERT INTO alerts (alert_type, message) VALUES ('seed', 'x')")

    async with store.transaction() as conn:
        await conn.execute("INSERT INTO alerts (alert_type, message) VALUES ('pending', 'y')")
        visible = await asyncio.wait_for(store.fetch_value("SELECT COUNT(*) FROM alerts"), timeout=2.0)
        assert visible == 1, "uncommitted write must not be visible to the reader"

    assert await store.fetch_value("SELECT COUNT(*) FROM alerts") == 2


async def test_transaction_rolls_back_on_error(store):
    with pytest.raises(RuntimeError):
        async with store.transaction() as conn:
            await conn.execute("INSERT INTO alerts (alert_type, message) VALUES ('a', 'b')")
            raise RuntimeError("caller failed")
    assert await store.fetch_value("SELECT COUNT(*) FROM alerts") == 0


async def test_use_before_connect_is_a_clear_error(tmp_path):
    s = Store(tmp_path / "x.db")
    with pytest.raises(RuntimeError, match="connect"):
        await s.fetch_all("SELECT 1")


async def test_stats_reports_version_and_counters(store):
    await store.execute("INSERT INTO alerts (alert_type, message) VALUES ('a', 'b')")
    stats = await store.stats()
    assert stats["connected"] and stats["writes"] >= 1 and stats["size_bytes"] > 0
    assert stats["schema_version"] >= 1 and stats["write_lock_held"] is False
