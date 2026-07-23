"""
Nexus - Funding Rate Aggregation + Term Structure (P1-1)

Weighted average funding rate across Binance, OKX plus:

- Rolling 7-day history store (sampled per fetch_all() call).
- `term_structure()` returning `{spot, predicted_1h, predicted_8h,
  realized_annualized_carry_pct}` - primary input for the
  cross-sectional funding carry factor (P1-4) and a new
  `funding_carry_signal` in the alpha composite.
- `carry_signal()` - bounded [-1, +1] score suitable for feeding
  alpha_engine alongside the existing 8 factors (integration is a
  follow-up; the signal is exposed now so xs_funding/backtests can
  consume it without touching alpha_engine's weight rebalancing).

Annualization convention: perp funding settles every 8h → 3 payments/day
→ 1095 payments/year. `realized_annualized_carry = mean_rate * 1095`.
"""

import logging
import time
from typing import Dict, List, Optional

import httpx

from backend.config import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_ENDPOINTS,
    OKX_BASE,
    EXCHANGE_WEIGHTS,
    FUNDING_THRESHOLDS,
)
from backend.ingestion.rate_guard import (
    BINANCE_FUTURES_HOST,
    record_response,
    record_success,
    should_skip,
)

# Annualization factor for 8-hour funding settlement.
_FUNDING_SETTLES_PER_YEAR = 3 * 365  # 1095
_SEVEN_DAYS_S = 7 * 24 * 3600

logger = logging.getLogger("nexus.funding")


