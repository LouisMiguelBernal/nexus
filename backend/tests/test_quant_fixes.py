"""Phase 0 correctness fixes - each test pins a defect found in the audit.

1. Platinum zone tier was unreachable (needed a CoinGlass flag nobody passed).
2. Squeeze meter's liquidation-proximity term was structurally zero.
3. VPIN saturated on whale prints and used one bucket size for every symbol.
4. Funding z-score read minutes of samples as a week and tripped the breaker.
5. Correlation aligned series by count, not timestamp.
6. VaR's Student-t quantile without scipy was a scaled normal.
"""

import time

import pytest

from backend.computation.correlation import correlation_matrix
from backend.computation.funding import FundingTracker
from backend.computation.golden_zone import GoldenZoneEngine
from backend.computation.liquidation_imbalance import nearest_liquidation_distance_pct
from backend.computation.squeeze_risk import SqueezeRiskMeter
from backend.computation.vpin import VPINTracker
from backend.config import ZONE_TIERS
from backend.risk.var import _student_t_quantile

# ---------------------------------------------------------------------------
# 1. Platinum tier
# ---------------------------------------------------------------------------


def _book(price: float, bid_qty: float, ask_qty: float) -> dict:
    return {"bids": [[price, bid_qty]], "asks": [[price * 1.0001, ask_qty]]}


def test_platinum_requires_three_venues_persistence_and_top_score():
    engine = GoldenZoneEngine("BTCUSDT")
    price = 10_000.0
    for venue in ("binance", "okx", "mexc"):
        engine.update_order_book(venue, _book(price, bid_qty=50.0, ask_qty=1.0))

    zones = engine.detect_zones()
    assert zones, "three overlapping books must produce a zone"
    top = zones[0]
    assert top.exchange_count == 3
    assert top.tier == "golden", "a brand-new three-venue zone is golden, not platinum"

    # Age the zone past the platinum persistence threshold and re-detect.
    for zone in engine._zone_history.values():
        zone.first_seen -= 3600.0
    zones = engine.detect_zones()
    assert zones[0].tier == "platinum"
    assert zones[0].weight == ZONE_TIERS["platinum"]["weight"]


def test_two_venue_zone_never_becomes_platinum():
    engine = GoldenZoneEngine("BTCUSDT")
    for venue in ("binance", "okx"):
        engine.update_order_book(venue, _book(10_000.0, 50.0, 1.0))
    engine.detect_zones()
    for zone in engine._zone_history.values():
        zone.first_seen -= 7200.0
    assert engine.detect_zones()[0].tier == "silver"


# ---------------------------------------------------------------------------
# 2. Squeeze liquidation-proximity term
# ---------------------------------------------------------------------------


def test_nearest_liquidation_distance_finds_recent_cluster_near_mark():
    now = time.time()
    events = [
        {"price": 101.0, "usd_value": 150_000.0, "time": now * 1000, "side": "SELL"},
        {"price": 101.05, "usd_value": 80_000.0, "time": now * 1000, "side": "SELL"},
        {"price": 110.0, "usd_value": 5_000_000.0, "time": (now - 7200) * 1000, "side": "BUY"},  # too old
        {"price": 100.2, "usd_value": 10_000.0, "time": now * 1000, "side": "SELL"},  # below min_usd
    ]
    dist = nearest_liquidation_distance_pct(events, mark_price=100.0, now=now)
    assert dist is not None
    assert dist == pytest.approx(1.0, abs=0.15)
    assert nearest_liquidation_distance_pct([], mark_price=100.0) is None
    assert nearest_liquidation_distance_pct(events, mark_price=0.0) is None


