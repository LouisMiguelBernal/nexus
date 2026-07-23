"""
Nexus - Matrix Engine Composite Scorer

7-layer institutional composite. Each layer ∈ [-1, +1]; final score is the
weighted sum × 100, clipped to [-100, +100]. Confidence = 1 - stdev(layers).
Agreement = % of layers with the same sign as the composite.

Layers
------
  trend  - EMA structure, ADX, Hurst persistence
  flow   - CVD multi-TF, OBI, VPIN inverse (low VPIN = clean flow)
  oi     - OI velocity z-score + funding persistence
  basis  - basis% z-score with cross-venue dispersion penalty
  vol    - ATR expansion vs BB-width compression
  liq    - Liquidation imbalance with vacuum penalty
  dealer - GEX proxy + funding skew

Verdict
-------
  SHORT_SQUEEZE   liq>0.6  & flow>0.4
  STRONG_BULL    composite>50 & vol>0  & flow>0
  STRONG_BEAR    composite<-50 & vol>0 & flow<0
  ACCUMULATION   composite>15 & oi>0  & flow>0
  DISTRIBUTION   composite<-15 & oi>0 & flow<0
  COMPRESSION    abs(composite)<10 & vol<-0.3
  RANGING        abs(composite)<10
  NEUTRAL        otherwise
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional


# ---------------------------------------------------------------------------
# Default layer weights (regime-neutral baseline)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS: Dict[str, float] = {
    "trend":  0.18,
    "flow":   0.20,
    "oi":     0.14,
    "basis":  0.10,
    "vol":    0.12,
    "liq":    0.14,
    "dealer": 0.12,
}
assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


# Per-regime overrides - must contain only keys from DEFAULT_WEIGHTS.
WEIGHTS_BY_REGIME: Dict[str, Dict[str, float]] = {
    "trending_up":   {"trend": 0.28, "flow": 0.22, "oi": 0.16, "basis": 0.06, "vol": 0.08, "liq": 0.10, "dealer": 0.10},
    "trending_down": {"trend": 0.28, "flow": 0.22, "oi": 0.16, "basis": 0.06, "vol": 0.08, "liq": 0.10, "dealer": 0.10},
    "ranging":       {"trend": 0.08, "flow": 0.18, "oi": 0.12, "basis": 0.16, "vol": 0.16, "liq": 0.16, "dealer": 0.14},
    "volatile":      {"trend": 0.10, "flow": 0.18, "oi": 0.14, "basis": 0.10, "vol": 0.18, "liq": 0.18, "dealer": 0.12},
    "low_liq":       {"trend": 0.10, "flow": 0.14, "oi": 0.10, "basis": 0.18, "vol": 0.14, "liq": 0.14, "dealer": 0.20},
}
for _r, _w in WEIGHTS_BY_REGIME.items():
    s = sum(_w.values())
    assert abs(s - 1.0) < 1e-6, f"regime {_r} weights sum to {s}"


@dataclass
class Layer:
    """One scored layer ∈ [-1, +1] with provenance."""

    value: float
    source: str = "direct"   # "direct" | "proxy" | "none"
    confidence: float = 1.0  # [0, 1]
    note: str = ""

    def clamp(self) -> "Layer":
        self.value = max(-1.0, min(1.0, float(self.value)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        return self

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Composite:
    score: float                           # [-100, +100]
    verdict: str
    confidence: float                      # [0, 100]
    agreement: float                       # [0, 100]
    venue_agreement: float                 # [0, 100]
    layers: Dict[str, Dict] = field(default_factory=dict)
    weights_used: Dict[str, float] = field(default_factory=dict)
    regime: str = "unknown"

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Layer constructors - each takes raw metric inputs and emits a Layer.
# All return Layer with .source ∈ {direct, proxy, none}. Missing inputs do
# NOT zero out the layer - they emit source="none", confidence=0 so the
# composite renormalises across whatever is present.
# ---------------------------------------------------------------------------

def _z(x: Optional[float], scale: float) -> Optional[float]:
    if x is None or not math.isfinite(x):
        return None
    return x / max(scale, 1e-9)


def _tanh_blend(parts: Iterable[Optional[float]], gain: float = 1.0) -> Optional[float]:
    vals = [v for v in parts if v is not None and math.isfinite(v)]
    if not vals:
        return None
    return math.tanh(gain * sum(vals) / len(vals))


def layer_trend(
    *,
    ema50_slope_pct: Optional[float],   # %/bar
    adx: Optional[float],
    hurst_signed: Optional[float],      # already in [-1,+1] from hurst_score
) -> Layer:
    inputs = [
        _z(ema50_slope_pct, 0.5),
        _z(adx, 30.0) if adx is not None else None,
        hurst_signed,
    ]
    v = _tanh_blend(inputs, gain=1.0)
    if v is None:
        return Layer(0.0, source="none", confidence=0.0, note="no trend inputs")
    confidence = sum(1 for p in inputs if p is not None) / len(inputs)
    return Layer(v, source="direct", confidence=confidence).clamp()


def layer_flow(
    *,
    cvd_1h_z: Optional[float],
    obi: Optional[float],         # already [-1,+1]
    vpin: Optional[float],        # [0,1]; we want low VPIN = clean = positive
    flow_ratio: Optional[float],  # [0,1]; >0.5 = buy-heavy
) -> Layer:
    parts: list[Optional[float]] = []
    parts.append(cvd_1h_z if cvd_1h_z is not None else None)
    parts.append(obi)
    if vpin is not None and math.isfinite(vpin):
        parts.append(0.5 - vpin)  # invert: low VPIN good
    if flow_ratio is not None and math.isfinite(flow_ratio):
        parts.append((flow_ratio - 0.5) * 2.0)  # rescale to ~[-1,+1]
    v = _tanh_blend(parts, gain=1.2)
    if v is None:
        return Layer(0.0, source="none", confidence=0.0, note="no flow inputs")
    conf = sum(1 for p in parts if p is not None) / 4.0
    return Layer(v, source="direct", confidence=conf).clamp()


def layer_oi(
    *,
    oi_change_pct: Optional[float],
    funding_persistence: Optional[float],  # [-1,+1] persistence of sign
) -> Layer:
    parts = [_z(oi_change_pct, 1.5), funding_persistence]
    v = _tanh_blend(parts, gain=1.0)
    if v is None:
        return Layer(0.0, source="none", confidence=0.0, note="no OI inputs")
    conf = sum(1 for p in parts if p is not None) / 2.0
    return Layer(v, source="direct", confidence=conf).clamp()


def layer_basis(
    *,
    basis_pct: Optional[float],
    basis_dispersion: Optional[float],  # stdev across venues (penalty)
) -> Layer:
    if basis_pct is None or not math.isfinite(basis_pct):
        return Layer(0.0, source="none", confidence=0.0, note="no basis")
    raw = math.tanh(basis_pct / 0.4)  # 0.4% → tanh ≈ 0.76
    if basis_dispersion is not None and math.isfinite(basis_dispersion):
        penalty = min(1.0, basis_dispersion / 0.3)
        raw *= (1.0 - 0.5 * penalty)
        conf = 1.0 - 0.5 * penalty
    else:
        conf = 0.7
    return Layer(raw, source="direct", confidence=conf).clamp()


def layer_vol(
    *,
    bb_width_pct: Optional[float],   # current BB width
    bb_width_avg: Optional[float],   # rolling avg for compression
    atr_pct: Optional[float],        # current ATR%
    atr_avg: Optional[float],        # rolling avg
) -> Layer:
    parts: list[Optional[float]] = []
    if bb_width_pct is not None and bb_width_avg and bb_width_avg > 0:
        # Compression (current < avg) = positive (loaded spring)
        parts.append((bb_width_avg - bb_width_pct) / bb_width_avg)
    if atr_pct is not None and atr_avg and atr_avg > 0:
        # ATR expansion = also signals regime change - but ambiguous direction,
        # so we treat expansion as +0.3 weight increase only.
        parts.append((atr_pct - atr_avg) / atr_avg * 0.5)
    v = _tanh_blend(parts, gain=1.5)
    if v is None:
        return Layer(0.0, source="none", confidence=0.0, note="no vol inputs")
    conf = sum(1 for p in parts if p is not None) / 2.0
    return Layer(v, source="direct", confidence=conf).clamp()


def layer_liq(
    *,
    long_liq_usd: Optional[float],
    short_liq_usd: Optional[float],
    liq_vacuum: Optional[float],  # pretrade liquidity vacuum score
) -> Layer:
    if long_liq_usd is None and short_liq_usd is None:
        return Layer(0.0, source="none", confidence=0.0, note="no liq inputs")
    L = long_liq_usd or 0.0
    S = short_liq_usd or 0.0
    total = L + S
    if total <= 0:
        return Layer(0.0, source="direct", confidence=0.5, note="quiet liquidations")
    # Short squeeze when shorts liquidating > longs (positive pressure on price).
    imbalance = (S - L) / total
    raw = math.tanh(imbalance * 1.5)
    if liq_vacuum is not None and math.isfinite(liq_vacuum):
        raw *= (1.0 - 0.3 * max(0.0, min(1.0, liq_vacuum)))
    return Layer(raw, source="direct", confidence=0.85).clamp()


def layer_dealer(
    *,
    gex_proxy: Optional[float],     # [-1,+1] from fallbacks.infer_gex_proxy
    funding_skew: Optional[float],  # term-structure skew
) -> Layer:
    parts = [gex_proxy, funding_skew]
    v = _tanh_blend(parts, gain=1.0)
    if v is None:
        return Layer(0.0, source="none", confidence=0.0, note="no dealer inputs")
    # GEX proxy gets at most 0.4 confidence (it's a proxy). Funding skew direct.
    conf = 0.5 if gex_proxy is not None else 0.4
    src = "proxy" if gex_proxy is not None and funding_skew is None else "direct"
    return Layer(v, source=src, confidence=conf).clamp()


# ---------------------------------------------------------------------------
# Composite assembler
# ---------------------------------------------------------------------------

def _verdict(score: float, layers: Dict[str, Layer]) -> str:
    L = lambda k: layers[k].value if k in layers else 0.0  # noqa: E731
    if L("liq") > 0.6 and L("flow") > 0.4:
        return "SHORT SQUEEZE RISK"
    if L("liq") < -0.6 and L("flow") < -0.4:
        return "LONG SQUEEZE RISK"
    if score > 50 and L("vol") > 0 and L("flow") > 0:
        return "STRONG BULLISH EXPANSION"
    if score < -50 and L("vol") > 0 and L("flow") < 0:
        return "STRONG BEARISH EXPANSION"
    if score > 15 and L("oi") > 0 and L("flow") > 0:
        return "ACCUMULATION"
    if score < -15 and L("oi") > 0 and L("flow") < 0:
        return "DISTRIBUTION"
    if abs(score) < 10 and L("vol") < -0.3:
        return "VOL COMPRESSION"
    if abs(score) < 10:
        return "RANGING / LOW EDGE"
    return "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"


def assemble(
    layers: Dict[str, Layer],
    *,
    regime: str = "unknown",
    venue_agreement_pct: float = 100.0,
) -> Composite:
    """Combine layers into the final composite with renormalised weights."""

    weights = WEIGHTS_BY_REGIME.get(regime, DEFAULT_WEIGHTS).copy()

    # Drop layers that are absent (source == 'none' AND confidence == 0).
    present = {k: v for k, v in layers.items() if v.source != "none" or v.confidence > 0}
    if not present:
        return Composite(
            score=0.0, verdict="NO DATA", confidence=0.0,
            agreement=0.0, venue_agreement=venue_agreement_pct,
            layers={k: v.to_dict() for k, v in layers.items()},
            weights_used={}, regime=regime,
        )

    # Renormalise the subset.
    w_total = sum(weights.get(k, 0.0) for k in present.keys())
    if w_total <= 0:
        # Equal-weight fallback if regime-mapping skipped these keys.
        w_norm = {k: 1.0 / len(present) for k in present}
    else:
        w_norm = {k: weights.get(k, 0.0) / w_total for k in present.keys()}

    score = 100.0 * sum(present[k].value * w_norm[k] for k in present)
    score = max(-100.0, min(100.0, score))

    # Confidence = 1 - stdev of present layer values, weighted by per-layer conf.
    vals = [present[k].value * present[k].confidence for k in present]
    if len(vals) >= 2:
        try:
            sd = statistics.pstdev(vals)
        except statistics.StatisticsError:
            sd = 0.0
    else:
        sd = 0.0
    conf = max(0.0, min(1.0, 1.0 - sd))
    confidence_pct = 100.0 * conf * (sum(present[k].confidence for k in present) / len(present))

    # Agreement = fraction of layers with same sign as composite.
    sign = 1 if score > 0 else -1 if score < 0 else 0
    if sign == 0:
        agreement_pct = 100.0  # all neutral counts as agreement
    else:
        same = sum(1 for k in present if (present[k].value > 0) == (sign > 0) and present[k].value != 0)
        agreement_pct = 100.0 * same / len(present)

    return Composite(
        score=round(score, 2),
        verdict=_verdict(score, present),
        confidence=round(confidence_pct, 1),
        agreement=round(agreement_pct, 1),
        venue_agreement=round(venue_agreement_pct, 1),
        layers={k: v.to_dict() for k, v in layers.items()},
        weights_used={k: round(v, 4) for k, v in w_norm.items()},
        regime=regime,
    )
