"""
Nexus - composite geopolitical risk score.

Turns the raw global-event snapshot into one 0-100 number the macro gate can
act on, plus the component breakdown that justifies it. The gate is the only
consumer that matters; everything else is display.

Design rules, in order of importance:

1. **Unavailable is not zero.** A dead USGS feed must not read as "no seismic
   risk". Components carry an ``available`` flag and the weights are
   renormalised over the ones that answered. If nothing answers, the score is
   ``None`` and the gate falls back to calendar-only behaviour.

2. **Bounded and saturating.** Every component maps to 0-100 through an
   explicit, monotone transform. No component can dominate through an outlier -
   a single M8.5 quake saturates the seismic term rather than pinning the
   composite at 100.

3. **Asymmetric smoothing.** Risk is allowed to spike immediately but decays
   slowly (EWMA on the way down only). A gate that flickers open the minute a
   headline ages out is worse than useless under leverage.

The weights are judgement, not fit - there is no labelled outcome series to fit
them to, and pretending otherwise would be false precision. They encode: market-
moving conflict/policy news matters most to a crypto book, physical disasters
and cyber exploitation tempo matter less, space weather matters only at the
extremes. Validating them against realised vol is the obvious next step.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("nexus.geo.instability")

WEIGHTS = {
    "conflict": 0.36,      # wire keyword pressure - the fastest macro transmitter
    "disasters": 0.18,     # GDACS red/orange alerts
    "instability": 0.18,   # worldmonitor CII when present, else redistributed
    "seismic": 0.10,       # large quakes: supply-chain / energy relevance
    "cyber": 0.10,         # actively-exploited CVEs (CISA KEV additions)
    "space_weather": 0.08, # only bites at G3+
}

# Terms that historically precede a risk-off session. Weighted by how directly
# each maps to a market repricing rather than by human severity.
#
# Every entry must be specific enough to survive substring matching against a
# headline corpus: bare "strikes" catches "strikes a deal" and bare "default"
# catches "default settings", and both would quietly inflate the score.
CONFLICT_LEXICON = {
    "nuclear": 5.0, "strait of hormuz": 5.0, "invasion": 4.0, "invade": 4.0,
    "missile": 3.0, "airstrike": 3.0, "air strike": 3.0, "air strikes": 2.0,
    "sanctions": 3.0, "embargo": 3.0, "blockade": 3.0, "export ban": 3.0,
    "escalation": 2.5, "escalate": 2.5, "retaliation": 2.5, "retaliate": 2.5,
    "ceasefire": -1.5, "peace deal": -2.0, "de-escalation": -2.0,
    "oil supply": 2.0, "pipeline": 1.5, "opec": 1.5, "tariff": 2.0,
    "coup": 4.0, "martial law": 3.5, "state of emergency": 3.0,
    "cyberattack": 2.0, "grid failure": 2.0, "sovereign default": 2.5,
}

_STATE: Dict[str, float] = {"score": 0.0, "ts": 0.0}
# Decay half-life on the way down. Risk that took a headline to create should
# take a few polls to clear.
_DECAY_LAMBDA = 0.75


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _seismic_component(block: Dict) -> Optional[float]:
    if not block.get("available"):
        return None
    events: List[Dict] = block.get("events") or []
    if not events:
        return 0.0

    peak = max(float(e.get("magnitude") or 0.0) for e in events)
    # M4.5 (the feed floor) -> 0, M8.0 -> 100, saturating above.
    score = _clamp((peak - 4.5) / 3.5 * 100.0)
    if any(e.get("tsunami") for e in events):
        score = _clamp(score + 20.0)
    return score


def _disaster_component(block: Dict) -> Optional[float]:
    if not block.get("available"):
        return None
    events: List[Dict] = block.get("events") or []
    reds = sum(1 for e in events if e.get("level") == "red")
    oranges = sum(1 for e in events if e.get("level") == "orange")
    # Three simultaneous red alerts is a genuinely bad day; call that 100.
    return _clamp((reds * 33.0) + (oranges * 8.0))


def _cyber_component(block: Dict) -> Optional[float]:
    """
    Exploitation tempo from CISA KEV additions, measured against its own base
    rate rather than an absolute constant.

    Two decisions worth keeping:

    * Count *additions*, not catalogue size. The catalogue only ever grows, so
      its total encodes nothing but elapsed time.
    * Normalise by the trailing 30-day rate. CISA's publication cadence drifts,
      and a fixed "15 additions is bad" threshold made an ordinary week score 80
      out of 100. Relative to base rate, a normal week is 0 - which is what the
      other components mean by quiet - and three times normal is 100.

    Ransomware-linked entries count double; those are the ones that take
    counterparties offline.
    """
    if not block.get("available"):
        return None

    recent = int(block.get("added_7d") or 0)
    ransomware = int(block.get("ransomware_7d") or 0)
    weighted = recent + ransomware

    monthly = int(block.get("added_30d") or 0)
    expected = max(monthly * 7.0 / 30.0, 1.0)  # the catalogue's own weekly rate

    ratio = weighted / expected
    return _clamp((ratio - 1.0) / 2.0 * 100.0)


def _space_weather_component(block: Dict) -> Optional[float]:
    if not block.get("available"):
        return None
    peak = max(
        int(block.get("geomagnetic") or 0),
        int(block.get("radiation") or 0),
        int(block.get("radio_blackout") or 0),
    )
    # G1-G2 are routine and score near nothing; G5 is 100.
    return _clamp(((peak / 5.0) ** 2) * 100.0)


def _conflict_component(block: Dict) -> Optional[float]:
    if not block.get("available"):
        return None
    items: List[Dict] = block.get("items") or []
    if not items:
        return 0.0

    pressure = 0.0
    hits: Dict[str, int] = {}
    for item in items:
        blob = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        for term, weight in CONFLICT_LEXICON.items():
            if term in blob:
                pressure += weight
                hits[term] = hits.get(term, 0) + 1

    block["keyword_hits"] = dict(sorted(hits.items(), key=lambda kv: -kv[1])[:10])
    # ~25 weighted points across a 50-headline window is a saturated wire.
    return _clamp(pressure / 25.0 * 100.0)


def _instability_component(enrichment: Dict) -> Optional[float]:
    if not enrichment.get("available"):
        return None
    # Sandbox fixtures are schema-valid samples, not observations. Scoring them
    # would put invented numbers into the macro gate.
    if enrichment.get("sample"):
        return None
    peak = enrichment.get("peak_score")
    mean5 = enrichment.get("mean_top5")
    if not isinstance(peak, (int, float)):
        return None
    # Their index is already 0-100. Blend peak with the top-5 mean so one
    # perpetually unstable state does not pin the term.
    blended = 0.5 * float(peak) + 0.5 * float(mean5 or peak)
    return _clamp(blended)


def _band(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "elevated"
    if score >= 40:
        return "watch"
    return "normal"


def compute(snapshot: Dict, enrichment: Optional[Dict] = None, smooth: bool = True) -> Dict:
    """
    Collapse a ``geo.sources.fetch_all()`` snapshot (plus optional worldmonitor
    enrichment) into a single score.

    Returns ``score=None`` when no source answered - the caller must treat that
    as "unknown", not "safe".
    """
    enrichment = enrichment or {"available": False}

    components = {
        "conflict": _conflict_component(snapshot.get("wires") or {}),
        "disasters": _disaster_component(snapshot.get("disasters") or {}),
        "instability": _instability_component(enrichment),
        "seismic": _seismic_component(snapshot.get("seismic") or {}),
        "cyber": _cyber_component(snapshot.get("cyber") or {}),
        "space_weather": _space_weather_component(snapshot.get("space_weather") or {}),
    }

    live = {k: v for k, v in components.items() if v is not None}
    if not live:
        return {
            "score": None,
            "band": "unknown",
            "components": components,
            "available_weight": 0.0,
            "reason": "no geo source answered",
        }

    # Renormalise over the components that actually reported.
    total_weight = sum(WEIGHTS[k] for k in live)
    raw = sum(WEIGHTS[k] * v for k, v in live.items()) / total_weight

    score = raw
    if smooth:
        now = time.time()
        prev = float(_STATE.get("score") or 0.0)
        # Spike immediately, decay slowly: risk-off is cheap to enter and
        # expensive to exit too early.
        score = raw if raw >= prev else (_DECAY_LAMBDA * prev + (1 - _DECAY_LAMBDA) * raw)
        _STATE.update({"score": score, "ts": now})

    return {
        "score": round(score, 1),
        "raw_score": round(raw, 1),
        "band": _band(score),
        "components": {k: (round(v, 1) if v is not None else None) for k, v in components.items()},
        "weights": WEIGHTS,
        # How much of the model actually reported. Below ~0.5 the score is thin
        # and the UI should say so rather than imply full coverage.
        "available_weight": round(total_weight, 3),
        "enriched": bool(enrichment.get("available")),
        "top_countries": enrichment.get("countries") or [],
    }


def reset_state() -> None:
    """Clear the smoothing memory. Tests rely on this; production does not."""
    _STATE.update({"score": 0.0, "ts": 0.0})
