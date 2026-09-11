"""
Nexus - Order Book Imbalance (OBI) time-series tracker.

Samples the live Binance depth-20 snapshot at a fixed interval and keeps a
rolling series so the UI can chart short-term buy vs sell pressure.

**Notional weighting (P1-6)**

OBI now integrates order-book depth in **USD notional**:

    bid_notional = Σ p_i · q_i   over top-N bid levels
    ask_notional = Σ p_i · q_i   over top-N ask levels
    obi          = (bid_notional − ask_notional) / (bid_notional + ask_notional)

This is the same institutional convention as the Kyle-lambda / PIN
literature - a 100 BTC wall at $70 k signals the same dollar pressure as
a 1 BTC wall at $7 M, which the prior qty-only formulation missed. The
sample tuple still carries `bid_vol`/`ask_vol` as the *notional* figures
(unit change is transparent to the frontend chart).

**VPIN-bucket alignment (P1-6)**

`sample_on_vpin_close(vpin_bucket)` stores an OBI snapshot stamped to a
VPIN bucket close so toxicity events can be cross-referenced with the
prevailing book posture. Consumed by `squeeze_risk` and the circuit
breaker's event path (P2).

Range: [-1, +1]. Positive = bid-heavy (buy pressure). Negative = ask-heavy.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class OBITracker:
    """Per-symbol rolling OBI sampler."""

    def __init__(self, symbol: str, depth_levels: int = 10, max_samples: int = 600):
        self.symbol = symbol
        self.depth_levels = depth_levels
        self.max_samples = max_samples
        # Each sample: (t_unix, obi_notional, bid_notional, ask_notional, mid)
        # bid_notional / ask_notional are Σ p·q (USD), NOT raw qty.
        self._samples: Deque[tuple] = deque(maxlen=max_samples)
        # Parallel quantity-only series so consumers can compare a notional
        # imbalance against the raw size imbalance - useful for distinguishing
        # large-price vs large-qty wall behaviours.
        # tuple: (t_unix, obi_qty, bid_qty, ask_qty)
        self._qty_samples: Deque[tuple] = deque(maxlen=max_samples)
        # VPIN-bucket-aligned OBI snapshots (P1-6).
        self._vpin_aligned: Deque[Dict[str, Any]] = deque(maxlen=256)

    def update(self, order_book: Optional[dict]) -> Optional[Dict]:
        """Call on every tick or on a timer. Returns the latest sample dict or None."""
        if not order_book:
            return None
        bids = order_book.get("bids") or []
        asks = order_book.get("asks") or []
        if not bids or not asks:
            return None

        top_b = bids[: self.depth_levels]
        top_a = asks[: self.depth_levels]
        # Notional integration: Σ p_i · q_i.
        bid_notional = sum(float(p) * float(q) for p, q in top_b)
        ask_notional = sum(float(p) * float(q) for p, q in top_a)
        denom = bid_notional + ask_notional
        if denom <= 0:
            return None
        obi = (bid_notional - ask_notional) / denom
        # Quantity-only imbalance (parallel series).
        bid_qty = sum(float(q) for _, q in top_b)
        ask_qty = sum(float(q) for _, q in top_a)
        qty_denom = bid_qty + ask_qty
        obi_qty = (bid_qty - ask_qty) / qty_denom if qty_denom > 0 else 0.0
        mid = (float(top_b[0][0]) + float(top_a[0][0])) / 2

        t = time.time()
        self._samples.append((t, obi, bid_notional, ask_notional, mid))
        self._qty_samples.append((t, obi_qty, bid_qty, ask_qty))
        return {
            "time": t,
            "obi": obi,                    # primary (notional) - back-compat key
            "obi_notional": obi,
            "obi_qty": obi_qty,
            "bid_vol": bid_notional,       # back-compat
            "ask_vol": ask_notional,       # back-compat
            "bid_notional": bid_notional,
            "ask_notional": ask_notional,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "mid": mid,
        }

    # ------------------------------------------------------------------
    # VPIN-bucket alignment (P1-6)
    # ------------------------------------------------------------------

    def sample_on_vpin_close(self, vpin_bucket: Dict[str, Any]) -> Optional[Dict]:
        """Stamp the latest OBI onto a VPIN bucket close event.

        `vpin_bucket` is the dict returned by `VPINTracker.add_trade()` when
        a bucket closes (or any dict with `close_ts`, `vpin`, `close_price`).
        Returns the stored snapshot, or None if OBI has no samples yet.
        """
        latest = self.latest()
        if latest is None:
            return None
        snap = {
            "bucket_close_ts": vpin_bucket.get("close_ts"),
            "bucket_vpin": vpin_bucket.get("vpin"),
            "bucket_close_price": vpin_bucket.get("close_price"),
            "bucket_notional": vpin_bucket.get("notional"),
            "obi": latest["obi"],
            "bid_notional": latest.get("bid_notional", latest["bid_vol"]),
            "ask_notional": latest.get("ask_notional", latest["ask_vol"]),
            "mid": latest["mid"],
        }
        self._vpin_aligned.append(snap)
        return snap

    def vpin_aligned_series(self, limit: int = 64) -> List[Dict[str, Any]]:
        return list(self._vpin_aligned)[-limit:]

    # ------------------------------------------------------------------
    def latest(self) -> Optional[Dict]:
        if not self._samples:
            return None
        t, obi, bv, av, mid = self._samples[-1]
        return {"time": t, "obi": obi, "bid_vol": bv, "ask_vol": av, "mid": mid}

    def series(self, limit: int = 240) -> List[Dict]:
        """Return the last ``limit`` samples, oldest first."""
        if not self._samples:
            return []
        data = list(self._samples)[-limit:]
        return [
            {"time": t, "obi": obi, "bid_vol": bv, "ask_vol": av, "mid": mid}
            for (t, obi, bv, av, mid) in data
        ]

    def summary(self, window: int = 120) -> Dict:
        """Aggregate stats over the last ``window`` samples.

        Returns dual notional/qty stats. The legacy ``latest``/``mean``/``std``
        fields stay anchored to the notional series for back-compat with the
        existing /api/obi consumers and matrix.py flow block.
        """
        if not self._samples:
            return {
                "count": 0,
                "latest": None,
                "mean": None,
                "std": None,
                "min": None,
                "max": None,
                "bias": "no_data",
                "latest_qty": None,
                "mean_qty": None,
                "std_qty": None,
                "bias_qty": "no_data",
            }
        window = min(window, len(self._samples))
        vals = [s[1] for s in list(self._samples)[-window:]]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = var ** 0.5
        latest = vals[-1]

        def _bias(x: float) -> str:
            if x >= 0.2: return "strong_bid"
            if x >= 0.05: return "bid"
            if x <= -0.2: return "strong_ask"
            if x <= -0.05: return "ask"
            return "balanced"

        # Quantity series (matched window).
        if self._qty_samples:
            qwindow = min(window, len(self._qty_samples))
            qvals = [s[1] for s in list(self._qty_samples)[-qwindow:]]
            qmean = sum(qvals) / len(qvals)
            qvar = sum((v - qmean) ** 2 for v in qvals) / len(qvals)
            qstd = qvar ** 0.5
            qlatest = qvals[-1]
        else:
            qmean = qstd = qlatest = 0.0

        return {
            "count": len(self._samples),
            "window": window,
            "latest": round(latest, 4),
            "mean": round(mean, 4),
            "std": round(std, 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "bias": _bias(latest),
            # Quantity-only parallel stats (P1-6 dual tracking).
            "latest_qty": round(qlatest, 4),
            "mean_qty": round(qmean, 4),
            "std_qty": round(qstd, 4),
            "bias_qty": _bias(qlatest),
        }

    def with_vpin_context(self, vpin_result: Optional[Any] = None, window: int = 120) -> Dict:
        """Summary merged with a VPINTracker snapshot for cross-event analysis.

        ``vpin_result`` is the result of ``VPINTracker.snapshot()``. When None
        or absent, the VPIN keys are emitted as None so the consumer schema is
        stable (frontend types don't toggle shape).
        """
        out = dict(self.summary(window=window))
        if vpin_result is not None:
            out.update({
                "vpin_running": getattr(vpin_result, "running", None),
                "vpin_last_bucket": getattr(vpin_result, "last_bucket", None),
                "vpin_toxic": getattr(vpin_result, "toxic", None),
                "vpin_window": getattr(vpin_result, "window", None),
                "vpin_bucket_target_notional": getattr(vpin_result, "bucket_target_notional", None),
                "vpin_buckets_closed": getattr(vpin_result, "buckets_closed", None),
            })
        else:
            out.update({
                "vpin_running": None,
                "vpin_last_bucket": None,
                "vpin_toxic": None,
                "vpin_window": None,
                "vpin_bucket_target_notional": None,
                "vpin_buckets_closed": None,
            })
        return out
