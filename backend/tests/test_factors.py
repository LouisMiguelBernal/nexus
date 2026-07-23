"""
Verification: P1-3 (TSMOM), P1-4 (XS funding carry), P1-5 (OI-mom).
"""

import math

from backend.computation.factors.tsmom import compute_tsmom, tsmom_portfolio
from backend.computation.factors.xs_funding import compute_xs_funding


def test_tsmom_trending_up_produces_long_signal():
    closes = [100.0 + i * 0.5 for i in range(100)]  # monotonically up
    out = compute_tsmom(closes, formation_hours=12, skip_hours=1, vol_hours=72)
    assert out["direction"] == "long"
    assert out["score"] > 0.0
    assert out["raw"] > 0.0


def test_tsmom_trending_down_produces_short_signal():
    closes = [200.0 - i * 0.3 for i in range(100)]
    out = compute_tsmom(closes)
    assert out["direction"] == "short"
    assert out["score"] < 0.0


def test_tsmom_insufficient_data_returns_flat():
    out = compute_tsmom([100.0, 101.0])
    assert out["direction"] == "flat"
    assert out["score"] == 0.0


def test_tsmom_portfolio_maps_symbols_to_results():
    closes_by = {
        "BTC": [100.0 + i * 0.5 for i in range(100)],
        "ETH": [200.0 - i * 0.3 for i in range(100)],
    }
    port = tsmom_portfolio(closes_by)
    assert set(port.keys()) == {"BTC", "ETH"}
    assert port["BTC"]["direction"] == "long"
    assert port["ETH"]["direction"] == "short"


def test_xs_funding_ranks_and_selects_quintile_legs():
    # 10 symbols with funding carry increasing linearly.
    ts = {
        f"SYM{i}": {"realized_annualized_carry": -0.1 + i * 0.05}
        for i in range(10)
    }
    result = compute_xs_funding(ts)
    assert result["reason"] == "OK"
    assert len(result["universe"]) == 10
    # With quintile=0.2 and n=10, legs hold 2 names each.
    assert len(result["long_leg"]) == 2
    assert len(result["short_leg"]) == 2
    # Long leg = cheapest (lowest carry), short leg = most expensive.
    lowest = min(result["universe"], key=lambda s: ts[s]["realized_annualized_carry"])
    highest = max(result["universe"], key=lambda s: ts[s]["realized_annualized_carry"])
    assert lowest in result["long_leg"]
    assert highest in result["short_leg"]


def test_xs_funding_scores_are_contrarian_to_crowding():
    """High positive carry ⇒ short-bias (negative score). Negative carry ⇒ long-bias."""
    ts = {
        "HOT": {"realized_annualized_carry": 1.0},   # heavily long-crowded
        "COLD": {"realized_annualized_carry": -0.5},  # short-crowded
        "MID1": {"realized_annualized_carry": 0.0},
        "MID2": {"realized_annualized_carry": 0.1},
        "MID3": {"realized_annualized_carry": -0.1},
    }
    result = compute_xs_funding(ts)
    assert result["scores"]["HOT"]["score"] < 0  # short-bias
    assert result["scores"]["COLD"]["score"] > 0  # long-bias


def test_xs_funding_empty_universe():
    result = compute_xs_funding({})
    assert result["reason"] == "empty universe"
    assert result["long_leg"] == []
