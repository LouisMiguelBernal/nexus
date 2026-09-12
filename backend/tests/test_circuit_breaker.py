"""Circuit breaker: venue-scoped WS trips, expiry, and threshold/event independence.

The old implementation had one boolean trip with no way back. These tests pin
the behaviour that replaced it.
"""

from backend.risk.circuit_breaker import TRIP_POLICY, CircuitBreaker


class FakeClock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def gap(streams: dict[str, float], connected: bool = True) -> dict:
    """Build a WSManager.gap_report()-shaped dict: {stream: idle_seconds}."""
    return {
        name: {
            "connected": connected,
            "last_event_time": 0.0,
            "seconds_since_last_event": secs,
            "gap_log": [],
        }
        for name, secs in streams.items()
    }


# ---------------------------------------------------------------------------
# WS outage is scoped to required venues
# ---------------------------------------------------------------------------


def test_secondary_venue_outage_degrades_but_does_not_suppress_signals():
    """OKX and MEXC are routinely ISP-blocked here. Losing them is information,
    not a reason to stop trading - this fired within hours of every start."""
    cb = CircuitBreaker(FakeClock())
    tripped = cb.on_ws_gap_report(gap({"binance_futures": 1.0, "okx": 400.0, "mexc": 900.0}))
    assert tripped is False
    state = cb.state
    assert state.triggered is False and state.signals_suppressed is False
    assert state.degraded is True
    assert "okx" in state.degraded_reason and "mexc" in state.degraded_reason
    assert cb.can_trade() is True


def test_required_venue_outage_trips():
    cb = CircuitBreaker(FakeClock())
    assert cb.on_ws_gap_report(gap({"binance_futures": 120.0, "okx": 1.0})) is True
    state = cb.state
    assert state.triggered and state.signals_suppressed
    assert state.trigger_reason.startswith("WS stream")
    assert cb.can_trade() is False
    assert [t["kind"] for t in state.active_trips] == ["ws_outage"]


def test_disconnected_required_venue_trips_even_when_recent():
    cb = CircuitBreaker(FakeClock())
    assert cb.on_ws_gap_report(gap({"binance_futures": 2.0}, connected=False)) is True


def test_ws_trip_clears_only_after_feeds_stay_healthy():
    clock = FakeClock()
    cb = CircuitBreaker(clock)
    cb.on_ws_gap_report(gap({"binance_futures": 120.0}))
    assert cb.state.triggered

    healthy_for = TRIP_POLICY["ws_outage"]["healthy_for_s"]
    clock.advance(30)
    cb.on_ws_gap_report(gap({"binance_futures": 1.0}))  # recovery clock starts HERE
    assert cb.state.triggered, "recovery must be sustained, not instant"

    clock.advance(healthy_for - 1)
    assert cb.state.triggered, "one second short of the required healthy window"
    clock.advance(2)
    assert cb.state.triggered is False, "clears once required feeds have held"
    assert cb.can_trade() is True
    assert any(e["kind"] == "ws_outage_cleared" for e in cb.recent_events())


def test_flapping_feed_restarts_the_recovery_clock():
    clock = FakeClock()
    cb = CircuitBreaker(clock)
    cb.on_ws_gap_report(gap({"binance_futures": 120.0}))
    clock.advance(200)
    cb.on_ws_gap_report(gap({"binance_futures": 1.0}))  # healthy clock starts
    clock.advance(200)
    cb.on_ws_gap_report(gap({"binance_futures": 120.0}))  # down again -> reset
    clock.advance(200)
    cb.on_ws_gap_report(gap({"binance_futures": 1.0}))
    clock.advance(100)
    assert cb.state.triggered, "300s of health had not accrued since the last outage"


# ---------------------------------------------------------------------------
# Event trips expire
# ---------------------------------------------------------------------------


def test_event_trip_expires_without_recurrence():
    clock = FakeClock()
    cb = CircuitBreaker(clock)
    assert cb.on_vpin("BTCUSDT", 0.92) is True
    assert cb.state.triggered
    clock.advance(TRIP_POLICY["vpin_toxic"]["after_s"] - 1)
    assert cb.state.triggered
    clock.advance(2)
    assert cb.state.triggered is False
    assert any(e["kind"] == "vpin_toxic_cleared" for e in cb.recent_events())


def test_recurrence_refreshes_the_expiry():
    clock = FakeClock()
    cb = CircuitBreaker(clock)
    cb.on_funding_zscore("BTCUSDT", 3.5)
    clock.advance(3000)
    cb.on_funding_zscore("BTCUSDT", 3.6)  # re-arms
    clock.advance(1000)
    assert cb.state.triggered, "the clock restarts on each recurrence"
    clock.advance(2700)
    assert cb.state.triggered is False


