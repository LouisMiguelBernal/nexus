"""
Nexus - Fallback / Inference Contract

Every Matrix layer must produce a value with attached *source* and
*confidence*. When direct measurement is unavailable (paid endpoint, missing
WS, cold start) we substitute a proxy and de-rate confidence accordingly.

Frontend reads `source ∈ {"direct", "proxy", "none"}` and tints proxy values
8% lower opacity. Confidence ∈ [0,1] feeds the composite layer-stdev.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Dict, Optional


@dataclass
class Inferred:
    value: float
    source: str  # "direct" | "proxy" | "none"
    confidence: float  # [0, 1]
    note: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def direct(value: float, note: str = "") -> Inferred:
    return Inferred(value=float(value), source="direct", confidence=1.0, note=note)


def proxy(value: float, confidence: float = 0.5, note: str = "") -> Inferred:
    return Inferred(
        value=float(value),
        source="proxy",
        confidence=max(0.0, min(1.0, confidence)),
        note=note,
    )


def absent(note: str = "") -> Inferred:
    return Inferred(value=0.0, source="none", confidence=0.0, note=note)


# ---------------------------------------------------------------------------
# Specific inference recipes
# ---------------------------------------------------------------------------

def infer_top_trader_ratio(
    cvd_z: Optional[float],
    funding_z: Optional[float],
    taker_imbalance: Optional[float],
) -> Inferred:
    """Public top-trader long/short ratio is paid/restricted on most venues.

    Proxy: tanh-blend of (CVD z-score, funding z-score, taker imbalance). This
    correlates well empirically with revealed positioning during regime breaks
    but is *not* identical. Confidence capped at 0.55.
    """
    parts = [v for v in (cvd_z, funding_z, taker_imbalance) if v is not None]
    if not parts:
        return absent("no proxy inputs")
    blended = sum(parts) / len(parts)
    return proxy(math.tanh(blended), confidence=0.55, note="cvd+funding+taker proxy")


def infer_oi_delta(
    price_change_pct: float,
    volume_delta_z: Optional[float],
    liquidation_flux: Optional[float],
) -> Inferred:
    """Used when OI WS gap > 60s and snapshot poller hasn't refreshed yet.

    Sign: positive when price rises with positive volume-delta + low liq flux
    (real buying), negative when liq flux dominates (forced unwind).
    """
    if volume_delta_z is None and liquidation_flux is None:
        return absent("no proxy inputs")
    vd = volume_delta_z or 0.0
    lf = liquidation_flux or 0.0
    raw = math.tanh(0.6 * vd - 0.4 * lf + 0.2 * (1 if price_change_pct > 0 else -1))
    return proxy(raw, confidence=0.45, note="vol-delta + liq-flux proxy")


def infer_gex_proxy(
    options_pcr: Optional[float],
    dvol: Optional[float],
    spot_max_pain_dist_pct: Optional[float],
) -> Inferred:
    """Dealer-gamma proxy from Deribit aggregate metrics (no per-strike Greeks).

    Heuristic: PCR>1 implies put-heavy → dealers short gamma → suppresses moves;
    DVOL high amplifies. Distance from max pain weights direction.
    """
    inputs = [options_pcr, dvol, spot_max_pain_dist_pct]
    if all(v is None for v in inputs):
        return absent("no Deribit inputs")
    pcr = options_pcr if options_pcr is not None else 1.0
    dv = dvol if dvol is not None else 50.0
    md = spot_max_pain_dist_pct if spot_max_pain_dist_pct is not None else 0.0
    # Negative when PCR>1 and price above max pain (dealers will push price down).
    raw = math.tanh((1.0 - pcr) * 0.8 + (-md / 5.0) - (dv / 200.0) * 0.2)
    return proxy(raw, confidence=0.40, note="Deribit PCR/DVOL/maxpain proxy")
