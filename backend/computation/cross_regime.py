"""
Nexus - cross-asset regime conditioning.

The crypto book does not trade in a vacuum: a dollar squeeze, a credit widening
or a VIX spike reprices perps before any of it shows up in order flow. This
module turns the cross-asset context board into two things the existing engines
can consume without changing their contracts:

  * ``risk_appetite()`` - a -100..+100 risk-on/risk-off score with its component
    breakdown.
  * ``adjust_regime()`` - takes the crypto ``RegimeClassifier`` output and
    conditions it on that macro state.

**The vocabulary never grows.** ``adjust_regime`` returns one of the same five
regime labels ``WEIGHTS_BY_REGIME`` keys on (``trending_bull``,
``trending_bear``, ``ranging``, ``volatile``, ``low_liq``). Introducing a sixth
would KeyError the alpha engine's weight lookup, so cross-asset input is only
ever allowed to:

  1. **tip a low-confidence classification** between existing labels, and
  2. **scale confidence** when macro and microstructure disagree.

Direction is still decided by the crypto tape. Macro conditions the prior; it
does not get a vote on the trade. That asymmetry is deliberate - cross-asset
data is daily-resolution and lags perp microstructure by hours.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("nexus.cross_regime")

VALID_REGIMES = ("trending_bull", "trending_bear", "ranging", "volatile", "low_liq")

# Each axis maps to -1 (risk-off) .. +1 (risk-on) before weighting.
RORO_WEIGHTS = {
    "equity_trend": 0.22,  # SPX slope - the base risk signal
    "vol_level": 0.20,  # VIX absolute level
    "vol_change": 0.12,  # VIX direction
    "dollar_trend": 0.18,  # DXY - the dominant crypto beta driver
    "credit": 0.15,  # HYG - stress shows here before equities
    "rates_change": 0.08,  # US10Y velocity, not level
    "cyclicals": 0.05,  # copper/gold ratio
}


def _slope_pct(closes: list[float], window: int = 20) -> float | None:
    """Least-squares slope over the window, as % of mean price per bar."""
    if not closes or len(closes) < max(5, window // 2):
        return None
    series = np.asarray(closes[-window:], dtype=float)
    if series.size < 3 or not np.isfinite(series).all():
        return None
    mean = float(series.mean())
    if mean == 0:
        return None
    slope = float(np.polyfit(np.arange(series.size), series, 1)[0])
    return slope / mean * 100.0


def _pct_change(closes: list[float], bars: int = 5) -> float | None:
    if not closes or len(closes) <= bars:
        return None
    past = closes[-1 - bars]
    if not past:
        return None
    return (closes[-1] - past) / past * 100.0


def _squash(value: float | None, scale: float) -> float | None:
    """Bounded, monotone map to -1..+1. `scale` is the value that reaches ~0.76."""
    if value is None:
        return None
    return float(np.tanh(value / scale))


def risk_appetite(quotes: dict[str, dict]) -> dict:
    """
    Risk-on / risk-off from the macro proxies.

    ``quotes`` is keyed by the logical names in ``config.REGIME_PROXIES``
    (spx, vix, dxy, us10y, gold, oil, hyg, copper), each a
    ``crossasset.yahoo.fetch_quote`` row. Missing proxies drop out and the
    weights renormalise - a partial board still produces a usable score.
    """

    def closes(key: str) -> list[float]:
        return (quotes.get(key) or {}).get("closes") or []

    axes: dict[str, float | None] = {}

    axes["equity_trend"] = _squash(_slope_pct(closes("spx")), 0.25)

    vix_last = (quotes.get("vix") or {}).get("price")
    if isinstance(vix_last, (int, float)):
        # VIX 12 -> risk-on, 20 -> neutral, 35+ -> hard risk-off.
        axes["vol_level"] = float(np.tanh((20.0 - float(vix_last)) / 8.0))
    else:
        axes["vol_level"] = None
    axes["vol_change"] = _squash(-(_pct_change(closes("vix"), 5) or 0.0) if closes("vix") else None, 15.0)

    # A rising dollar is risk-off for a crypto book: invert the sign.
    axes["dollar_trend"] = _squash(-(_slope_pct(closes("dxy")) or 0.0) if closes("dxy") else None, 0.12)
    axes["credit"] = _squash(_slope_pct(closes("hyg")), 0.10)

    # Rates: velocity, not level. A fast repricing in either direction is the
    # stress signal; a high but stable 10Y is already in the price.
    us10y_move = _pct_change(closes("us10y"), 5)
    axes["rates_change"] = float(-np.tanh(abs(us10y_move) / 6.0)) if us10y_move is not None else None

    copper, gold = closes("copper"), closes("gold")
    if len(copper) >= 21 and len(gold) >= 21:
        n = min(len(copper), len(gold), 60)
        ratio = [copper[-n + i] / gold[-n + i] for i in range(n) if gold[-n + i]]
        axes["cyclicals"] = _squash(_slope_pct(ratio), 0.35)
    else:
        axes["cyclicals"] = None

    live = {k: v for k, v in axes.items() if v is not None}
    if not live:
        return {
            "score": None,
            "state": "unknown",
            "axes": axes,
            "coverage": 0.0,
            "reason": "no macro proxies available",
        }

    total_weight = sum(RORO_WEIGHTS[k] for k in live)
    score = sum(RORO_WEIGHTS[k] * v for k, v in live.items()) / total_weight * 100.0

    if score >= 35:
        state = "risk_on"
    elif score <= -35:
        state = "risk_off"
    else:
        state = "neutral"

    return {
        "score": round(score, 1),
        "state": state,
        "axes": {k: (round(v, 3) if v is not None else None) for k, v in axes.items()},
        "weights": RORO_WEIGHTS,
        "coverage": round(total_weight, 3),
    }


def macro_stress(quotes: dict[str, dict], roro: dict) -> dict:
    """
    A 0-100 stress reading used to tip the regime toward ``volatile``.

    Distinct from risk appetite: RORO has a sign, stress does not. A violent
    melt-up and a violent sell-off are both high-stress states, and both argue
    for the volatile weight profile.
    """
    vix = (quotes.get("vix") or {}).get("price")
    vix_term = min(max((float(vix) - 15.0) / 25.0, 0.0), 1.0) if isinstance(vix, (int, float)) else None

    us10y = (quotes.get("us10y") or {}).get("closes") or []
    rate_move = abs(_pct_change(us10y, 5) or 0.0) if us10y else None
    rate_term = min(rate_move / 8.0, 1.0) if rate_move is not None else None

    dxy = (quotes.get("dxy") or {}).get("closes") or []
    dxy_move = abs(_pct_change(dxy, 5) or 0.0) if dxy else None
    dxy_term = min(dxy_move / 2.0, 1.0) if dxy_move is not None else None

    terms = [t for t in (vix_term, rate_term, dxy_term) if t is not None]
    if not terms:
        return {"score": None, "level": "unknown"}

    # Soft-max, not mean. Stress is driven by whichever axis is screaming: a
    # plain average lets a VIX at 38 read as "moderate" merely because rates and
    # the dollar happen to be quiet, which is exactly backwards. The max term
    # carries the reading; the mean keeps a single noisy axis from owning it.
    score = (0.6 * max(terms) + 0.4 * float(np.mean(terms))) * 100.0

    # A hard risk-off reading is itself corroborating evidence of stress.
    if roro.get("score") is not None and roro["score"] <= -50:
        score = min(100.0, score + 10.0)

    level = "high" if score >= 60 else "moderate" if score >= 35 else "low"
    return {"score": round(score, 1), "level": level}


def adjust_regime(crypto_regime: dict, quotes: dict[str, dict]) -> dict:
    """
    Condition the crypto regime on cross-asset state.

    Returns a dict that is a **superset** of the classifier's own output, so it
    is a drop-in replacement everywhere ``RegimeClassifier.classify()`` is used.
    ``regime`` is guaranteed to remain one of ``VALID_REGIMES`` (or the
    classifier's own ``insufficient_data`` passthrough).
    """
    base_regime = str(crypto_regime.get("regime") or "ranging")
    base_conf = float(crypto_regime.get("confidence") or 0.0)

    roro = risk_appetite(quotes)
    stress = macro_stress(quotes, roro)

    out = {
        **crypto_regime,
        "cross_asset": {
            "risk_appetite": roro,
            "stress": stress,
            "applied": False,
            "tipped_from": None,
            "confidence_delta": 0.0,
        },
    }

    # No usable macro board, or the classifier itself had nothing to say:
    # hand the crypto verdict straight through.
    if roro.get("score") is None or base_regime not in VALID_REGIMES:
        return out

    regime, confidence = base_regime, base_conf
    tipped_from = None

    # 1. Tip only a low-confidence, directionless call. A confident trend read
    #    from the tape outranks a daily-resolution macro board.
    if (
        base_regime == "ranging"
        and base_conf < 0.65
        and stress.get("score") is not None
        and stress["score"] >= 60
    ):
        regime, tipped_from = "volatile", "ranging"

    # 2. Divergence penalty: the tape says trend, the macro board disagrees.
    #    Do not flip the direction - shrink the conviction.
    alignment = 0.0
    roro_score = float(roro["score"])
    if base_regime == "trending_bull":
        alignment = roro_score / 100.0
    elif base_regime == "trending_bear":
        alignment = -roro_score / 100.0

    delta = 0.0
    if base_regime in ("trending_bull", "trending_bear"):
        if alignment < -0.35:
            delta = -0.15  # macro leaning hard the other way
        elif alignment > 0.35:
            delta = 0.05  # corroboration is worth less than contradiction costs
        confidence = max(0.05, min(0.95, confidence + delta))

    out["regime"] = regime
    out["confidence"] = round(confidence, 3)
    out["cross_asset"].update(
        {
            "applied": True,
            "tipped_from": tipped_from,
            "alignment": round(alignment, 3),
            "confidence_delta": round(delta, 3),
        }
    )
    return out
