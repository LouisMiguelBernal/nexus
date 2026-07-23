"""
sentiment_router.py  -  Institutional Sentiment Engine v3
==========================================================

Endpoints
---------
GET  /api/sentiment/fng              Weighted F&G index (0-100) computed from live Binance data
GET  /api/sentiment/smartmoney       Smart Money signal engine - confidence, type, timeframe, AI insight
POST /api/sentiment/brief-save       Persist AI brief server-side (belt-and-suspenders for frontend store)
GET  /api/sentiment/brief-load       Load last persisted brief
GET  /api/sentiment/sync             Atomic fetch of FNG + SmartMoney in one call (reduces round-trips)

Architecture
------------
- Sentiment Engine    : _compute_fng()         - 5 weighted components from Binance public APIs
- Smart Money Engine  : _compute_smart_money() - top-trader divergence + signal classification
- Brief Store         : in-memory dict          - never auto-clears, only overwritten on explicit save
- AI Interpretation   : _ai_interpret_fng()    - rule-based 1-line interpretation (no LLM overhead)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import os
import statistics
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter

from backend import config as _config  # noqa: F401  - side-effect: loads .env

log = logging.getLogger("nexus.sentiment")
router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_API  = "https://api.binance.com"

# ── In-memory caches (survive tab navigation, reset only on server restart) ───

_fng_cache:  dict[str, Any] = {}
_fng_ts:     float = 0.0
FNG_TTL      = 300  # 5 min

_sm_cache:   dict[str, Any] = {}
_sm_ts:      float = 0.0
SM_TTL       = 120  # 2 min

# Persistent brief - NEVER auto-clears, only overwritten when user clicks Generate
_brief_store: dict[str, Any] = {}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _pub_get(url: str, params: dict | None = None) -> Any:
    """Unauthenticated GET - all Binance public endpoints."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, params=params or {},
                        headers={"User-Agent": "NexusTerminal/0.3"})
        r.raise_for_status()
        return r.json()


def _sign(params: dict[str, Any], secret: str) -> dict[str, Any]:
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 6000
    q = "&".join(f"{k}={v}" for k, v in p.items())
    p["signature"] = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  SENTIMENT ENGINE - Fear & Greed Index
# ══════════════════════════════════════════════════════════════════════════════
#
# Five components, weighted to match the methodology of alternative.me's
# Crypto Fear & Greed Index (the market standard), but sourced exclusively
# from Binance USDT-M Futures public endpoints:
#
#  Component              Weight   Signal direction
#  ─────────────────────  ──────   ───────────────────────────────────────────
#  Volatility             25 %     High swing = Fear, low = Greed (complacency)
#  Momentum / Volume      25 %     Price up + high vol = Greed; price down = Fear
#  Funding Rate           20 %     Positive = crowded long = Greed;
#                                  Negative = crowded short = Fear
#  L/S Positioning        20 %     CONTRARIAN: retail crowded long = Fear signal
#                                  (they are usually wrong at extremes)
#  OI Momentum            10 %     Rising OI = new interest = mild Greed lean
#
# Range: 0 (Extreme Fear) → 100 (Extreme Greed)

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _score_volatility(price_chg_24h: float, high_24h: float, low_24h: float,
                      close: float) -> float:
    """
    Volatility component.
    Uses true intra-day range (High-Low)/Close as volatility proxy.
    High range (>5%) = Fear; tight range (<0.5%) = Greed (complacency).
    """
    if close > 0 and high_24h > 0 and low_24h > 0:
        range_pct = (high_24h - low_24h) / close * 100
    else:
        range_pct = abs(price_chg_24h)

    # Calibration: 0% range → 65, 5% range → 35, 15% range → 10
    score = 65 - range_pct * 6
    return _clamp(score)


