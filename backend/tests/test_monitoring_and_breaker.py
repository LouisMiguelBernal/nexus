"""
Verification: P2 monitoring + event-triggered circuit breaker.

Plan clause:
> "Inject 300 ms latency; assert alert fires within one polling cycle;
>  inject 30 s staleness; assert flagged feed."
"""

import time

from backend.monitoring.latency_slo import LatencyTracker, LatencySLO
from backend.monitoring.staleness import StalenessDetector
from backend.risk.circuit_breaker import CircuitBreaker


def test_latency_tracker_flags_budget_breach():
    tracker = LatencyTracker(
        slos=[LatencySLO(stream="binance_trade", budget_ms=250.0,
                         breach_window=10, breach_threshold=5)],
    )
    # 10 samples, 6 of which exceed the budget - should trip.
    for _ in range(4):
        tracker.record("binance_trade", 100.0)
    for _ in range(6):
        tracker.record("binance_trade", 300.0)
    assert tracker.breached("binance_trade") is True
    snap = tracker.snapshot()["binance_trade"]
    assert snap["breached"] is True


def test_latency_tracker_handles_fresh_stream_gracefully():
    tracker = LatencyTracker(default_budget_ms=250.0)
    tracker.record("new_stream", 50.0)
    snap = tracker.snapshot()
    assert "new_stream" in snap
    assert snap["new_stream"]["breached"] is False


def test_staleness_detector_flags_idle_feed():
    det = StalenessDetector(multiplier=3.0)
    # Regular 1-second arrivals, but the most recent one was 30s ago.
    now = time.time()
    for i in range(20):
        det.record_arrival("binance", ts=now - 50 + i)  # last arrival ≈ 30s ago
    report = det.check("binance")
    assert report["stale"] is True, report
    assert report["seconds_since_last"] >= 20.0


def test_staleness_ingests_gap_report():
    det = StalenessDetector()
    mock_report = {
        "binance": {"connected": True, "last_event_time": time.time() - 5.0,
                    "seconds_since_last_event": 5.0, "gap_log": []},
    }
    det.ingest_gap_report(mock_report)
    assert "binance" in det._arrivals


def test_circuit_breaker_event_triggers():
    cb = CircuitBreaker()
    # VaR breach
    assert cb.on_var_breach(realized_pnl=-500, var_99=200) is True
    assert cb.state.triggered is True

    # Reset to try another trigger
    cb2 = CircuitBreaker()
    # WS outage via mocked gap_report
    tripped = cb2.on_ws_gap_report({
        "binance": {"connected": True, "last_event_time": 0,
                    "seconds_since_last_event": 120.0, "gap_log": []},
    })
    assert tripped is True
    assert cb2.state.trigger_reason.startswith("WS stream")

    cb3 = CircuitBreaker()
    assert cb3.on_funding_zscore("BTCUSDT", zscore=3.5) is True

    cb4 = CircuitBreaker()
    assert cb4.on_funding_zscore("BTCUSDT", zscore=1.5) is False
    assert cb4.state.triggered is False


def test_correlation_shock_trigger():
    cb = CircuitBreaker()
    now = time.time()
    # Seed a baseline ρ=0.3.
    assert cb.on_correlation_snapshot(0.3, ts=now - 60) is False
    # A jump to ρ=0.9 exceeds the 0.30 delta threshold → shock.
    assert cb.on_correlation_snapshot(0.9, ts=now) is True
