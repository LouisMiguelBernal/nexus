"""
Nexus - VPIN (Volume-Synchronized Probability of Informed Trading)

Reference
---------
Easley, D., López de Prado, M., O'Hara, M. (2012).
"Flow Toxicity and Liquidity in a High-Frequency World".
Review of Financial Studies, 25(5), 1457-1493.

Definition
----------
Bucket incoming trades by *equal dollar volume* (volume clock, not wall
clock). For each bucket of size `V`:

    V_buy  = Σ (p·q) classified as buyer-initiated
    V_sell = Σ (p·q) classified as seller-initiated
    V_buy + V_sell = V

    VPIN_bucket = |V_buy − V_sell| / V       ∈ [0, 1]

Running VPIN = simple moving average of `VPIN_bucket` over the last
`window` buckets (default 50, ≈ López de Prado's original parameterization).

Why volume clock
----------------
Trading intensity compresses in time during toxic flow events - time bars
smear the signal. Volume bars normalize activity so VPIN cleanly spikes
when order flow becomes one-sided per unit of liquidity consumed.

Consumers
---------
- `backend/computation/squeeze_risk.py` - weight into squeeze score.
- `backend/risk/circuit_breaker.py` - VPIN > 0.85 trip (event trigger, P2).
- `backend/computation/obi_tracker.py` - OBI sampled on VPIN bucket close.

Side classification
-------------------
When trade side is *known* (e.g. exchange-reported `isBuyerMaker`), use it.
Otherwise fall back to the **bulk volume classification** (BVC) from the
original paper - a Z-score of the price change per bucket:

    V_buy = V · Φ(ΔP / σ)      with Φ = standard normal CDF
    V_sell = V − V_buy

This module accepts either mode via `classify`.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Literal, Optional

logger = logging.getLogger("nexus.vpin")


# ------------------------------------------------------------------
# Standard normal helpers (stdlib-only, avoids scipy hard dep)
# ------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf. Exact enough for BVC."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class _Bucket:
    """Accumulator for a single volume bucket (closed at dollar_volume ≥ target)."""
    target_notional: float
    notional: float = 0.0
    buy_notional: float = 0.0
    sell_notional: float = 0.0
    trade_count: int = 0
    first_price: Optional[float] = None
    last_price: Optional[float] = None
    open_ts: Optional[float] = None
    close_ts: Optional[float] = None

    def add(self, price: float, qty: float, side: Optional[str], ts: Optional[float]) -> None:
        notional = price * qty
        self.notional += notional
        self.trade_count += 1
        if self.first_price is None:
            self.first_price = price
            self.open_ts = ts
        self.last_price = price
        self.close_ts = ts
        if side == "buy":
            self.buy_notional += notional
        elif side == "sell":
            self.sell_notional += notional
        # Unknown side: deferred; reclassified on close via BVC.

    def finalize(self, bvc_sigma: float) -> Dict[str, float]:
        """Close the bucket and compute VPIN contribution."""
        # If some/all trades were side-unknown, apply BVC to the residual.
        classified = self.buy_notional + self.sell_notional
        residual = max(0.0, self.notional - classified)
        if residual > 0 and self.first_price and self.last_price and bvc_sigma > 0:
            dp = (self.last_price - self.first_price) / self.first_price
            prob_buy = _norm_cdf(dp / bvc_sigma)
            self.buy_notional += residual * prob_buy
            self.sell_notional += residual * (1.0 - prob_buy)
        elif residual > 0:
            # No sigma yet - split 50/50 (conservative, VPIN → 0).
            self.buy_notional += residual * 0.5
            self.sell_notional += residual * 0.5

        imbalance = abs(self.buy_notional - self.sell_notional)
        total = self.buy_notional + self.sell_notional
        vpin = imbalance / total if total > 0 else 0.0
        return {
            "vpin": vpin,
            "buy_notional": self.buy_notional,
            "sell_notional": self.sell_notional,
            "notional": self.notional,
            "trade_count": self.trade_count,
            "open_ts": self.open_ts or 0.0,
            "close_ts": self.close_ts or 0.0,
            "open_price": self.first_price or 0.0,
            "close_price": self.last_price or 0.0,
        }


@dataclass
class VPINResult:
    running: float                   # SMA of last `window` bucket VPINs
    last_bucket: float               # VPIN of the most recent closed bucket
    buckets_closed: int              # total buckets closed in this tracker's lifetime
    window: int
    toxic: bool                      # running > toxic_threshold (default 0.85)
    bucket_target_notional: float
    history: List[Dict[str, float]] = field(default_factory=list)


class VPINTracker:
    """Streaming VPIN calculator on notional volume clock.

    Parameters
    ----------
    bucket_target_notional : float
        USD notional per bucket. Paper convention: daily_$vol / 50. Set from
        a rolling estimate of 24h notional / 50.
    window : int
        Number of recent buckets to average for `running` VPIN. Default 50.
    toxic_threshold : float
        Running VPIN above this is flagged toxic. Default 0.85 (the circuit
        breaker trip level cited in the plan).
    bvc_lookback : int
        Number of recent bucket returns used to estimate σ for Bulk Volume
        Classification when trade sides are absent.
    """

    def __init__(
        self,
        bucket_target_notional: float,
        window: int = 50,
        toxic_threshold: float = 0.85,
        bvc_lookback: int = 50,
    ):
        if bucket_target_notional <= 0:
            raise ValueError("bucket_target_notional must be positive")
        self.bucket_target_notional = float(bucket_target_notional)
        self.window = int(window)
        self.toxic_threshold = float(toxic_threshold)
        self.bvc_lookback = int(bvc_lookback)

        self._current = _Bucket(target_notional=self.bucket_target_notional)
        self._vpin_hist: Deque[float] = deque(maxlen=self.window)
        self._return_hist: Deque[float] = deque(maxlen=self.bvc_lookback)
        self._closed_buckets: Deque[Dict[str, float]] = deque(maxlen=256)
        self._total_closed = 0

    # ------------------------------------------------------------------

    def _bvc_sigma(self) -> float:
        if len(self._return_hist) < 5:
            return 0.0
        mean = sum(self._return_hist) / len(self._return_hist)
        var = sum((r - mean) ** 2 for r in self._return_hist) / len(self._return_hist)
        return math.sqrt(var) if var > 0 else 0.0

    def update_bucket_target(self, new_target: float) -> None:
        """Resize the bucket target (e.g. after a daily $-volume refresh)."""
        if new_target > 0:
            self.bucket_target_notional = float(new_target)
            # Do NOT rewrite the open bucket - it will close at the new target.
            self._current.target_notional = self.bucket_target_notional

    def add_trade(
        self,
        price: float,
        qty: float,
        side: Optional[Literal["buy", "sell"]] = None,
        ts: Optional[float] = None,
    ) -> Optional[Dict[str, float]]:
        """Ingest one trade. Returns the closed-bucket dict if this trade
        sealed a bucket, else None."""
        if price <= 0 or qty <= 0:
            return None
        self._current.add(price, qty, side, ts)

        closed: Optional[Dict[str, float]] = None
        # Close bucket when target notional reached.
        while self._current.notional >= self.bucket_target_notional:
            closed = self._close_current()
            # Any excess notional from the last trade is already captured in
            # this bucket (we don't split a single trade across buckets - it
            # distorts the BVC return calc). Next trades open a fresh bucket.
            break
        return closed

    def _close_current(self) -> Dict[str, float]:
        sigma = self._bvc_sigma()
        snap = self._current.finalize(bvc_sigma=sigma)
        self._vpin_hist.append(snap["vpin"])
        self._closed_buckets.append(snap)
        self._total_closed += 1
        # Update BVC return history with this bucket's return.
        if snap["open_price"] > 0 and snap["close_price"] > 0:
            r = (snap["close_price"] - snap["open_price"]) / snap["open_price"]
            self._return_hist.append(r)
        # Start a fresh bucket.
        self._current = _Bucket(target_notional=self.bucket_target_notional)
        return snap

    # ------------------------------------------------------------------

    def snapshot(self) -> VPINResult:
        running = sum(self._vpin_hist) / len(self._vpin_hist) if self._vpin_hist else 0.0
        last = self._vpin_hist[-1] if self._vpin_hist else 0.0
        return VPINResult(
            running=round(running, 6),
            last_bucket=round(last, 6),
            buckets_closed=self._total_closed,
            window=self.window,
            toxic=running >= self.toxic_threshold,
            bucket_target_notional=self.bucket_target_notional,
            history=list(self._closed_buckets),
        )

    def as_dict(self) -> Dict:
        s = self.snapshot()
        return {
            "vpin": s.running,
            "vpin_last_bucket": s.last_bucket,
            "buckets_closed": s.buckets_closed,
            "window": s.window,
            "toxic": s.toxic,
            "toxic_threshold": self.toxic_threshold,
            "bucket_target_notional": s.bucket_target_notional,
        }
