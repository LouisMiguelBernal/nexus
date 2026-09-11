"""
Verification: cross-asset regime conditioning.

The contract this file defends:

  1. The conditioner NEVER emits a label ``WEIGHTS_BY_REGIME`` does not key on.
     A sixth regime name would KeyError the alpha engine's weight lookup.
  2. Macro conditions the prior; it does not decide direction. A trending call
     from the tape is never flipped by the macro board - only its confidence
     moves.
  3. A missing or partial macro board degrades to the unconditioned crypto
     regime rather than raising or inventing a reading.
"""

import pytest

from backend.computation import regime as regime_module
from backend.computation.alpha_engine import WEIGHTS_BY_REGIME, set_regime_conditioner
from backend.computation.regime import RegimeClassifier
from backend.computation.cross_regime import (
    VALID_REGIMES,
    adjust_regime,
    macro_stress,
    risk_appetite,
)


def _series(start: float, drift: float, n: int = 60) -> list:
    return [start * (1 + drift) ** i for i in range(n)]


def _quote(symbol: str, price: float, closes: list) -> dict:
    return {"symbol": symbol, "price": price, "closes": closes, "change_pct": 0.0}


def _risk_on_board() -> dict:
    return {
        "spx": _quote("^GSPC", 5000.0, _series(4600.0, 0.0015)),
        "vix": _quote("^VIX", 12.5, _series(18.0, -0.004)),
        "dxy": _quote("DX-Y.NYB", 99.0, _series(104.0, -0.0007)),
        "hyg": _quote("HYG", 80.0, _series(77.0, 0.0006)),
        "us10y": _quote("^TNX", 4.1, _series(4.1, 0.0001)),
        "gold": _quote("GC=F", 2400.0, _series(2400.0, 0.0002)),
        "copper": _quote("HG=F", 4.6, _series(4.2, 0.0012)),
    }


def _risk_off_board() -> dict:
    return {
        "spx": _quote("^GSPC", 4300.0, _series(4900.0, -0.0022)),
        "vix": _quote("^VIX", 38.0, _series(15.0, 0.012)),
        "dxy": _quote("DX-Y.NYB", 108.0, _series(101.0, 0.0012)),
        "hyg": _quote("HYG", 72.0, _series(79.0, -0.0013)),
        "us10y": _quote("^TNX", 4.9, _series(4.2, 0.0026)),
        "gold": _quote("GC=F", 2600.0, _series(2400.0, 0.0012)),
        "copper": _quote("HG=F", 3.8, _series(4.4, -0.0018)),
    }


# ---------------------------------------------------------------------------
# Risk appetite
# ---------------------------------------------------------------------------

def test_risk_on_board_scores_positive():
    result = risk_appetite(_risk_on_board())
    assert result["score"] is not None
    assert result["score"] > 25, result
    assert result["state"] == "risk_on"


def test_risk_off_board_scores_negative():
    result = risk_appetite(_risk_off_board())
    assert result["score"] < -25, result
    assert result["state"] == "risk_off"


def test_empty_board_reports_unknown_not_zero():
    """A dead upstream must not read as a neutral market."""
    result = risk_appetite({})
    assert result["score"] is None
    assert result["state"] == "unknown"
    assert result["coverage"] == 0.0


def test_partial_board_renormalises_weights():
    partial = {"spx": _quote("^GSPC", 5000.0, _series(4600.0, 0.0015))}
    result = risk_appetite(partial)
    assert result["score"] is not None
    # Only the equity axis reported, so coverage is that axis's weight alone.
    assert 0.0 < result["coverage"] < 1.0
    assert result["axes"]["credit"] is None


def test_score_is_bounded():
    """No single axis may push the composite outside -100..100."""
    extreme = _risk_off_board()
    extreme["vix"] = _quote("^VIX", 900.0, _series(10.0, 0.05))
    result = risk_appetite(extreme)
    assert -100.0 <= result["score"] <= 100.0


def test_stress_is_unsigned():
    """A violent melt-up and a violent sell-off are both high-stress."""
    off = macro_stress(_risk_off_board(), risk_appetite(_risk_off_board()))
    on = macro_stress(_risk_on_board(), risk_appetite(_risk_on_board()))
    assert off["score"] > on["score"]
    assert off["level"] in ("moderate", "high")


# ---------------------------------------------------------------------------
# Regime conditioning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label", list(VALID_REGIMES))
def test_conditioner_never_leaves_the_known_vocabulary(label):
    for board in (_risk_on_board(), _risk_off_board(), {}):
        out = adjust_regime({"regime": label, "confidence": 0.5}, board)
        assert out["regime"] in WEIGHTS_BY_REGIME, out["regime"]