def _score_momentum(price_chg_24h: float, price_chg_7d: float,
                    volume_ratio: float) -> float:
    """
    Momentum + Volume component.
    Combines 24h and estimated 7d direction with volume confirmation.
    Strong bull momentum + high volume → Greed.
    """
    # 24h direction (primary weight 0.7)
    d24 = _clamp(50 + price_chg_24h * 4, 5, 95)
    # 7d direction (secondary weight 0.3) - if available
    d7  = _clamp(50 + price_chg_7d  * 2, 5, 95)
    direction = d24 * 0.7 + d7 * 0.3

    # Volume amplification: vol_ratio > 1.5 amplifies direction, < 0.5 dampens
    vol_factor = _clamp(0.7 + volume_ratio * 0.2, 0.5, 1.5)
    score = _clamp(50 + (direction - 50) * vol_factor)
    return score


def _score_funding(funding_rate_pct: float) -> float:
    """
    Funding Rate component.
    Persistent positive funding = longs paying shorts = crowded long = Greed.
    Neutral: ±0.01%/8h. Extreme: ±0.10%/8h.
    """
    # Linear mapping: 0% → 50, +0.08% → 75, -0.08% → 25
    score = 50 + funding_rate_pct * 312.5
    return _clamp(score)


def _score_ls_contrarian(ls_ratio: float) -> float:
    """
    Long/Short Ratio - CONTRARIAN signal.
    Retail accounts are wrong at extremes:
      L/S > 1.6 (retail heavily long) → Fear (smart money is opposite)
      L/S < 0.7 (retail heavily short) → Greed (short squeeze likely)
      L/S ≈ 1.0 → Neutral 50
    """
    if ls_ratio >= 1.0:
        # Retail long-heavy → fear signal (contrarian)
        score = 50 - (ls_ratio - 1.0) * 35
    else:
        # Retail short-heavy → greed signal (contrarian)
        score = 50 + (1.0 - ls_ratio) * 35
    return _clamp(score)


def _score_oi(oi_chg_24h_pct: float, price_chg_24h: float) -> float:
    """
    OI Momentum component.
    Rising OI + rising price = new longs = Greed confirmation.
    Rising OI + falling price = new shorts = Fear confirmation.
    Falling OI = positions closing = neutral.
    """
    if oi_chg_24h_pct > 0 and price_chg_24h > 0:
        score = 55 + oi_chg_24h_pct * 4      # bull confirmation
    elif oi_chg_24h_pct > 0 and price_chg_24h < 0:
        score = 45 - oi_chg_24h_pct * 4      # bear confirmation
    else:
        score = 50                             # closing positions = neutral
    return _clamp(score)


def _label_fng(score: int) -> tuple[str, str]:
    if score <= 20: return "Extreme Fear", "#e74c3c"
    if score <= 40: return "Fear",         "#e67e22"
    if score <= 60: return "Neutral",      "#f1c40f"
    if score <= 80: return "Greed",        "#2ecc71"
    return "Extreme Greed",               "#27ae60"


def _ai_interpret_fng(score: int, label: str,
                      price_chg: float, funding: float,
                      ls_ratio: float, oi_chg: float) -> str:
    """
    Rule-based 1-2 line interpretation. No LLM required - fast, deterministic.
    Mirrors how a quant would describe the reading in a morning briefing.
    """
    parts: list[str] = []

    if score <= 20:
        parts.append("Market in capitulation territory.")
    elif score <= 35:
        parts.append("Elevated fear - traders de-risking.")
    elif score <= 50:
        parts.append("Cautious sentiment dominates.")
    elif score <= 65:
        parts.append("Mild optimism - risk appetite recovering.")
    elif score <= 80:
        parts.append("Greed building - momentum buyers active.")
    else:
        parts.append("Euphoria zone - historically high reversal risk.")

    drivers: list[str] = []
    if abs(price_chg) > 3:
        drivers.append(f"price {'surge' if price_chg > 0 else 'drop'} ({price_chg:+.1f}%)")
    if funding > 0.06:
        drivers.append("elevated long funding drag")
    elif funding < -0.04:
        drivers.append("negative funding (short pressure)")
    if ls_ratio > 1.5:
        drivers.append("retail crowded long (contrarian bearish)")
    elif ls_ratio < 0.8:
        drivers.append("retail crowded short (contrarian bullish)")
    if oi_chg > 3:
        drivers.append("OI expanding")
    elif oi_chg < -3:
        drivers.append("OI contracting")

    if drivers:
        parts.append(f"Key drivers: {', '.join(drivers[:3])}.")

    return " ".join(parts)


