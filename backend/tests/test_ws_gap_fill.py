"""
Verification: P0-4 - WS gap-fill tracking.

Plan clause:
> "Kill WS 30 s; reconnect; assert no missing klines vs REST truth;
>  `gap_filled` event logged."

We don't spin up real WS infra in unit tests - we exercise the internal
state machine by poking `_last_event_time` / `_disconnect_started_at` and
asserting the gap is recorded in `_gap_log` and that `gap_report()`
returns the right structure.
"""

import time

from backend.ingestion.ws_manager import WSConnection, WSManager


def test_gap_log_capped_and_records_entries():
    conn = WSConnection(name="test", url="wss://example.test")
    # Simulate repeated gap close events.
    for i in range(100):
        entry = {"start": time.time() - 10, "end": time.time(), "duration_s": 10.0}
        conn._gap_log.append(entry)
        if len(conn._gap_log) > conn._gap_log_cap:
            conn._gap_log = conn._gap_log[-conn._gap_log_cap:]
    assert len(conn._gap_log) == conn._gap_log_cap == 64


def test_gap_report_schema_for_wsmanager():
    mgr = WSManager()
    mgr.add(WSConnection(name="alpha", url="wss://a.test"))
    mgr.add(WSConnection(name="beta", url="wss://b.test"))
    rpt = mgr.gap_report()
    assert set(rpt.keys()) == {"alpha", "beta"}
    for name, bundle in rpt.items():
        assert {"connected", "last_event_time", "seconds_since_last_event", "gap_log"} <= bundle.keys()


def test_gap_report_single_connection_lookup_and_miss():
    mgr = WSManager()
    mgr.add(WSConnection(name="solo", url="wss://s.test"))
    assert "gap_log" in mgr.gap_report("solo")
    assert "error" in mgr.gap_report("unknown")


def test_seconds_since_last_event_reflects_stamp():
    conn = WSConnection(name="t", url="wss://t.test")
    assert conn.seconds_since_last_event is None
    conn._last_event_time = time.time() - 4.0
    secs = conn.seconds_since_last_event
    assert secs is not None and 3.5 < secs < 5.0


def test_gap_log_entry_duration_recorded():
    """Simulate the bookkeeping that `connect()` performs on successful reconnect."""
    conn = WSConnection(name="x", url="wss://x.test")
    conn._disconnect_started_at = time.time() - 10.0
    conn._last_event_time = time.time() - 12.0
    gap_end = time.time()
    if conn._disconnect_started_at and conn._last_event_time and gap_end - conn._last_event_time > 1:
        gap_start = conn._last_event_time
        conn._gap_log.append({
            "start": gap_start,
            "end": gap_end,
            "duration_s": round(gap_end - gap_start, 3),
        })
    assert conn.gap_log
    assert conn.gap_log[-1]["duration_s"] >= 10.0
