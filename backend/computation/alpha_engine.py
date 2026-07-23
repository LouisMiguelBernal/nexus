"""
Nexus -- Alpha Signal Engine
Renaissance Technologies / Two Sigma inspired multi-factor alpha generation.
Combines order flow, funding, cross-exchange spreads, liquidation risk,
delta divergence, smart money flow, and volatility regime into a composite
alpha score for institutional-grade signal generation.
"""

import logging
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    # Regime classifier - regime-conditional factor loading (P0-1).
    # Import is soft-coupled so alpha_engine still works if regime.py moves.
    from backend.computation.regime import RegimeClassifier
except ImportError:  # pragma: no cover - local-dev fallback
    try:
        from .regime import RegimeClassifier  # type: ignore
    except Exception:
        RegimeClassifier = None  # type: ignore

logger = logging.getLogger("nexus.alpha_engine")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AlphaSignal:
    """A single alpha signal with direction, strength, and metadata."""

    name: str
    direction: str  # "long", "short", "neutral"
    strength: float  # 0-100
    strength_raw: float = 0.0  # unclamped value for diagnostics
    confidence: float = 0.0  # 0-1
    reasoning: str = ""
    timeframe: str = "intraday"  # "scalp", "intraday", "swing"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "strength": round(self.strength, 2),
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_stdev(values: list[float], min_count: int = 3) -> float:
    """Return population stdev or 0.0 when there are too few values."""
    if len(values) < min_count:
        return 0.0
    try:
        return statistics.pstdev(values)
    except statistics.StatisticsError:
        return 0.0