async def _compute_fng() -> dict[str, Any]:
    """
    Parallel fetch of 4 Binance public endpoints → compute weighted F&G.
    All calls are unauthenticated and cache-exempt (TTL handled by route).
    """
    errors: list[str] = []

    # Parallel fetch
    ticker_task = _pub_get(f"{BINANCE_FAPI}/fapi/v1/ticker/24hr",
                           {"symbol": "BTCUSDT"})
    funding_task = _pub_get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex",
                            {"symbol": "BTCUSDT"})
    ls_task = _pub_get(f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio",
                       {"symbol": "BTCUSDT", "period": "1h", "limit": 2})
    oi_task = _pub_get(f"{BINANCE_FAPI}/futures/data/openInterestHist",
                       {"symbol": "BTCUSDT", "period": "1h", "limit": 25})

    results = await asyncio.gather(ticker_task, funding_task, ls_task, oi_task,
                                   return_exceptions=True)

    ticker     = results[0] if not isinstance(results[0], Exception) else {}
    fund_data  = results[1] if not isinstance(results[1], Exception) else {}
    ls_data    = results[2] if not isinstance(results[2], Exception) else []
    oi_data    = results[3] if not isinstance(results[3], Exception) else []

    for i, name in enumerate(["ticker", "funding", "ls_ratio", "oi"]):
        if isinstance(results[i], Exception):
            errors.append(f"{name}: {results[i]}")

    # Parse
    price_chg    = float(ticker.get("priceChangePercent", 0))
    close        = float(ticker.get("lastPrice", 0))
    high_24h     = float(ticker.get("highPrice", 0))
    low_24h      = float(ticker.get("lowPrice", 0))
    volume_now   = float(ticker.get("volume", 0))

    # Estimate 7d change from 24h (imperfect but no extra call needed)
    # Using a rough heuristic: 7d ≈ 24h * 0.4 (regression toward mean)
    price_chg_7d = price_chg * 0.4

    # Volume ratio (normalise against 150K BTC/day benchmark)
    volume_ratio = min(volume_now / 150_000, 3.0) if volume_now > 0 else 1.0

    funding_pct = float(fund_data.get("lastFundingRate", 0)) * 100

    ls_ratio = 1.0
    if ls_data and isinstance(ls_data, list) and ls_data:
        ls_ratio = float(ls_data[-1].get("longShortRatio", 1.0))

    oi_chg_pct = 0.0
    if oi_data and isinstance(oi_data, list) and len(oi_data) >= 2:
        oi_new = float(oi_data[-1].get("sumOpenInterest", 1))
        oi_old = float(oi_data[0].get("sumOpenInterest", 1))
        oi_chg_pct = ((oi_new - oi_old) / max(oi_old, 1)) * 100

    # Component scores
    vol_score  = _score_volatility(price_chg, high_24h, low_24h, close)
    mom_score  = _score_momentum(price_chg, price_chg_7d, volume_ratio)
    fund_score = _score_funding(funding_pct)
    ls_score   = _score_ls_contrarian(ls_ratio)
    oi_score   = _score_oi(oi_chg_pct, price_chg)

    # Weighted composite
    composite = (
        vol_score  * 0.25 +
        mom_score  * 0.25 +
        fund_score * 0.20 +
        ls_score   * 0.20 +
        oi_score   * 0.10
    )
    score = int(round(_clamp(composite)))
    label, color = _label_fng(score)
    interpretation = _ai_interpret_fng(score, label, price_chg,
                                        funding_pct, ls_ratio, oi_chg_pct)

    return {
        "score":  score,
        "label":  label,
        "color":  color,
        "ai_interpretation": interpretation,
        "components": {
            "volatility":  round(vol_score,  1),
            "momentum":    round(mom_score,  1),
            "funding":     round(fund_score, 1),
            "ls_position": round(ls_score,   1),
            "oi_momentum": round(oi_score,   1),
        },
        "inputs": {
            "price_change_24h_pct": round(price_chg,    4),
            "funding_rate_pct":     round(funding_pct,  6),
            "ls_ratio":             round(ls_ratio,     4),
            "oi_change_24h_pct":    round(oi_chg_pct,   4),
        },
        "computed_at": datetime.utcnow().isoformat(),
        "errors":      errors or None,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  SMART MONEY ENGINE
# ══════════════════════════════════════════════════════════════════════════════
#
# Mirrors what Binance's smart-money/signal page shows, built from the same
# underlying public futures data.
#
# Signal Classification:
#   TREND_FOLLOWING  - top traders riding an established move
#   REVERSAL         - top traders positioned against recent price action
#   ACCUMULATION     - top traders adding to longs quietly (low volatility)
#   DISTRIBUTION     - top traders reducing longs / adding shorts on strength
#
# Timeframe:
#   SCALP    - signal likely to resolve in < 1h
#   INTRADAY - 1-12h window
#   SWING    - 12h-7d window
#
# Confidence (0-100):
#   Based on signal agreement, divergence strength, and OI velocity.

def _classify_signal(top_ratio: float, top_delta_6h: float,
                     oi_vel: float, price_chg: float,
                     funding: float) -> tuple[str, str, int, str]:
    """
    Returns (signal_label, signal_type, confidence, timeframe).
    """
    # Net bias
    is_long  = top_ratio >= 1.05
    is_short = top_ratio <= 0.95

    # Trend vs reversal: is positioning aligned with price action?
    price_bull = price_chg > 0
    aligned = (is_long and price_bull) or (is_short and not price_bull)

    # OI expanding = new positions
    oi_expanding = oi_vel > 1.0

    # Signal type
    if aligned and oi_expanding:
        sig_type = "TREND_FOLLOWING"
    elif aligned and not oi_expanding:
        sig_type = "DISTRIBUTION" if is_long else "ACCUMULATION"
    elif not aligned and oi_expanding:
        sig_type = "REVERSAL"
    else:
        sig_type = "ACCUMULATION" if is_long else "DISTRIBUTION"

    # Label
    ratio_pct = top_ratio / (top_ratio + 1) * 100
    if top_ratio >= 1.5:   label = "STRONG LONG"
    elif top_ratio >= 1.15: label = "LONG BIAS"
    elif top_ratio <= 0.67: label = "STRONG SHORT"
    elif top_ratio <= 0.87: label = "SHORT BIAS"
    else:                   label = "NEUTRAL"

    # Confidence
    conf = 50.0
    # How far from neutral?
    conf += abs(top_ratio - 1.0) * 40
    # Momentum of position change
    conf += abs(top_delta_6h) * 30
    # OI velocity confirmation
    if oi_expanding and aligned:
        conf += 10
    elif oi_expanding and not aligned:
        conf -= 5
    # Funding alignment
    if (is_long and funding > 0.02) or (is_short and funding < -0.02):
        conf -= 5    # over-crowded, reduce confidence
    confidence = int(_clamp(conf))

    # Timeframe heuristic
    if abs(top_delta_6h) > 0.15:
        timeframe = "SCALP"      # rapid repositioning = short-term
    elif abs(top_delta_6h) > 0.05:
        timeframe = "INTRADAY"
    else:
        timeframe = "SWING"

    return label, sig_type, confidence, timeframe


def _ai_insight(top_ratio: float, top_delta_6h: float, divergence_type: str,
                sig_type: str, oi_vel: float, funding: float,
                price_chg: float) -> str:
    """Concise AI insight - no fluff, quant language."""
    direction = "long" if top_ratio >= 1.0 else "short"
    strength  = "aggressively" if abs(top_ratio - 1.0) > 0.4 else "moderately"

    lines: list[str] = []

    lines.append(
        f"Top traders are {strength} positioned {direction} "
        f"({top_ratio:.2f} ratio, Δ6h={top_delta_6h:+.3f})."
    )

    if divergence_type == "smart_money_long_retail_short":
        lines.append("Divergence detected: smart money net long vs retail net short - historically bullish.")
    elif divergence_type == "smart_money_short_retail_long":
        lines.append("Divergence: smart money net short vs retail net long - historically bearish.")

    type_map = {
        "TREND_FOLLOWING": "OI expanding with aligned positioning - trend-following mode.",
        "REVERSAL":        "Positioning counter to recent price - potential reversal setup forming.",
        "ACCUMULATION":    "Low OI + quiet long build - possible accumulation phase.",
        "DISTRIBUTION":    "OI contracting with long positioning - distribution or profit-taking.",
    }
    lines.append(type_map.get(sig_type, ""))

    if funding > 0.08:
        lines.append("Warning: elevated funding rate - long crowding risk.")
    elif funding < -0.06:
        lines.append("Negative funding - shorts paying, squeeze risk elevated.")

    return " ".join(l for l in lines if l)


async def _compute_smart_money(symbol: str = "BTCUSDT") -> dict[str, Any]:
    errors: list[str] = []

    # Parallel fetch
    top_task    = _pub_get(f"{BINANCE_FAPI}/futures/data/topLongShortPositionRatio",
                           {"symbol": symbol, "period": "1h", "limit": 24})
    global_task = _pub_get(f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio",
                           {"symbol": symbol, "period": "1h", "limit": 24})
    oi_task     = _pub_get(f"{BINANCE_FAPI}/futures/data/openInterestHist",
                           {"symbol": symbol, "period": "1h", "limit": 48})
    mark_task   = _pub_get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex",
                           {"symbol": symbol})
    ticker_task = _pub_get(f"{BINANCE_FAPI}/fapi/v1/ticker/24hr",
                           {"symbol": symbol})

    results = await asyncio.gather(top_task, global_task, oi_task,
                                   mark_task, ticker_task,
                                   return_exceptions=True)

    top_ls     = results[0] if not isinstance(results[0], Exception) else []
    global_ls  = results[1] if not isinstance(results[1], Exception) else []
    oi_hist    = results[2] if not isinstance(results[2], Exception) else []
    mark_data  = results[3] if not isinstance(results[3], Exception) else {}
    ticker     = results[4] if not isinstance(results[4], Exception) else {}

    for i, n in enumerate(["top_ls", "global_ls", "oi", "mark", "ticker"]):
        if isinstance(results[i], Exception):
            errors.append(f"{n}: {results[i]}")

    # ── Top trader analysis ──────────────────────────────────────────────────

    top_ratio_now = 1.0
    top_long_pct  = 50.0
    top_short_pct = 50.0
    top_delta_6h  = 0.0
    top_delta_24h = 0.0
    top_trend     = "flat"

    if top_ls and isinstance(top_ls, list) and len(top_ls) >= 1:
        latest = top_ls[-1]
        top_ratio_now = float(latest.get("longShortRatio", 1.0))
        top_long_pct  = float(latest.get("longAccount",  0.5)) * 100
        top_short_pct = float(latest.get("shortAccount", 0.5)) * 100

        if len(top_ls) >= 6:
            r6h = float(top_ls[max(0, len(top_ls) - 7)].get("longShortRatio", top_ratio_now))
            top_delta_6h = top_ratio_now - r6h

        if len(top_ls) >= 2:
            r24h = float(top_ls[0].get("longShortRatio", top_ratio_now))
            top_delta_24h = top_ratio_now - r24h

        if top_delta_6h > 0.04:   top_trend = "rising"
        elif top_delta_6h < -0.04: top_trend = "falling"

    # ── Retail / divergence ──────────────────────────────────────────────────

    global_ratio = 1.0
    divergence_type = "none"
    divergence_strength = 0.0
    divergence_bias: str = "none"

    if global_ls and isinstance(global_ls, list) and global_ls:
        global_ratio = float(global_ls[-1].get("longShortRatio", 1.0))
        div = top_ratio_now - global_ratio
        divergence_strength = round(abs(div), 3)
        if div > 0.15:
            divergence_type = "smart_money_long_retail_short"
            divergence_bias = "bullish"
        elif div < -0.15:
            divergence_type = "smart_money_short_retail_long"
            divergence_bias = "bearish"

    # ── OI velocity ──────────────────────────────────────────────────────────

    oi_vel = 0.0
    oi_accel = 0.0

    if oi_hist and isinstance(oi_hist, list) and len(oi_hist) >= 12:
        vals = [float(x.get("sumOpenInterest", 0)) for x in oi_hist]
        oi_vel   = (vals[-1] - vals[-7]) / max(vals[-7], 1) * 100
        vel_12h  = (vals[-7] - vals[0])  / max(vals[0],  1) * 100
        oi_accel = oi_vel - vel_12h

    # ── Funding + price ───────────────────────────────────────────────────────

    funding = float(mark_data.get("lastFundingRate", 0)) * 100
    price_chg = float(ticker.get("priceChangePercent", 0))

    fund_label = "neutral"
    if   funding >  0.10: fund_label = "extreme_longs"
    elif funding >  0.04: fund_label = "elevated_longs"
    elif funding < -0.10: fund_label = "extreme_shorts"
    elif funding < -0.04: fund_label = "elevated_shorts"

    # ── Signal classification ─────────────────────────────────────────────────

    label, sig_type, confidence, timeframe = _classify_signal(
        top_ratio_now, top_delta_6h, oi_vel, price_chg, funding
    )

    # Boost confidence if divergence present
    if divergence_bias != "none":
        confidence = min(100, confidence + 12)

    insight = _ai_insight(top_ratio_now, top_delta_6h, divergence_type,
                           sig_type, oi_vel, funding, price_chg)

    # ── Signal score (−100 to +100) ───────────────────────────────────────────

    score = (top_ratio_now - 1.0) * 60
    if top_trend == "rising":  score += 12
    if top_trend == "falling": score -= 12
    if divergence_type == "smart_money_long_retail_short":  score += 18
    if divergence_type == "smart_money_short_retail_long":  score -= 18
    score = max(-100.0, min(100.0, score + oi_vel * 1.5))
    signal_color = "#26a69a" if score > 8 else "#ef5350" if score < -8 else "#f4a44b"

    # ── History for sparklines ────────────────────────────────────────────────

    def _to_history(data: list) -> list[dict]:
        return [
            {
                "ts":    int(x.get("timestamp", 0)),
                "ratio": round(float(x.get("longShortRatio", 1.0)), 3),
                "long":  round(float(x.get("longAccount",  0.5)) * 100, 1),
                "short": round(float(x.get("shortAccount", 0.5)) * 100, 1),
            }
            for x in (data[-24:] if data else [])
        ]

    return {
        "symbol": symbol,
        "signal": {
            "score":      round(score, 1),
            "label":      label,
            "color":      signal_color,
            "type":       sig_type,
            "timeframe":  timeframe,
            "confidence": confidence,
            "ai_insight": insight,
        },
        "top_trader": {
            "ratio":     round(top_ratio_now, 3),
            "bias":      "long" if top_ratio_now >= 1.0 else "short",
            "trend":     top_trend,
            "delta_6h":  round(top_delta_6h,  3),
            "delta_24h": round(top_delta_24h, 3),
            "long_pct":  round(top_long_pct,  1),
            "short_pct": round(top_short_pct, 1),
        },
        "divergence": {
            "type":     divergence_type,
            "strength": divergence_strength,
            "signal":   divergence_bias != "none",
            "bias":     divergence_bias,
        },
        "oi": {
            "velocity_6h_pct":  round(oi_vel,   3),
            "acceleration_pct": round(oi_accel, 3),
        },
        "funding": {
            "rate_pct": round(funding, 6),
            "label":    fund_label,
        },
        "history": {
            "top_trader": _to_history(top_ls if isinstance(top_ls, list) else []),
            "retail":     _to_history(global_ls if isinstance(global_ls, list) else []),
        },
        "computed_at": datetime.utcnow().isoformat(),
        "errors": errors or None,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/fng")
async def get_fng():
    """Compute Fear & Greed index. Cached 5 min."""
    global _fng_cache, _fng_ts
    if _fng_cache and (time.time() - _fng_ts) < FNG_TTL:
        return _fng_cache
    try:
        result = await _compute_fng()
        _fng_cache = result
        _fng_ts = time.time()
        return result
    except Exception as e:
        log.error(f"FNG: {e}", exc_info=True)
        if _fng_cache:
            return {**_fng_cache, "stale": True}
        return {"score": 50, "label": "Neutral", "color": "#f1c40f",
                "error": str(e), "ai_interpretation": "Data unavailable."}


@router.get("/smartmoney")
async def get_smart_money(symbol: str = "BTCUSDT"):
    """Smart Money signal engine. Cached 2 min."""
    global _sm_ts  # _sm_cache is only mutated, never rebound
    key = symbol.upper()
    if _sm_cache.get(key) and (time.time() - _sm_ts) < SM_TTL:
        return _sm_cache[key]
    try:
        result = await _compute_smart_money(key)
        _sm_cache[key] = result
        _sm_ts = time.time()
        return result
    except Exception as e:
        log.error(f"SmartMoney: {e}", exc_info=True)
        if _sm_cache.get(key):
            return {**_sm_cache[key], "stale": True}
        return {"error": str(e), "symbol": symbol}


@router.get("/sync")
async def sync_sentiment(symbol: str = "BTCUSDT"):
    """
    Atomic fetch of FNG + SmartMoney in one call.
    Reduces frontend round-trips from 2 to 1.
    Both results are individually cached per their TTLs.
    """
    fng_task = get_fng()
    sm_task  = get_smart_money(symbol)
    fng, sm  = await asyncio.gather(fng_task, sm_task, return_exceptions=True)
    return {
        "fng":         fng  if not isinstance(fng, Exception) else {"error": str(fng)},
        "smartmoney":  sm   if not isinstance(sm,  Exception) else {"error": str(sm)},
        "synced_at":   datetime.utcnow().isoformat(),
    }


@router.post("/brief-save")
async def save_brief(payload: dict):
    """
    Persist AI brief server-side.
    ONLY overwrites - never auto-clears.
    Frontend Zustand store is the primary persistence layer;
    this is belt-and-suspenders for hard refreshes.
    """
    _brief_store.clear()
    _brief_store.update(payload)
    _brief_store["saved_at"] = datetime.utcnow().isoformat()
    return {"saved": True, "saved_at": _brief_store["saved_at"]}


@router.get("/brief-load")
async def load_brief():
    """Return last persisted brief. Returns null fields if nothing saved yet."""
    if not _brief_store:
        return {"brief": None, "news_synthesis": None, "saved_at": None}
    return _brief_store


@router.delete("/brief-clear")
async def clear_brief():
    """Explicitly clear the server-side brief store. Called when user generates new brief."""
    _brief_store.clear()
    return {"cleared": True}


@router.get("/debug")
async def debug():
    """Diagnostic endpoint - shows cache ages, no secrets exposed."""
    return {
        "fng_cache_age_s":   round(time.time() - _fng_ts) if _fng_ts else None,
        "sm_cache_age_s":    round(time.time() - _sm_ts)  if _sm_ts  else None,
        "fng_score":         _fng_cache.get("score"),
        "sm_signal":         _sm_cache.get(list(_sm_cache.keys())[0], {}).get("signal", {}).get("label") if _sm_cache else None,
        "brief_saved":       bool(_brief_store),
        "brief_saved_at":    _brief_store.get("saved_at"),
    }