def test_direction_is_never_flipped_by_macro():
    """The tape decides direction. Macro only moves conviction."""
    bull = {"regime": "trending_bull", "confidence": 0.8}
    out = adjust_regime(bull, _risk_off_board())
    assert out["regime"] == "trending_bull"
    assert out["confidence"] < 0.8  # divergence penalty applied
    assert out["cross_asset"]["confidence_delta"] < 0


def test_corroboration_raises_confidence_less_than_divergence_lowers_it():
    bull = {"regime": "trending_bull", "confidence": 0.6}
    agreed = adjust_regime(bull, _risk_on_board())
    diverged = adjust_regime(bull, _risk_off_board())
    up = agreed["confidence"] - 0.6
    down = 0.6 - diverged["confidence"]
    assert up > 0 and down > 0
    assert down > up, "contradiction must cost more than corroboration pays"


def test_low_confidence_ranging_tips_to_volatile_under_stress():
    out = adjust_regime({"regime": "ranging", "confidence": 0.5}, _risk_off_board())
    assert out["regime"] == "volatile"
    assert out["cross_asset"]["tipped_from"] == "ranging"


def test_confident_ranging_is_not_tipped():
    out = adjust_regime({"regime": "ranging", "confidence": 0.9}, _risk_off_board())
    assert out["regime"] == "ranging"
    assert out["cross_asset"]["tipped_from"] is None


def test_no_macro_board_passes_crypto_regime_through_untouched():
    original = {"regime": "trending_bear", "confidence": 0.72, "atr_pct": 3.1}
    out = adjust_regime(original, {})
    assert out["regime"] == "trending_bear"
    assert out["confidence"] == 0.72
    assert out["cross_asset"]["applied"] is False


def test_insufficient_data_regime_is_passed_through():
    out = adjust_regime({"regime": "insufficient_data", "confidence": 0.0}, _risk_off_board())
    assert out["regime"] == "insufficient_data"
    assert out["cross_asset"]["applied"] is False


# ---------------------------------------------------------------------------
# The conditioning hook
#
# It lives inside RegimeClassifier.classify() so that all four call sites (the
# alpha engine, the matrix router, /api/alpha and /api/brief) read the same
# conditioned label. These tests pin that down - wrapping call sites by hand is
# how the reported regime and the regime the weights came from drift apart.
# ---------------------------------------------------------------------------

def _trending_klines(n: int = 60):
    closes = [100.0 * (1.01 ** i) for i in range(n)]
    return (
        closes,
        [1000.0 + 40 * i for i in range(n)],
        [c * 1.004 for c in closes],
        [c * 0.996 for c in closes],
    )


@pytest.fixture
def _clean_hook():
    regime_module.set_conditioner(None)
    yield
    regime_module.set_conditioner(None)


def test_hook_is_off_by_default(_clean_hook):
    """Backtests must not silently inherit today's live macro board."""
    assert regime_module.get_conditioner() is None
    out = RegimeClassifier().classify(*_trending_klines())
    assert "cross_asset" not in out


def test_hook_applies_to_every_classify_call(_clean_hook):
    calls = []

    def spy(regime):
        calls.append(regime)
        return {**regime, "spied": True}

    set_regime_conditioner(spy)  # re-exported from alpha_engine
    out = RegimeClassifier().classify(*_trending_klines())
    assert out["spied"] is True
    assert len(calls) == 1


def test_insufficient_data_path_is_conditioned_too(_clean_hook):
    """Uniform shape: consumers must not special-case the short-series branch."""
    set_regime_conditioner(lambda r: {**r, "spied": True})
    out = RegimeClassifier().classify([1.0] * 5, [1.0] * 5, [1.0] * 5, [1.0] * 5)
    assert out["regime"] == "insufficient_data"
    assert out["spied"] is True


def test_broken_conditioner_degrades_instead_of_raising(_clean_hook):
    def boom(_regime):
        raise RuntimeError("upstream exploded")

    set_regime_conditioner(boom)
    out = RegimeClassifier().classify(*_trending_klines())
    assert out["regime"] in WEIGHTS_BY_REGIME


def test_conditioner_returning_garbage_is_ignored(_clean_hook):
    set_regime_conditioner(lambda _r: "not a dict")
    out = RegimeClassifier().classify(*_trending_klines())
    assert out["regime"] in WEIGHTS_BY_REGIME


def test_live_conditioner_end_to_end_keeps_a_valid_label(_clean_hook):
    """The real conditioner, wired the way main.py wires it."""
    board = _risk_off_board()
    set_regime_conditioner(lambda r: adjust_regime(r, board))
    out = RegimeClassifier().classify(*_trending_klines())
    assert out["regime"] in WEIGHTS_BY_REGIME
    assert "cross_asset" in out
    assert out["cross_asset"]["risk_appetite"]["state"] == "risk_off"