def test_multiple_trips_are_tracked_independently():
    clock = FakeClock()
    cb = CircuitBreaker(clock)
    cb.on_vpin("BTCUSDT", 0.9)
    clock.advance(60)
    cb.on_funding_zscore("ETHUSDT", 4.0)
    assert {t["kind"] for t in cb.state.active_trips} == {"vpin_toxic", "funding_spike"}
    assert "+1 more" in cb.state.trigger_reason
    clock.advance(TRIP_POLICY["vpin_toxic"]["after_s"] - 30)
    kinds = {t["kind"] for t in cb.state.active_trips}
    assert kinds == {"funding_spike"}, "one expiring must not clear the other"
    assert cb.state.triggered is True


# ---------------------------------------------------------------------------
# Threshold triggers and their independence from event trips
# ---------------------------------------------------------------------------


def test_daily_loss_trips_and_resets():
    clock = FakeClock()
    cb = CircuitBreaker(clock)
    cb.initialize(10_000.0)
    assert cb.update(9_800.0).triggered is False  # -2%
    state = cb.update(9_400.0)  # -6% > 5% limit
    assert state.triggered and state.leverage_reduced
    assert [t["kind"] for t in state.active_trips] == ["daily_loss"]
    cb.daily_reset()
    after = cb.state
    assert after.triggered is False and after.daily_loss_pct == 0.0
    assert cb.can_trade() is True


def test_update_does_not_wipe_event_trips():
    """Regression: update() used to reassign the whole state object, which would
    have silently cleared every event trip the moment an equity feed existed."""
    cb = CircuitBreaker(FakeClock())
    cb.initialize(10_000.0)
    cb.on_vpin("BTCUSDT", 0.95)
    assert cb.state.triggered
    for equity in (10_050.0, 10_100.0, 10_020.0):
        cb.update(equity)
    assert cb.state.triggered, "a profitable equity tick must not clear a toxic-flow trip"
    assert [t["kind"] for t in cb.state.active_trips] == ["vpin_toxic"]


def test_daily_reset_does_not_clear_event_trips():
    cb = CircuitBreaker(FakeClock())
    cb.initialize(10_000.0)
    cb.update(9_400.0)
    cb.on_vpin("BTCUSDT", 0.95)
    cb.daily_reset()
    assert [t["kind"] for t in cb.state.active_trips] == ["vpin_toxic"]


def test_drawdown_uses_peak_not_day_start():
    cb = CircuitBreaker(FakeClock())
    cb.initialize(10_000.0)
    cb.update(12_000.0)  # new peak
    state = cb.update(10_100.0)  # -15.8% from peak, but +1% on the day
    assert state.drawdown_from_peak_pct > 15.0
    assert state.daily_loss_pct < 0
    assert "drawdown" in {t["kind"] for t in state.active_trips}


def test_leverage_cap_halves_only_while_reduced():
    cb = CircuitBreaker(FakeClock())
    cb.initialize(10_000.0)
    assert cb.get_leverage_cap(10) == 10
    cb.update(9_600.0)  # -4% -> past the 3% reduction threshold
    assert cb.state.leverage_reduced and cb.get_leverage_cap(10) == 5
    assert cb.get_leverage_cap(1) == 1


# ---------------------------------------------------------------------------
# Listeners and payload shape
# ---------------------------------------------------------------------------


def test_listeners_fire_on_trip_and_clear_and_a_bad_one_is_isolated():
    clock = FakeClock()
    cb = CircuitBreaker(clock)
    seen: list[tuple[str, str]] = []
    cb.add_listener(lambda action, trip: (_ for _ in ()).throw(RuntimeError("boom")))
    cb.add_listener(lambda action, trip: seen.append((action, trip.kind)))

    cb.on_vpin("BTCUSDT", 0.95)
    assert seen == [("tripped", "vpin_toxic")]
    cb.on_vpin("BTCUSDT", 0.96)  # re-arm: not a new trip
    assert len(seen) == 1
    clock.advance(TRIP_POLICY["vpin_toxic"]["after_s"] + 1)
    _ = cb.state
    assert seen[-1] == ("cleared", "vpin_toxic")


def test_to_dict_keeps_every_key_the_frontend_reads():
    cb = CircuitBreaker(FakeClock())
    payload = cb.state.to_dict()
    for key in (
        "triggered",
        "trigger_reason",
        "daily_loss_pct",
        "weekly_loss_pct",
        "drawdown_from_peak_pct",
        "leverage_reduced",
        "signals_suppressed",
        "reset_time",
    ):
        assert key in payload, f"RiskTab reads {key}"
    assert payload["reset_time"] == "00:00 UTC"
    assert payload["active_trips"] == [] and payload["degraded"] is False
