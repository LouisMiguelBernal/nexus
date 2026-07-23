"""
Verification: P1-2 - VPIN on volume clock.

Plan clause:
> "Inject synthetic toxic flow; assert `VPIN > 0.85` triggers circuit
>  breaker halt within one cycle."
"""

from backend.computation.vpin import VPINTracker
from backend.risk.circuit_breaker import CircuitBreaker


def test_balanced_flow_keeps_vpin_low():
    v = VPINTracker(bucket_target_notional=1_000.0, window=10, toxic_threshold=0.85)
    for i in range(200):
        side = "buy" if i % 2 == 0 else "sell"
        v.add_trade(price=100.0, qty=2.0, side=side, ts=float(i))
    snap = v.snapshot()
    assert snap.buckets_closed >= 10
    # Alternating buy/sell with 5 trades/bucket yields per-bucket imbalance
    # of |3-2|/5 = 0.2 exactly - loosen to a non-toxic ceiling.
    assert snap.running <= 0.25, f"balanced flow must keep VPIN low, got {snap.running}"
    assert snap.toxic is False


def test_one_sided_toxic_flow_trips_threshold():
    v = VPINTracker(bucket_target_notional=1_000.0, window=10, toxic_threshold=0.85)
    # Every trade is a buy - maximum imbalance.
    for i in range(200):
        v.add_trade(price=100.0, qty=2.0, side="buy", ts=float(i))
    snap = v.snapshot()
    assert snap.running > 0.85, f"expected toxic VPIN, got {snap.running}"
    assert snap.toxic is True


def test_circuit_breaker_event_trigger_on_vpin_toxic():
    cb = CircuitBreaker()
    tripped = cb.on_vpin("BTCUSDT", vpin=0.92)
    assert tripped is True
    assert cb.state.triggered is True
    assert cb.state.signals_suppressed is True
    events = cb.recent_events()
    assert events and events[-1]["kind"] == "vpin_toxic"


def test_bucket_target_resize():
    v = VPINTracker(bucket_target_notional=1_000.0)
    v.update_bucket_target(5_000.0)
    assert v.bucket_target_notional == 5_000.0