class FundingTracker:
    """Track and aggregate funding rates across exchanges."""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self._rates: Dict[str, float] = {}
        # Predicted *next* funding rate per exchange (populated by fetch_* if
        # the venue exposes it). Falls back to spot when unavailable.
        self._predicted: Dict[str, float] = {}
        self._history: list = []

    async def fetch_binance(self) -> Optional[float]:
        if should_skip(BINANCE_FUTURES_HOST):
            return None
        try:
            url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['mark_price']}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={"symbol": self.symbol})
                if record_response(BINANCE_FUTURES_HOST, resp.status_code, resp.text):
                    return None
                record_success(BINANCE_FUTURES_HOST)
                data = resp.json()
                rate = float(data.get("lastFundingRate", 0))
                self._rates["binance"] = rate
                # Binance premiumIndex exposes the current *running* premium
                # but not an explicit next-funding rate; use the realized rate
                # as a best-available predictor.
                self._predicted["binance"] = rate
                return rate
        except Exception as e:
            logger.error(f"Binance funding error: {e}")
            return None

    async def fetch_okx(self) -> Optional[float]:
        try:
            inst_id = self.symbol.replace("USDT", "-USDT-SWAP")
            url = f"{OKX_BASE}/api/v5/public/funding-rate"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params={"instId": inst_id})
                data = resp.json()
                items = data.get("data", [])
                if items:
                    rate = float(items[0].get("fundingRate", 0))
                    self._rates["okx"] = rate
                    # OKX exposes an explicit `nextFundingRate` field - use it
                    # when present, else fall back to the realized rate.
                    pred = items[0].get("nextFundingRate")
                    try:
                        self._predicted["okx"] = float(pred) if pred is not None else rate
                    except (TypeError, ValueError):
                        self._predicted["okx"] = rate
                    return rate
        except Exception as e:
            logger.error(f"OKX funding error: {e}")
        return None

    async def fetch_all(self) -> Dict:
        """Fetch funding rates from all exchanges."""
        import asyncio
        await asyncio.gather(
            self.fetch_binance(),
            self.fetch_okx(),
            return_exceptions=True,
        )
        return self.get_weighted_rate()

    def get_weighted_rate(self) -> Dict:
        """Compute OI-weighted average funding rate."""
        if not self._rates:
            return {"weighted_rate": 0, "classification": "no_data", "rates": {}}

        total_weight = 0
        weighted_sum = 0
        for exchange, rate in self._rates.items():
            w = EXCHANGE_WEIGHTS.get(exchange, 0.05)
            weighted_sum += rate * w
            total_weight += w

        weighted_rate = weighted_sum / total_weight if total_weight > 0 else 0
        rate_pct = weighted_rate * 100  # Convert to percentage

        # Classify
        classification = "neutral"
        for label, threshold in sorted(FUNDING_THRESHOLDS.items(), key=lambda x: abs(x[1]), reverse=True):
            if threshold > 0 and rate_pct >= threshold:
                classification = label
                break
            elif threshold < 0 and rate_pct <= threshold:
                classification = label
                break

        # Record history
        self._history.append({
            "timestamp": time.time(),
            "weighted_rate": weighted_rate,
            "rates": dict(self._rates),
        })
        if len(self._history) > 1000:
            self._history = self._history[-500:]

        zscore = self._compute_zscore(weighted_rate)

        return {
            "weighted_rate": round(weighted_rate, 6),
            "weighted_rate_pct": round(rate_pct, 4),
            "classification": classification,
            "rates": {k: round(v, 6) for k, v in self._rates.items()},
            "leverage_impact": f"At 10x: {round(rate_pct * 10 * 3, 4)}% daily drag" if rate_pct > 0 else "Shorts paying longs",
            "zscore": zscore["zscore"],
            "zscore_window": zscore["window"],
            "zscore_classification": zscore["classification"],
            "mean_rate": zscore["mean"],
            "std_rate": zscore["std"],
        }

    def _compute_zscore(self, current: float) -> Dict:
        """Rolling z-score of the current weighted funding rate against the
        last N historical samples. Uses population std, guards against zero
        variance so the result is always finite.

        Classification thresholds:
          |z| >= 2   crowded / extreme
          |z| >= 1   stretched
          else       normal
        """
        window = min(len(self._history), 240)  # ~ last 240 samples
        if window < 10:
            return {"zscore": 0.0, "window": window, "mean": 0.0, "std": 0.0, "classification": "insufficient_data"}

        samples = [h["weighted_rate"] for h in self._history[-window:]]
        mean = sum(samples) / window
        var = sum((x - mean) ** 2 for x in samples) / window
        std = var ** 0.5
        if std <= 1e-12:
            return {"zscore": 0.0, "window": window, "mean": mean, "std": std, "classification": "flat"}

        z = (current - mean) / std
        absz = abs(z)
        if absz >= 2:
            cls = "extreme_long_crowding" if z > 0 else "extreme_short_crowding"
        elif absz >= 1:
            cls = "stretched_long" if z > 0 else "stretched_short"
        else:
            cls = "normal"
        return {
            "zscore": round(z, 3),
            "window": window,
            "mean": round(mean, 6),
            "std": round(std, 6),
            "classification": cls,
        }

    # ------------------------------------------------------------------
    # Term structure (P1-1)
    # ------------------------------------------------------------------

    def _predicted_weighted(self) -> float:
        """Weighted average of per-exchange `nextFundingRate` predictions.
        Falls back to the current weighted rate when no venue supplied a
        forward quote."""
        if not self._predicted:
            agg = self.get_weighted_rate() if self._rates else {"weighted_rate": 0.0}
            return float(agg.get("weighted_rate", 0.0))

        total_w = 0.0
        acc = 0.0
        for ex, rate in self._predicted.items():
            w = EXCHANGE_WEIGHTS.get(ex, 0.05)
            acc += rate * w
            total_w += w
        return acc / total_w if total_w > 0 else 0.0

    def _rolling_samples(self, window_s: float = _SEVEN_DAYS_S) -> List[float]:
        cutoff = time.time() - window_s
        return [h["weighted_rate"] for h in self._history if h["timestamp"] >= cutoff]

    def term_structure(self) -> Dict:
        """Forward curve of funding for `self.symbol`.

        Returns
        -------
        {
          "spot":                       current weighted funding (per 8h settle),
          "predicted_1h":               predicted hourly drag = predicted_8h / 8,
          "predicted_8h":               weighted next-funding (per 8h settle),
          "realized_annualized_carry":  mean(rolling 7d) * 1095 (decimal, e.g. 0.12 = 12%/yr),
          "realized_annualized_carry_pct": same * 100,
          "window_samples":             how many samples backed the 7d mean,
          "slope_8h":                   predicted_8h − spot (crowding direction),
        }
        """
        spot_bundle = self.get_weighted_rate() if self._rates else {"weighted_rate": 0.0}
        spot = float(spot_bundle.get("weighted_rate", 0.0))
        predicted_8h = self._predicted_weighted()
        predicted_1h = predicted_8h / 8.0

        samples = self._rolling_samples(_SEVEN_DAYS_S)
        if samples:
            mean_rate = sum(samples) / len(samples)
        else:
            mean_rate = spot
        realized_annualized = mean_rate * _FUNDING_SETTLES_PER_YEAR

        return {
            "symbol": self.symbol,
            "spot": round(spot, 8),
            "predicted_1h": round(predicted_1h, 8),
            "predicted_8h": round(predicted_8h, 8),
            "slope_8h": round(predicted_8h - spot, 8),
            "realized_annualized_carry": round(realized_annualized, 6),
            "realized_annualized_carry_pct": round(realized_annualized * 100, 4),
            "window_samples": len(samples),
            "predicted_sources": dict(self._predicted),
        }

    def term_structure_skew(self) -> Dict:
        """Front-end (1h annualized) vs back-end (8h realized 7d mean) skew.

        The 8h realized rate is the trailing 7d mean of the per-settle funding
        rate annualized. The 1h annualized is the predicted next funding
        normalized to a yearly carry. Skew is the gap between them - positive
        means the curve is steeper at the front (rising funding pressure),
        negative means the back-end is fatter (decaying crowd).

        Confidence is tied to ``window_samples >= 10`` to gate noisy first-day
        readings. Consumers (alpha factor / dealer layer) downgrade weight or
        ignore the metric when ``available`` is False.
        """
        ts = self.term_structure()
        # Front: predicted 1h drag annualized to per-year carry.
        front = float(ts.get("predicted_1h", 0.0)) * _FUNDING_SETTLES_PER_YEAR * 8.0
        # Back: 7d realized mean already annualized.
        back = float(ts.get("realized_annualized_carry", 0.0))
        skew_abs = front - back
        skew_pct = (skew_abs / abs(back) * 100.0) if back != 0 else 0.0
        window_samples = int(ts.get("window_samples", 0))
        available = window_samples >= 10

        if not available:
            interpretation = "warmup"
        elif abs(skew_pct) < 5.0:
            interpretation = "flat"
        elif skew_pct > 5.0:
            interpretation = "front_steep"
        else:
            interpretation = "back_steep"

        return {
            "symbol": self.symbol,
            "front_rate_1h_annualized": round(front, 6),
            "back_rate_8h_realized": round(back, 6),
            "skew_abs": round(skew_abs, 6),
            "skew_pct": round(skew_pct, 4),
            "available": available,
            "window_samples": window_samples,
            "interpretation": interpretation,
        }

    def funding_zscore_rolling(self, window_hours: float = 168.0) -> Dict:
        """Wall-clock-windowed z-score of weighted funding rate.

        Distinct from `_compute_zscore` (which uses sample-count). Used by
        the circuit-breaker `on_funding_zscore` event hook so triggers fire
        on calendar-time crowding regardless of how often `fetch_all` was
        called. Default window 168h (7 days) per plan spec.
        """
        cutoff = time.time() - window_hours * 3600
        samples = [h["weighted_rate"] for h in self._history if h["timestamp"] >= cutoff]
        n = len(samples)
        if n < 10:
            return {
                "zscore": 0.0,
                "window_hours": window_hours,
                "samples": n,
                "mean": 0.0,
                "std": 0.0,
                "current": float(self.get_weighted_rate().get("weighted_rate", 0.0)) if self._rates else 0.0,
                "classification": "insufficient_data",
            }
        current = samples[-1]
        mean = sum(samples) / n
        var = sum((x - mean) ** 2 for x in samples) / n
        std = var ** 0.5
        z = 0.0 if std <= 1e-12 else (current - mean) / std
        absz = abs(z)
        if absz >= 2.5:
            cls = "extreme"
        elif absz >= 1.5:
            cls = "stretched"
        else:
            cls = "normal"
        return {
            "zscore": round(z, 3),
            "window_hours": window_hours,
            "samples": n,
            "mean": round(mean, 8),
            "std": round(std, 8),
            "current": round(current, 8),
            "classification": cls,
        }

    def carry_signal(self) -> Dict:
        """Bounded funding-carry score in [-1, +1] for alpha composite use.

        Maps annualized carry to a saturating tanh-like score:

            score = clamp(annualized_carry / ref, -1, +1)

        with ref = 50% annualized (≈ 0.00046/8h, well past "crowded" on both
        BTC and ETH perps). Sign follows carry direction - **positive carry
        (longs paying shorts) yields a NEGATIVE alpha contribution** because
        it signals long-side crowding / mean reversion risk (classic basis
        trade short the over-funded leg).

        Returned dict is shaped to drop into alpha_engine:
            {"score": float in [-1,1], "confidence": float in [0,1], ...}
        """
        ts = self.term_structure()
        annualized = ts["realized_annualized_carry"]
        ref = 0.50
        raw = annualized / ref if ref else 0.0
        # Contrarian to crowding: positive carry → short-bias alpha.
        score = -max(-1.0, min(1.0, raw))

        # Confidence = history coverage × |z-score magnitude| of spot
        # (normalized). Short history or flat tape → low confidence.
        hist_n = ts["window_samples"]
        hist_confidence = min(1.0, hist_n / 240.0)  # ≥240 samples = full conf
        z = self._compute_zscore(ts["spot"])["zscore"]
        z_conf = min(1.0, abs(z) / 2.0)
        confidence = round(0.5 * hist_confidence + 0.5 * z_conf, 4)

        return {
            "score": round(score, 4),
            "confidence": confidence,
            "annualized_carry_pct": ts["realized_annualized_carry_pct"],
            "spot": ts["spot"],
            "predicted_8h": ts["predicted_8h"],
            "slope_8h": ts["slope_8h"],
            "zscore": z,
            "interpretation": (
                "long_crowded_short_bias" if score < -0.3
                else "short_crowded_long_bias" if score > 0.3
                else "neutral"
            ),
        }