def test_squeeze_liq_term_is_nonzero_when_cluster_is_close():
    meter = SqueezeRiskMeter("BTCUSDT")
    far = meter.compute(funding_rate_pct=0.0, oi_change_pct=0.0, ls_ratio=1.0, nearest_liq_distance_pct=5.0)
    near = meter.compute(funding_rate_pct=0.0, oi_change_pct=0.0, ls_ratio=1.0, nearest_liq_distance_pct=1.0)
    assert far["long_squeeze_risk_pct"] == 0.0
    assert near["long_squeeze_risk_pct"] == pytest.approx(20.0)  # (5-1)/5 * 25 points
    assert near["short_squeeze_risk_pct"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 3. VPIN
# ---------------------------------------------------------------------------


def test_whale_print_is_split_across_buckets_instead_of_saturating():
    v = VPINTracker(bucket_target_notional=1_000.0, window=10)
    # 25 units at $100 = $2,500 notional against $1,000 buckets.
    closed = v.add_trade(price=100.0, qty=25.0, side="buy", ts=1.0)
    assert closed is not None
    snap = v.snapshot()
    assert snap.buckets_closed == 2
    assert v._current.notional == pytest.approx(500.0)
    # Sells now fill the open bucket: it must not inherit the whale's bias.
    v.add_trade(price=100.0, qty=5.0, side="sell", ts=2.0)
    assert v.snapshot().buckets_closed == 3
    assert v.snapshot().last_bucket == pytest.approx(0.0)  # 500 buy / 500 sell


def test_balanced_flow_still_low_after_split_change():
    v = VPINTracker(bucket_target_notional=1_000.0, window=10)
    for i in range(200):
        v.add_trade(price=100.0, qty=2.0, side="buy" if i % 2 == 0 else "sell", ts=float(i))
    assert v.snapshot().running <= 0.25


def test_bucket_target_from_daily_volume_is_per_symbol_and_clamped():
    assert VPINTracker.target_from_daily_volume(50_000_000_000.0) == 20_000_000.0  # BTC-scale, capped
    assert VPINTracker.target_from_daily_volume(100_000_000.0) == pytest.approx(2_000_000.0)
    assert VPINTracker.target_from_daily_volume(1_000_000.0) == 200_000.0  # floor
    assert VPINTracker.target_from_daily_volume(0.0) == 200_000.0


# ---------------------------------------------------------------------------
# 4. Funding z-score warm-up
# ---------------------------------------------------------------------------


def test_funding_zscore_refuses_to_call_minutes_a_week():
    ft = FundingTracker("BTCUSDT")
    now = time.time()
    # 40 samples over 20 minutes - plenty of samples, no span.
    ft.seed_history([(now - i * 30, 0.0001 + 0.00005 * (i % 4)) for i in range(40)])
    out = ft.funding_zscore_rolling()
    assert out["classification"] == "insufficient_data"
    assert out["zscore"] == 0.0
    assert out["span_hours"] < 48


def test_funding_zscore_available_after_history_seed():
    ft = FundingTracker("BTCUSDT")
    now = time.time()
    # 45 samples four hours apart: 42 of them fall inside the 168h window with a
    # span of ~164h, so both gates pass.
    ft.seed_history([(now - i * 4 * 3600, 0.0001 * (1 + (i % 3))) for i in range(45)])
    out = ft.funding_zscore_rolling()
    assert out["classification"] != "insufficient_data"
    assert out["samples"] >= 30
    assert out["span_hours"] >= 48


def test_seed_history_deduplicates_and_sorts():
    ft = FundingTracker("BTCUSDT")
    ft.seed_history([(300.0, 0.1), (100.0, 0.2), (300.0, 0.3)])
    assert [h["timestamp"] for h in ft._history] == [100.0, 300.0]
    assert ft.seed_history([(100.0, 0.9)]) == 0


# ---------------------------------------------------------------------------
# 5. Correlation alignment
# ---------------------------------------------------------------------------


def test_correlation_inner_joins_on_timestamp():
    ts = [i * 900_000 for i in range(40)]
    closes = [100.0 * (1.01 ** (i % 7)) for i in range(40)]
    a = list(zip(ts, closes, strict=True))
    b = [(t, c) for t, c in a if t != 15 * 900_000]  # one bar missing on B
    out = correlation_matrix({"A": a, "B": b}, min_bars=20)
    assert out["aligned_by"] == "timestamp"
    assert out["n_bars"] == 38  # 39 common closes -> 38 returns
    assert out["matrix"][0][1] == pytest.approx(1.0)


def test_correlation_count_alignment_misaligns_the_same_data():
    ts = [i * 900_000 for i in range(40)]
    closes = [100.0 * (1.01 ** (i % 7)) for i in range(40)]
    a = closes
    b = [c for t, c in zip(ts, closes, strict=True) if t != 15 * 900_000]
    out = correlation_matrix({"A": a, "B": b}, min_bars=20)
    assert out["aligned_by"] == "count"
    assert out["matrix"][0][1] < 0.99, "count alignment silently shifts the series"


# ---------------------------------------------------------------------------
# 6. VaR Student-t quantile
# ---------------------------------------------------------------------------


def test_student_t_quantile_is_the_real_thing():
    assert _student_t_quantile(0.01, 5.0) == pytest.approx(-3.3649, abs=1e-3)
    assert _student_t_quantile(0.99, 5.0) == pytest.approx(3.3649, abs=1e-3)
    assert _student_t_quantile(0.05, 3.0) == pytest.approx(-2.3534, abs=1e-3)
