"""
Nexus - Cross-Sectional Funding Carry Factor

Reference
---------
Avellaneda & Lee (2010) statarb analog applied to crypto perp funding:
sort the universe by funding magnitude; long the least-funded (or
negative-funded) names, short the most-funded. This harvests the
premium paid by crowded-leverage traders on both sides.

Consumes the per-symbol `term_structure()` output from
`backend/computation/funding.py` (P1-1).

Signal construction
-------------------
For each symbol i with annualized realized carry c_i:

    z_i = (c_i − mean(c)) / std(c)
    score_i = −tanh(z_i / k)         k = 1.0 (shrinkage)

    Positive c_i (longs paying shorts) ⇒ negative score ⇒ short-bias alpha.
    Negative c_i (shorts paying longs) ⇒ positive score ⇒ long-bias alpha.

Quintile ranking (portfolio form)
---------------------------------
For universes of N ≥ 5:
    long_leg  = bottom quintile by c_i (least funded / most negative)
    short_leg = top    quintile by c_i (most funded)
    weight    = 1 / |leg|  per name (equal-weight within leg)

Returned dict carries both the continuous score and the discrete leg
membership so callers can pick whichever fits their execution regime.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional


def _std(xs: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var) if var > 0 else 0.0


def compute_xs_funding(
    term_structures: Dict[str, Dict],
    *,
    shrinkage_k: float = 1.0,
    quintile_cutoff: float = 0.20,
) -> Dict:
    """Cross-sectional funding carry ranking.

    Parameters
    ----------
    term_structures
        Mapping `{symbol: funding.FundingTracker.term_structure() dict}`.
        Reads the `realized_annualized_carry` field per entry.
    shrinkage_k
        Tanh bandwidth. Higher = more conservative / less extreme scores.
    quintile_cutoff
        Fraction per leg when building the long/short portfolio. 0.20 → top
        and bottom quintile. Clamped to [0.05, 0.50].

    Returns
    -------
    {
      "universe":      list of symbols (sorted by carry),
      "scores":        {sym: {"carry_annualized": c, "zscore": z, "score": s}},
      "long_leg":      [symbols],          # underfunded / negative carry
      "short_leg":     [symbols],          # most funded
      "leg_weight":    float,              # 1 / quintile_size
      "universe_stats": {"mean_carry": ..., "std_carry": ..., "n": ...},
      "reason":        str (when not actionable),
    }
    """
    carries: List[tuple[str, float]] = []
    for sym, ts in term_structures.items():
        try:
            c = float(ts.get("realized_annualized_carry", 0.0))
        except (TypeError, ValueError):
            continue
        carries.append((sym, c))

    n = len(carries)
    if n == 0:
        return {
            "universe": [],
            "scores": {},
            "long_leg": [],
            "short_leg": [],
            "leg_weight": 0.0,
            "universe_stats": {"mean_carry": 0.0, "std_carry": 0.0, "n": 0},
            "reason": "empty universe",
        }

    values = [c for _, c in carries]
    mean_c = sum(values) / n
    std_c = _std(values)

    scores: Dict[str, Dict] = {}
    for sym, c in carries:
        z = (c - mean_c) / std_c if std_c > 1e-12 else 0.0
        # Contrarian: high carry → short. tanh saturates extreme z.
        score = -math.tanh(z / max(shrinkage_k, 1e-6))
        scores[sym] = {
            "carry_annualized": round(c, 6),
            "carry_annualized_pct": round(c * 100, 4),
            "zscore": round(z, 4),
            "score": round(score, 4),
        }

    # Sort ascending by carry → bottom = cheapest to be long; top = shorts.
    sorted_syms = sorted(scores.keys(), key=lambda s: scores[s]["carry_annualized"])
    cut = max(0.05, min(0.50, quintile_cutoff))
    leg_n = max(1, int(math.floor(n * cut)))

    long_leg = sorted_syms[:leg_n] if n >= 5 else []
    short_leg = sorted_syms[-leg_n:] if n >= 5 else []
    leg_weight = 1.0 / leg_n if leg_n > 0 else 0.0

    reason = "OK" if n >= 5 else f"universe too small for quintile legs (n={n})"

    return {
        "universe": sorted_syms,
        "scores": scores,
        "long_leg": long_leg,
        "short_leg": short_leg,
        "leg_weight": round(leg_weight, 6),
        "universe_stats": {
            "mean_carry": round(mean_c, 6),
            "std_carry": round(std_c, 6),
            "n": n,
        },
        "reason": reason,
    }
