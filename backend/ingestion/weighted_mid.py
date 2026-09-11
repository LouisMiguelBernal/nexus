"""
Nexus - Cross-Exchange Weighted Mid Price

P_combined = Σ (w_i × P_i)

w_i = static_w_i × volume_factor × spread_tightness × latency_health,
renormalized across non-degraded feeds. All inputs are read-only over
WSManager + per-exchange data stores.

Falls back to median of available mids if every venue is degraded
(prevents NaN propagation during multi-venue outage).
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Dict, Optional

from backend.ingestion.feed_validator import (
    evaluate_feeds,
    normalized_dynamic_weights,
)


def compute_weighted_mid(
    symbol: str,
    ws_manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Compute the weighted mid for `symbol`.

    Returns
    -------
    {
      symbol, timestamp,
      price: float | None,
      method: "weighted" | "median_fallback" | "unavailable",
      weights: {venue: w},
      components: {venue: {mid, weight, contribution}},
      degradations: {venue: float},
    }
    """
    sym = symbol.upper()
    health = evaluate_feeds(sym, ws_manager=ws_manager)
    weights = normalized_dynamic_weights(sym, ws_manager=ws_manager)

    components: Dict[str, Dict[str, Any]] = {}
    weighted_total = 0.0
    weight_sum = 0.0
    available_mids = []
    degradations: Dict[str, float] = {}

    for venue, h in health.items():
        mid = h.get("mid")
        deg = h.get("degradation", 0.0)
        degradations[venue] = deg
        w = weights.get(venue, 0.0)
        if mid is None:
            components[venue] = {"mid": None, "weight": 0.0, "contribution": 0.0}
            continue
        available_mids.append(mid)
        contribution = mid * w
        components[venue] = {
            "mid": mid,
            "weight": round(w, 6),
            "contribution": round(contribution, 6),
        }
        weighted_total += contribution
        weight_sum += w

    if weight_sum > 0:
        price = weighted_total
        method = "weighted"
    elif available_mids:
        price = statistics.median(available_mids)
        method = "median_fallback"
    else:
        price = None
        method = "unavailable"

    return {
        "symbol": sym,
        "timestamp": time.time(),
        "price": price,
        "method": method,
        "weights": {v: round(w, 6) for v, w in weights.items()},
        "components": components,
        "degradations": {v: round(d, 4) for v, d in degradations.items()},
    }