def _ema(values: list[float], span: int) -> float:
    """Compute exponential moving average of *values* with given span."""
    if not values:
        return 0.0
    alpha = 2.0 / (span + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = alpha * v + (1.0 - alpha) * ema_val
    return ema_val


# ---------------------------------------------------------------------------
# Constants / Weights
# ---------------------------------------------------------------------------

# Default signal weights for composite scoring (regime-neutral baseline)
SIGNAL_WEIGHTS: Dict[str, float] = {
    "ofi": 0.18,
    "vwap_deviation": 0.12,
    "funding_arb": 0.10,
    "cross_exchange_spread": 0.10,
    "liquidation_cascade": 0.12,
    "delta_divergence": 0.15,
    "smart_money_flow": 0.13,
    "vol_regime": 0.10,
}

# Sanity check
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-6, "Signal weights must sum to 1"


# Regime-conditional factor loading (Harvey/Liu/Zhu 2016) - 11-factor.
#
# Each dict must sum to 1.0. Selected at composite time based on regime.classify().
# Philosophy:
#   trending_*  -> momentum / flow factors dominate (OFI, smart money, TSMOM, OI-mom)
#   ranging     -> mean-reversion factors dominate (VWAP dev, funding fade, carry contrarian)
#   volatile    -> risk-off: smart money + liquidation cascade up-weighted
#   low_liq     -> structural (funding arb, spread, funding carry) dominate
#
# New factors (P1):
#   funding_carry  (P1-1) - contrarian to annualized funding crowding
#   tsmom          (P1-3) - vol-scaled 12h/1h time-series momentum
#   oi_momentum    (P1-5) - OI rate-of-change z-score
WEIGHTS_BY_REGIME: Dict[str, Dict[str, float]] = {
    "trending_bull": {
        "ofi": 0.18, "vwap_deviation": 0.04, "funding_arb": 0.06,
        "cross_exchange_spread": 0.06, "liquidation_cascade": 0.10,
        "delta_divergence": 0.10, "smart_money_flow": 0.14, "vol_regime": 0.08,
        "tsmom": 0.10, "oi_momentum": 0.06, "funding_carry": 0.04,
        "squeeze": 0.04,
    },
    "trending_bear": {
        "ofi": 0.18, "vwap_deviation": 0.04, "funding_arb": 0.06,
        "cross_exchange_spread": 0.06, "liquidation_cascade": 0.10,
        "delta_divergence": 0.10, "smart_money_flow": 0.14, "vol_regime": 0.08,
        "tsmom": 0.10, "oi_momentum": 0.06, "funding_carry": 0.04,
        "squeeze": 0.04,
    },
    "ranging": {
        "ofi": 0.10, "vwap_deviation": 0.12, "funding_arb": 0.10,
        "cross_exchange_spread": 0.10, "liquidation_cascade": 0.06,
        "delta_divergence": 0.10, "smart_money_flow": 0.08, "vol_regime": 0.08,
        "tsmom": 0.04, "oi_momentum": 0.04, "funding_carry": 0.10,
        "squeeze": 0.08,
    },
    "volatile": {
        "ofi": 0.12, "vwap_deviation": 0.08, "funding_arb": 0.08,
        "cross_exchange_spread": 0.08, "liquidation_cascade": 0.10,
        "delta_divergence": 0.07, "smart_money_flow": 0.11, "vol_regime": 0.08,
        "tsmom": 0.06, "oi_momentum": 0.06, "funding_carry": 0.06,
        "squeeze": 0.10,
    },
    "low_liq": {
        "ofi": 0.06, "vwap_deviation": 0.08, "funding_arb": 0.10,
        "cross_exchange_spread": 0.10, "liquidation_cascade": 0.08,
        "delta_divergence": 0.08, "smart_money_flow": 0.10, "vol_regime": 0.10,
        "tsmom": 0.04, "oi_momentum": 0.04, "funding_carry": 0.10,
        "squeeze": 0.12,
    },
    # Fallback (8-factor legacy). New P1 factors (incl. squeeze) get zero
    # weight here - safe degradation when we can't classify regime.
    "insufficient_data": SIGNAL_WEIGHTS,
}

# Sanity check each regime profile sums to 1.
for _regime_name, _profile in WEIGHTS_BY_REGIME.items():
    _total = sum(_profile.values())
    assert abs(_total - 1.0) < 1e-6, (
        f"Regime '{_regime_name}' weights must sum to 1, got {_total:.6f}"
    )


# ---------------------------------------------------------------------------
# AlphaEngine
# ---------------------------------------------------------------------------

class AlphaEngine:
    """
    Multi-factor alpha signal engine.

    Accepts a symbol string and a reference to the in-memory BinanceFuturesData
    store so it can read order books, agg trades, liquidations, and mark prices
    directly.
    """

    def __init__(
        self,
        symbol: str,
        binance_data: Any = None,
        *,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.symbol = symbol.upper()
        self.binance_data = binance_data

        # Baseline weights - overridden per-cycle by regime-conditional lookup
        # unless the caller explicitly pins a weight dict (tests / backtests).
        self._weights = weights or SIGNAL_WEIGHTS.copy()
        self._weights_pinned = weights is not None

        # Regime classifier for regime-conditional factor loading (P0-1).
        # Lives for the life of the engine instance; safe to reuse across cycles.
        self._regime_classifier = RegimeClassifier() if RegimeClassifier is not None else None
        self._last_regime: Dict[str, Any] = {"regime": "insufficient_data", "confidence": 0.0}

        # Internal rolling stores
        self._ofi_history: deque[float] = deque(maxlen=300)
        self._vwap_prices: deque[Tuple[float, float]] = deque(maxlen=10_000)
        self._spread_history: deque[Dict[str, float]] = deque(maxlen=300)
        self._vol_history: deque[float] = deque(maxlen=500)

        # Cache last composite
        self._last_composite: Optional[dict] = None

        logger.info("AlphaEngine initialised for %s", self.symbol)

    # ------------------------------------------------------------------
    # Regime-conditional weight selection (P0-1)
    # ------------------------------------------------------------------

    def _classify_regime(self, klines: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Classify current regime from provided klines; cache last known.

        *klines* is an iterable of dicts with keys {close, volume, high, low}.
        If classifier unavailable or data insufficient, returns the previous
        regime so composite weights don't flap.
        """
        if self._regime_classifier is None or not klines or len(klines) < 20:
            return self._last_regime

        try:
            closes = [float(k["close"]) for k in klines]
            volumes = [float(k.get("volume", 0.0)) for k in klines]
            highs = [float(k["high"]) for k in klines]
            lows = [float(k["low"]) for k in klines]
            result = self._regime_classifier.classify(closes, volumes, highs, lows)
            self._last_regime = result
            return result
        except Exception:
            logger.exception("regime classification failed for %s", self.symbol)
            return self._last_regime

    def _select_weights(self, regime_label: str) -> Dict[str, float]:
        """Pick weight profile for the current regime, honoring pinned weights."""
        if self._weights_pinned:
            return self._weights
        profile = WEIGHTS_BY_REGIME.get(regime_label)
        if profile is None:
            profile = WEIGHTS_BY_REGIME["insufficient_data"]
        return profile

    # ------------------------------------------------------------------
    # Data accessors (thin helpers over BinanceFuturesData)
    # ------------------------------------------------------------------

    def _get_order_book(self) -> Optional[dict]:
        if self.binance_data is None:
            return None
        return self.binance_data.order_books.get(self.symbol)

    def _get_agg_trades(self) -> deque:
        if self.binance_data is None:
            return deque()
        return self.binance_data.agg_trades.get(self.symbol, deque())

    def _get_mark_price_info(self) -> Optional[dict]:
        if self.binance_data is None:
            return None
        return self.binance_data.mark_prices.get(self.symbol)

    def _get_liquidations(self) -> deque:
        if self.binance_data is None:
            return deque()
        return self.binance_data.liquidations.get(self.symbol, deque())

    # Public feed hooks ------------------------------------------------
    def ingest_trade(self, price: float, qty: float) -> None:
        """Forward a single aggTrade into the VWAP running-window. Called
        by main.py's zone loop once per new trade."""
        if price > 0 and qty > 0:
            self._vwap_prices.append((price, qty))

    # ==================================================================
    # 1. Order Flow Imbalance (OFI)
    # ==================================================================

    def compute_ofi(self) -> AlphaSignal:
        """
        Measure aggressive buying vs selling pressure from order book snapshots.
        OFI = sum(bid_delta) - sum(ask_delta) across top levels.
        A positive OFI means aggressive buying is dominating.
        """
        ob = self._get_order_book()
        if ob is None or not ob.get("bids") or not ob.get("asks"):
            return AlphaSignal(
                name="ofi",
                direction="neutral",
                strength=0.0,
                confidence=0.0,
                reasoning="No order book data available",
                timeframe="scalp",
            )

        bids: list[list[float]] = ob["bids"]
        asks: list[list[float]] = ob["asks"]

        # Weighted imbalance across levels (deeper levels get less weight)
        bid_pressure = 0.0
        ask_pressure = 0.0
        max_levels = min(len(bids), len(asks), 20)

        for i in range(max_levels):
            weight = 1.0 / (1.0 + i * 0.3)  # decaying weight
            bid_pressure += bids[i][1] * weight
            ask_pressure += asks[i][1] * weight

        total = bid_pressure + ask_pressure
        if total < 1e-12:
            return AlphaSignal(
                name="ofi", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Zero liquidity", timeframe="scalp",
            )

        imbalance = (bid_pressure - ask_pressure) / total  # range [-1, 1]
        self._ofi_history.append(imbalance)

        # Use historical context for z-score
        if len(self._ofi_history) >= 10:
            mean_imb = statistics.mean(self._ofi_history)
            std_imb = _safe_stdev(list(self._ofi_history), 5)
            z = (imbalance - mean_imb) / std_imb if std_imb > 1e-9 else 0.0
        else:
            z = imbalance * 2.0  # rough scaling when history is thin

        strength = _clamp(abs(z) * 25.0, 0.0, 100.0)
        direction = "long" if imbalance > 0.05 else ("short" if imbalance < -0.05 else "neutral")
        confidence = _clamp(min(len(self._ofi_history) / 60.0, 1.0) * (strength / 100.0), 0.0, 1.0)

        return AlphaSignal(
            name="ofi",
            direction=direction,
            strength=strength,
            strength_raw=z,
            confidence=confidence,
            reasoning=(
                f"Bid pressure={bid_pressure:.1f}, Ask pressure={ask_pressure:.1f}, "
                f"imbalance={imbalance:+.3f}, z={z:+.2f}"
            ),
            timeframe="scalp",
        )

    # ==================================================================
    # 2. VWAP Deviation
    # ==================================================================

    def compute_vwap_deviation(self) -> AlphaSignal:
        """
        Track volume-weighted average price and signal when current price
        deviates by more than 1 standard deviation.
        """
        trades = self._get_agg_trades()
        if len(trades) < 20:
            return AlphaSignal(
                name="vwap_deviation", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Insufficient trade data", timeframe="intraday",
            )

        # Compute VWAP over recent trades
        pv_sum = 0.0
        v_sum = 0.0
        prices: list[float] = []
        for t in trades:
            p = t["price"]
            q = t["qty"]
            pv_sum += p * q
            v_sum += q
            prices.append(p)

        if v_sum < 1e-12:
            return AlphaSignal(
                name="vwap_deviation", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Zero volume", timeframe="intraday",
            )

        vwap = pv_sum / v_sum
        current_price = prices[-1]
        deviation = current_price - vwap
        price_std = _safe_stdev(prices, 5)

        if price_std < 1e-12:
            z_dev = 0.0
        else:
            z_dev = deviation / price_std

        # Signal: mean reversion when price is stretched
        # Above VWAP => short bias (mean revert), below => long bias
        if abs(z_dev) < 1.0:
            direction = "neutral"
        elif z_dev > 0:
            direction = "short"  # overextended above VWAP, expect reversion
        else:
            direction = "long"  # below VWAP, expect reversion

        strength = _clamp(abs(z_dev) * 20.0, 0.0, 100.0)
        confidence = _clamp(min(len(prices) / 500.0, 1.0) * (0.5 + 0.5 * min(abs(z_dev) / 3.0, 1.0)), 0.0, 1.0)

        return AlphaSignal(
            name="vwap_deviation",
            direction=direction,
            strength=strength,
            strength_raw=z_dev,
            confidence=confidence,
            reasoning=(
                f"VWAP={vwap:.2f}, price={current_price:.2f}, "
                f"dev={deviation:+.2f}, z={z_dev:+.2f}, std={price_std:.2f}"
            ),
            timeframe="intraday",
        )

    # ==================================================================
    # 3. Funding Rate Arbitrage
    # ==================================================================

    def compute_funding_arb(self, funding_data: Optional[dict] = None) -> AlphaSignal:
        """
        Detect extreme funding and signal mean reversion.

        funding_data expected shape (from FundingTracker):
        {
            "weighted_rate": float,  # bps
            "rates": {"binance": float, "okx": float, ...},
            "spread": float,         # max - min across exchanges
            "annualized": float,
        }
        """
        if funding_data is None:
            # Fall back to mark price info
            mp = self._get_mark_price_info()
            if mp is None:
                return AlphaSignal(
                    name="funding_arb", direction="neutral", strength=0.0,
                    confidence=0.0, reasoning="No funding data", timeframe="swing",
                )
            funding_data = {
                "weighted_rate": mp.get("funding_rate", 0.0),
                "rates": {"binance": mp.get("funding_rate", 0.0)},
                "spread": 0.0,
                "annualized": mp.get("funding_rate", 0.0) * 3 * 365 * 100,
            }

        rate = funding_data.get("weighted_rate", 0.0)
        spread = funding_data.get("spread", 0.0)

        # Thresholds in raw 8-hour funding rate
        # Normal range: -0.01% to +0.01% (0.0001)
        # Elevated: > 0.03% or < -0.03%
        # Extreme: > 0.05% or < -0.05%
        abs_rate = abs(rate)

        if abs_rate < 0.0001:
            return AlphaSignal(
                name="funding_arb", direction="neutral", strength=0.0,
                confidence=0.4, reasoning=f"Funding neutral: {rate*100:.4f}%", timeframe="swing",
            )

        # Positive funding => longs pay shorts => bearish mean reversion
        # Negative funding => shorts pay longs => bullish mean reversion
        direction = "short" if rate > 0 else "long"

        # Scale strength: 0.03% = moderate (~40), 0.10% = extreme (~90)
        strength = _clamp(abs_rate / 0.001 * 10.0, 0.0, 100.0)
        confidence = _clamp(0.3 + 0.7 * min(abs_rate / 0.0005, 1.0), 0.0, 1.0)

        # Boost if cross-exchange spread is also wide
        if spread > 0.0001:
            strength = min(strength * 1.15, 100.0)
            confidence = min(confidence + 0.05, 1.0)

        return AlphaSignal(
            name="funding_arb",
            direction=direction,
            strength=strength,
            strength_raw=rate,
            confidence=confidence,
            reasoning=(
                f"Funding rate={rate*100:.4f}%, annualised={funding_data.get('annualized', 0):.1f}%, "
                f"cross-exchange spread={spread*100:.4f}%"
            ),
            timeframe="swing",
        )

    # ==================================================================
    # 4. Cross-Exchange Spread
    # ==================================================================

    def compute_cross_exchange_spread(self, all_data: Optional[dict] = None) -> AlphaSignal:
        """
        Detect price dislocations between exchanges.

        all_data expected shape:
        {
            "binance": {"mid_price": float},
            "okx": {"mid_price": float},
            "mexc": {"mid_price": float},
        }
        """
        if all_data is None or len(all_data) < 2:
            return AlphaSignal(
                name="cross_exchange_spread", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Insufficient cross-exchange data", timeframe="scalp",
            )

        prices = {k: v.get("mid_price", 0) for k, v in all_data.items() if v.get("mid_price", 0) > 0}
        if len(prices) < 2:
            return AlphaSignal(
                name="cross_exchange_spread", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Too few valid prices", timeframe="scalp",
            )

        price_list = list(prices.values())
        mean_price = statistics.mean(price_list)
        max_price = max(price_list)
        min_price = min(price_list)
        spread_bps = (max_price - min_price) / mean_price * 10_000 if mean_price > 0 else 0.0

        leader_exchange = max(prices, key=prices.get)  # type: ignore[arg-type]
        laggard_exchange = min(prices, key=prices.get)  # type: ignore[arg-type]

        self._spread_history.append({"spread_bps": spread_bps, "ts": time.time()})

        # Historical context
        recent_spreads = [s["spread_bps"] for s in self._spread_history]
        avg_spread = statistics.mean(recent_spreads) if recent_spreads else spread_bps
        std_spread = _safe_stdev(recent_spreads, 5)
        z = (spread_bps - avg_spread) / std_spread if std_spread > 1e-9 else 0.0

        # Binance is typically the price leader; if Binance leads higher => bullish signal
        binance_price = prices.get("binance", mean_price)
        direction = "long" if binance_price > mean_price else "short"
        if spread_bps < 1.0:
            direction = "neutral"

        strength = _clamp(spread_bps * 5.0, 0.0, 100.0)
        confidence = _clamp(min(len(prices) / 4.0, 1.0) * min(abs(z) / 2.0, 1.0), 0.0, 1.0)

        return AlphaSignal(
            name="cross_exchange_spread",
            direction=direction,
            strength=strength,
            strength_raw=spread_bps,
            confidence=confidence,
            reasoning=(
                f"Spread={spread_bps:.2f}bps, leader={leader_exchange}({max_price:.2f}), "
                f"laggard={laggard_exchange}({min_price:.2f}), z={z:+.2f}"
            ),
            timeframe="scalp",
        )

    # ==================================================================
    # 5. Liquidation Cascade Predictor
    # ==================================================================

    def compute_liquidation_cascade(
        self,
        oi_data: Optional[dict] = None,
        funding_data: Optional[dict] = None,
    ) -> AlphaSignal:
        """
        Estimate liquidation cascade risk.

        oi_data expected shape:
        {
            "open_interest": float,      # total OI in USD
            "oi_change_pct": float,      # 24h OI change %
            "long_short_ratio": float,   # > 1 means more longs
        }
        """
        liqs = self._get_liquidations()
        mp_info = self._get_mark_price_info()
        mark_price = mp_info.get("mark_price", 0) if mp_info else 0
        funding_rate = mp_info.get("funding_rate", 0) if mp_info else 0

        if oi_data:
            oi_usd = oi_data.get("open_interest", 0)
            oi_change = oi_data.get("oi_change_pct", 0)
            ls_ratio = oi_data.get("long_short_ratio", 1.0)
        else:
            oi_usd = 0
            oi_change = 0
            ls_ratio = 1.0

        # Recent liquidation intensity (last 5 minutes)
        now_ms = time.time() * 1000
        recent_liqs = [liq for liq in liqs if (now_ms - liq.get("time", 0)) < 300_000]
        liq_usd_total = sum(liq.get("usd_value", liq["price"] * liq["qty"]) for liq in recent_liqs)
        long_liq_usd = sum(
            liq.get("usd_value", liq["price"] * liq["qty"])
            for liq in recent_liqs if liq.get("side", "") == "SELL"
        )
        short_liq_usd = liq_usd_total - long_liq_usd

        # Score components
        cascade_score = 0.0
        reasons: list[str] = []

        # High OI + rising = more fuel for cascade
        if oi_change > 5:
            cascade_score += 20.0
            reasons.append(f"OI surging +{oi_change:.1f}%")

        # Extreme funding => one side is crowded
        if abs(funding_rate) > 0.0003:
            cascade_score += 15.0
            reasons.append(f"Extreme funding {funding_rate*100:.4f}%")

        # Lopsided L/S ratio
        if ls_ratio > 1.5 or ls_ratio < 0.67:
            cascade_score += 15.0
            crowded = "longs" if ls_ratio > 1 else "shorts"
            reasons.append(f"Crowded {crowded} (ratio={ls_ratio:.2f})")

        # Active liquidations
        if liq_usd_total > 100_000:
            cascade_score += min(liq_usd_total / 50_000, 30.0)
            reasons.append(f"Active liqs ${liq_usd_total:,.0f}")

        # Direction: cascade liquidates the crowded side
        if ls_ratio > 1.2 or funding_rate > 0.0002:
            direction = "short"  # longs get liquidated
        elif ls_ratio < 0.8 or funding_rate < -0.0002:
            direction = "long"  # shorts get squeezed
        else:
            direction = "neutral"

        strength = _clamp(cascade_score, 0.0, 100.0)
        confidence = _clamp(
            0.2 + 0.3 * (1 if oi_data else 0) + 0.3 * min(len(recent_liqs) / 10, 1.0)
            + 0.2 * min(abs(funding_rate) / 0.0005, 1.0),
            0.0, 1.0,
        )

        return AlphaSignal(
            name="liquidation_cascade",
            direction=direction,
            strength=strength,
            strength_raw=cascade_score,
            confidence=confidence,
            reasoning="; ".join(reasons) if reasons else "Low cascade risk",
            timeframe="intraday",
        )

    # ==================================================================
    # 6. Delta Divergence (Price vs CVD)
    # ==================================================================

    def compute_delta_divergence(self, cvd_data: Optional[dict] = None) -> AlphaSignal:
        """
        Detect price vs cumulative volume delta divergence.

        cvd_data expected shape (from CVDComputer.get_cvd()):
        {
            "cvd": float,
            "buy_volume": float,
            "sell_volume": float,
            "net_delta": float,
            "price_change": float,   # optional
            "price_high": float,     # optional
            "price_low": float,      # optional
        }
        """
        trades = self._get_agg_trades()
        if cvd_data is None and len(trades) < 50:
            return AlphaSignal(
                name="delta_divergence", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Insufficient data for divergence", timeframe="intraday",
            )

        # Build CVD locally if not provided
        if cvd_data is None:
            trade_list = list(trades)
            cvd = 0.0
            prices: list[float] = []
            for t in trade_list:
                p, q, m = t["price"], t["qty"], t["is_buyer_maker"]
                usd = p * q
                cvd += -usd if m else usd
                prices.append(p)
            cvd_data = {
                "cvd": cvd,
                "price_high": max(prices) if prices else 0,
                "price_low": min(prices) if prices else 0,
            }
            # Compute price trend vs CVD trend over halves
            mid = len(trade_list) // 2
            first_half = trade_list[:mid]
            second_half = trade_list[mid:]

            cvd_first = sum(-t["price"] * t["qty"] if t["is_buyer_maker"] else t["price"] * t["qty"] for t in first_half)
            cvd_second = sum(-t["price"] * t["qty"] if t["is_buyer_maker"] else t["price"] * t["qty"] for t in second_half)

            price_first = statistics.mean([t["price"] for t in first_half]) if first_half else 0
            price_second = statistics.mean([t["price"] for t in second_half]) if second_half else 0
        else:
            cvd_first = 0
            cvd_second = cvd_data.get("cvd", 0)
            price_first = cvd_data.get("price_low", 0)
            price_second = cvd_data.get("price_high", 0)

        # Detect divergence
        price_rising = price_second > price_first
        cvd_rising = cvd_second > cvd_first

        if price_rising and not cvd_rising:
            # Bearish divergence: price up, CVD down
            direction = "short"
            reasoning = "Bearish divergence: price rising but CVD declining"
        elif not price_rising and cvd_rising:
            # Bullish divergence: price down, CVD up
            direction = "long"
            reasoning = "Bullish divergence: price falling but CVD rising"
        else:
            direction = "neutral"
            reasoning = "No divergence: price and CVD aligned"

        # Magnitude of divergence
        if price_first > 0 and cvd_first != 0:
            price_change_pct = abs(price_second - price_first) / price_first * 100
            cvd_change_pct = abs(cvd_second - cvd_first) / (abs(cvd_first) + 1e-9) * 100
            divergence_magnitude = min(price_change_pct + cvd_change_pct, 10.0)
        else:
            divergence_magnitude = 0.0

        strength = _clamp(divergence_magnitude * 10.0, 0.0, 100.0) if direction != "neutral" else 0.0
        confidence = _clamp(
            0.3 + 0.4 * min(divergence_magnitude / 5.0, 1.0) + 0.3 * min(len(trades) / 1000, 1.0),
            0.0, 1.0,
        ) if direction != "neutral" else 0.1

        return AlphaSignal(
            name="delta_divergence",
            direction=direction,
            strength=strength,
            strength_raw=divergence_magnitude if direction != "neutral" else 0.0,
            confidence=confidence,
            reasoning=reasoning,
            timeframe="intraday",
        )

    # ==================================================================
    # 7. Smart Money Flow
    # ==================================================================

    def compute_smart_money_flow(self) -> AlphaSignal:
        """
        Detect large order clustering and whale accumulation/distribution
        from order book and recent trade data.
        """
        trades = self._get_agg_trades()
        ob = self._get_order_book()

        if len(trades) < 30:
            return AlphaSignal(
                name="smart_money_flow", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Insufficient trade data", timeframe="intraday",
            )

        trade_list = list(trades)

        # Identify large trades (> 90th percentile by USD value)
        usd_values = [t["price"] * t["qty"] for t in trade_list]
        usd_values_sorted = sorted(usd_values)
        p90_idx = int(len(usd_values_sorted) * 0.9)
        large_threshold = usd_values_sorted[p90_idx] if p90_idx < len(usd_values_sorted) else 0

        large_buy_usd = 0.0
        large_sell_usd = 0.0
        large_count = 0

        for t in trade_list:
            usd = t["price"] * t["qty"]
            if usd >= large_threshold and large_threshold > 0:
                large_count += 1
                if t["is_buyer_maker"]:
                    large_sell_usd += usd
                else:
                    large_buy_usd += usd

        total_large = large_buy_usd + large_sell_usd
        if total_large < 1e-9:
            return AlphaSignal(
                name="smart_money_flow", direction="neutral", strength=0.0,
                confidence=0.1, reasoning="No significant large trades", timeframe="intraday",
            )

        # Net large flow
        net_flow = large_buy_usd - large_sell_usd
        flow_ratio = net_flow / total_large  # [-1, 1]

        # Check order book for whale walls
        wall_bias = 0.0
        if ob and ob.get("bids") and ob.get("asks"):
            bids = ob["bids"]
            asks = ob["asks"]
            bid_sizes = [b[1] for b in bids[:5]]
            ask_sizes = [a[1] for a in asks[:5]]
            avg_bid = statistics.mean(bid_sizes) if bid_sizes else 0
            avg_ask = statistics.mean(ask_sizes) if ask_sizes else 0
            max_bid = max(bid_sizes) if bid_sizes else 0
            max_ask = max(ask_sizes) if ask_sizes else 0

            # Large wall on bids = support = accumulation hint
            if max_bid > avg_bid * 3 and avg_bid > 0:
                wall_bias += 0.15
            if max_ask > avg_ask * 3 and avg_ask > 0:
                wall_bias -= 0.15

        combined = flow_ratio * 0.7 + wall_bias * 0.3
        direction = "long" if combined > 0.05 else ("short" if combined < -0.05 else "neutral")
        strength = _clamp(abs(combined) * 80.0, 0.0, 100.0)
        confidence = _clamp(
            0.2 + 0.5 * min(large_count / 50.0, 1.0) + 0.3 * abs(combined),
            0.0, 1.0,
        )

        return AlphaSignal(
            name="smart_money_flow",
            direction=direction,
            strength=strength,
            strength_raw=combined,
            confidence=confidence,
            reasoning=(
                f"Large buy=${large_buy_usd:,.0f}, sell=${large_sell_usd:,.0f}, "
                f"flow_ratio={flow_ratio:+.3f}, wall_bias={wall_bias:+.3f}"
            ),
            timeframe="intraday",
        )

    # ==================================================================
    # 8. Volatility Regime Shift
    # ==================================================================

    def compute_vol_regime(self, deribit_data: Optional[dict] = None) -> AlphaSignal:
        """
        Detect transitions between volatility regimes.

        deribit_data expected shape:
        {
            "iv_index": float,       # implied vol from Deribit DVOL or ATM options
            "iv_term_structure": list,  # optional
        }
        """
        trades = self._get_agg_trades()
        if len(trades) < 30:
            return AlphaSignal(
                name="vol_regime", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Insufficient data for vol analysis", timeframe="swing",
            )

        # Compute realized vol from log returns
        trade_list = list(trades)
        prices = [t["price"] for t in trade_list]

        log_returns: list[float] = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                lr = math.log(prices[i] / prices[i - 1])
                log_returns.append(lr)

        if len(log_returns) < 10:
            return AlphaSignal(
                name="vol_regime", direction="neutral", strength=0.0,
                confidence=0.0, reasoning="Not enough returns for vol calc", timeframe="swing",
            )

        rv = _safe_stdev(log_returns, 5) * math.sqrt(len(log_returns))  # period vol
        self._vol_history.append(rv)

        # Vol regime classification
        recent_vol = statistics.mean(list(self._vol_history)[-20:]) if len(self._vol_history) >= 5 else rv
        older_vol = statistics.mean(list(self._vol_history)[-100:-20]) if len(self._vol_history) >= 50 else recent_vol
        vol_change = (recent_vol - older_vol) / older_vol if older_vol > 1e-12 else 0.0

        # Compare RV to IV if Deribit data available
        iv = deribit_data.get("iv_index", 0) if deribit_data else 0
        rv_annualised = rv * math.sqrt(365 * 24 * 3600 / max(1, len(trade_list)))  # rough annualisation

        vrp = 0.0  # vol risk premium
        if iv > 0 and rv_annualised > 0:
            vrp = (iv - rv_annualised * 100) / iv  # positive = IV > RV = sell vol

        # Regime shift = vol expansion/compression
        if vol_change > 0.5:
            direction = "neutral"  # vol expanding = uncertain direction, but important signal
            reasoning = f"Vol EXPANDING: recent={recent_vol:.6f} vs older={older_vol:.6f} (+{vol_change*100:.0f}%)"
        elif vol_change < -0.3:
            direction = "neutral"
            reasoning = f"Vol COMPRESSING: recent={recent_vol:.6f} vs older={older_vol:.6f} ({vol_change*100:.0f}%)"
        else:
            direction = "neutral"
            reasoning = f"Vol stable: {recent_vol:.6f}"

        # VRP signal: high IV vs low RV = sell vol (usually short gamma)
        if vrp > 0.2 and iv > 0:
            reasoning += f" | IV premium {vrp*100:.0f}% (sell vol bias)"
        elif vrp < -0.2 and iv > 0:
            reasoning += " | RV > IV (buy vol bias)"

        strength = _clamp(abs(vol_change) * 80.0, 0.0, 100.0)
        confidence = _clamp(
            0.2 + 0.4 * min(len(self._vol_history) / 100.0, 1.0)
            + 0.2 * (1.0 if iv > 0 else 0.0)
            + 0.2 * min(abs(vol_change), 1.0),
            0.0, 1.0,
        )

        return AlphaSignal(
            name="vol_regime",
            direction=direction,
            strength=strength,
            strength_raw=vol_change,
            confidence=confidence,
            reasoning=reasoning,
            timeframe="swing",
        )

    # ==================================================================
    # 9. P1 factor adapters (funding_carry / tsmom / oi_momentum)
    # ==================================================================

    @staticmethod
    def _score_to_signal(
        name: str,
        payload: Optional[Dict[str, Any]],
        *,
        timeframe: str,
        reason_prefix: str,
    ) -> AlphaSignal:
        """Convert a `{score ∈ [-1,1], confidence, ...}` dict from a P1
        factor module into an AlphaSignal suitable for the composite.

        The factor modules (funding.carry_signal, factors.tsmom.compute_tsmom,
        oi_analysis.roc_zscore) each return a shaped dict - this keeps
        alpha_engine decoupled from their internals while giving the
        composite a unified direction/strength view.
        """
        if not payload:
            return AlphaSignal(
                name=name, direction="neutral", strength=0.0,
                confidence=0.0, reasoning=f"{reason_prefix}: no data",
                timeframe=timeframe,
            )
        try:
            raw = float(payload.get("score", 0.0))
        except (TypeError, ValueError):
            raw = 0.0
        try:
            conf = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0

        raw = max(-1.0, min(1.0, raw))
        direction = "long" if raw > 0.1 else ("short" if raw < -0.1 else "neutral")
        strength = _clamp(abs(raw) * 100.0, 0.0, 100.0)

        # Summarize a few diagnostic fields for the reasoning trace.
        diag_bits: list[str] = []
        for key in ("annualized_carry_pct", "scale", "zscore", "roc_pct",
                    "realized_vol_annual", "direction", "interpretation"):
            if key in payload and payload[key] is not None:
                diag_bits.append(f"{key}={payload[key]}")
        reasoning = f"{reason_prefix}: score={raw:+.3f}" + (
            "; " + ", ".join(diag_bits) if diag_bits else ""
        )

        return AlphaSignal(
            name=name,
            direction=direction,
            strength=strength,
            strength_raw=raw,
            confidence=_clamp(conf, 0.0, 1.0),
            reasoning=reasoning,
            timeframe=timeframe,
        )

    def compute_funding_carry(self, carry_data: Optional[Dict[str, Any]]) -> AlphaSignal:
        """Adapter for `FundingTracker.carry_signal()` output (P1-1)."""
        return self._score_to_signal(
            "funding_carry", carry_data, timeframe="swing",
            reason_prefix="Funding carry",
        )

    def compute_tsmom(self, tsmom_data: Optional[Dict[str, Any]]) -> AlphaSignal:
        """Adapter for `factors.tsmom.compute_tsmom()` output (P1-3)."""
        return self._score_to_signal(
            "tsmom", tsmom_data, timeframe="intraday",
            reason_prefix="TSMOM",
        )

    def compute_oi_momentum(self, oi_momentum_data: Optional[Dict[str, Any]]) -> AlphaSignal:
        """Adapter for `OITracker.roc_zscore()` output (P1-5)."""
        return self._score_to_signal(
            "oi_momentum", oi_momentum_data, timeframe="intraday",
            reason_prefix="OI-momentum",
        )

    def compute_squeeze(self, squeeze_data: Optional[Dict[str, Any]]) -> AlphaSignal:
        """Adapter for `SqueezeRiskMeter.compute()` output (P1-A).

        SqueezeRiskMeter returns ``long_squeeze_risk_pct`` /
        ``short_squeeze_risk_pct`` on a 0-100 scale and a ``dominant_risk``
        side. We convert this into a *signed* alpha contribution: a higher
        long-squeeze risk is a bullish reversion impulse (over-shorted; the
        squeeze unwinds upward), and vice-versa. Output magnitude is the
        normalized risk; confidence comes from the meter's ``alert_level``.
        """
        if not isinstance(squeeze_data, dict):
            return self._score_to_signal("squeeze", None, timeframe="intraday")
        long_risk = float(squeeze_data.get("long_squeeze_risk_pct") or 0.0)
        short_risk = float(squeeze_data.get("short_squeeze_risk_pct") or 0.0)
        dominant = squeeze_data.get("dominant_risk") or "balanced"
        # Convert to [-1, +1]: long_risk → bullish (+); short_risk → bearish (-).
        # Net = (long − short) / 100, clipped.
        net = max(-1.0, min(1.0, (long_risk - short_risk) / 100.0))
        alert = squeeze_data.get("alert_level") or "normal"
        conf = {"critical": 0.90, "elevated": 0.65, "normal": 0.30}.get(alert, 0.30)
        adapted = {
            "score": net,
            "confidence": conf,
            "reasoning": (
                f"Squeeze {dominant} · long_risk={long_risk:.0f}% short_risk={short_risk:.0f}% "
                f"(alert={alert})"
            ),
        }
        return self._score_to_signal(
            "squeeze", adapted, timeframe="intraday", reason_prefix="Squeeze",
        )

    # ==================================================================
    # 10. Composite Alpha Score
    # ==================================================================

    def generate_composite(
        self,
        funding_data: Optional[dict] = None,
        all_exchange_data: Optional[dict] = None,
        oi_data: Optional[dict] = None,
        cvd_data: Optional[dict] = None,
        deribit_data: Optional[dict] = None,
        klines: Optional[List[Dict[str, Any]]] = None,
        *,
        funding_carry_data: Optional[Dict[str, Any]] = None,
        tsmom_data: Optional[Dict[str, Any]] = None,
        oi_momentum_data: Optional[Dict[str, Any]] = None,
        squeeze_data: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        Compute all individual signals and combine into a single composite.

        If *klines* is provided, the regime classifier is invoked to select a
        regime-conditional weight profile (P0-1). Without klines, the last
        known regime's weights are reused so the composite stays stable across
        calls.

        Returns:
        {
            "symbol": str,
            "composite_score": float,     # -100 to +100 (positive = bullish)
            "composite_direction": str,
            "composite_confidence": float,
            "regime": {...},              # active regime + confidence
            "weights_used": {...},        # factor weights actually applied
            "signals": [AlphaSignal.to_dict(), ...],
            "timestamp": float,
        }
        """
        try:
            signals: list[AlphaSignal] = [
                self.compute_ofi(),
                self.compute_vwap_deviation(),
                self.compute_funding_arb(funding_data),
                self.compute_cross_exchange_spread(all_exchange_data),
                self.compute_liquidation_cascade(oi_data, funding_data),
                self.compute_delta_divergence(cvd_data),
                self.compute_smart_money_flow(),
                self.compute_vol_regime(deribit_data),
                # P1 factors - weighted zero under `insufficient_data`, so
                # safe to always append.
                self.compute_funding_carry(funding_carry_data),
                self.compute_tsmom(tsmom_data),
                self.compute_oi_momentum(oi_momentum_data),
                # P1-A squeeze: regime-aware via WEIGHTS_BY_REGIME["squeeze"].
                # Weighted zero under `insufficient_data`, so always safe.
                self.compute_squeeze(squeeze_data),
            ]
        except Exception:
            logger.exception("Error computing individual signals for %s", self.symbol)
            return {
                "symbol": self.symbol,
                "composite_score": 0.0,
                "composite_direction": "neutral",
                "composite_confidence": 0.0,
                "signals": [],
                "error": "Signal computation failed",
                "timestamp": time.time(),
            }

        # Regime-conditional weight selection (P0-1).
        regime_info = self._classify_regime(klines)
        regime_label = regime_info.get("regime", "insufficient_data")
        weights = self._select_weights(regime_label)
        # Keep self._weights in sync so read-only inspectors observe truth.
        self._weights = dict(weights)

        # Build weighted composite: convert direction + strength to signed value
        weighted_sum = 0.0
        weight_total = 0.0
        confidence_weighted_sum = 0.0

        for sig in signals:
            w = weights.get(sig.name, 0.0)
            if w <= 0:
                continue

            # Convert to signed strength [-100, 100]
            if sig.direction == "long":
                signed = sig.strength
            elif sig.direction == "short":
                signed = -sig.strength
            else:
                signed = 0.0

            # Weight by both the regime-selected weight and signal confidence
            effective_weight = w * sig.confidence
            weighted_sum += signed * effective_weight
            weight_total += effective_weight
            confidence_weighted_sum += sig.confidence * w

        if weight_total > 0:
            composite_score = weighted_sum / weight_total
        else:
            composite_score = 0.0

        composite_score = _clamp(composite_score, -100.0, 100.0)
        composite_confidence = _clamp(confidence_weighted_sum, 0.0, 1.0)

        if composite_score > 10:
            composite_direction = "long"
        elif composite_score < -10:
            composite_direction = "short"
        else:
            composite_direction = "neutral"

        result = {
            "symbol": self.symbol,
            "composite_score": round(composite_score, 2),
            "composite_direction": composite_direction,
            "composite_confidence": round(composite_confidence, 3),
            "regime": regime_info,
            "weights_used": {k: round(v, 4) for k, v in weights.items()},
            "signals": [s.to_dict() for s in signals],
            "signal_count": len(signals),
            "agreement_ratio": self._compute_agreement(signals),
            "timestamp": time.time(),
        }

        self._last_composite = result
        return result

    @staticmethod
    def _compute_agreement(signals: list[AlphaSignal]) -> float:
        """Fraction of non-neutral signals that agree on direction."""
        directional = [s for s in signals if s.direction != "neutral" and s.strength > 5]
        if not directional:
            return 0.0
        longs = sum(1 for s in directional if s.direction == "long")
        shorts = len(directional) - longs
        majority = max(longs, shorts)
        return round(majority / len(directional), 3)
