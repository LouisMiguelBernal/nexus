"""
Nexus - Unified /api/matrix/{symbol} endpoint.

Single envelope replacing the four legacy fan-out fetches the frontend used
to make every 30 s. Aggregates:

- Composite score + verdict + confidence/agreement
- 7 layers (trend / flow / oi / basis / vol / liq / dealer)
- Regime breakdown (label + Hurst + entropy)
- Order flow detail (CVD multi-TF, flow ratio, absorption, VPIN)
- Risk (VaR ensemble + ES + liquidation proximity)
- Research (basis, funding, GEX proxy, dealer skew)
- Per-venue health (latency, staleness, healthy bool)

Designed so the frontend can mount a single `useSWR("/api/matrix/{sym}")`
hook and bind the entire MatrixPanel from one snapshot.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from backend.computation import matrix_score
from backend.computation.entropy import entropy_score, sign_entropy
from backend.computation.fallbacks import (
    Inferred, absent, direct, infer_gex_proxy, proxy,
)
from backend.computation.hurst import hurst_exponent, hurst_score
from backend.risk.expected_shortfall import ESCalculator

logger = logging.getLogger("nexus.api.matrix")

router = APIRouter(prefix="/api", tags=["matrix"])

_es_calculator = ESCalculator()


# ---------------------------------------------------------------------------
# Helpers - compute per-layer inputs from app-level state
# ---------------------------------------------------------------------------

def _safe_get(d: Optional[dict], *keys, default=None):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def _z_from_series(series: list[float], current: Optional[float]) -> Optional[float]:
    if current is None or len(series) < 8:
        return None
    import statistics as _s
    try:
        mu = _s.mean(series)
        sd = _s.pstdev(series) or 1e-9
        return (current - mu) / sd
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Endpoint factory - main.py mounts the router with bound state
# ---------------------------------------------------------------------------

def make_router(*, state) -> APIRouter:
    """Build the matrix router bound to a state object exposing:

    - state.cvd_computers, state.oi_trackers, state.funding_trackers,
      state.absorption_detectors, state.obi_trackers, state.liq_aggregators,
      state.vpin_trackers, state.alpha_engines, state.regime_classifier,
      state.var_calculator, state.binance_data, state.deribit_feed,
      state.ws_manager
    - state.ensure_engines(symbol)
    """

    # Response cache + single-flight. The frontend polls this route every 4s;
    # without these, overlapping polls each re-await Deribit/funding upstream
    # and the loop backlog snowballs (observed 25s responses → "nothing loads").
    _resp_cache: Dict[str, tuple[float, Dict]] = {}
    _locks: Dict[str, asyncio.Lock] = {}
    _RESP_TTL_S = 4.0

    # Deribit aggregates change slowly (options OI / DVOL) - 60s cache, and the
    # three calls run concurrently with a hard per-call timeout so a slow
    # Deribit day can never stall the whole matrix.
    _deribit_cache: Dict[str, tuple[float, tuple]] = {}
    _DERIBIT_TTL_S = 60.0
    _DERIBIT_CALL_TIMEOUT_S = 5.0

    async def _deribit_aggregates(currency: str) -> tuple:
        now = time.time()
        hit = _deribit_cache.get(currency)
        if hit and now - hit[0] < _DERIBIT_TTL_S:
            return hit[1]

        async def _guard(coro):
            try:
                return await asyncio.wait_for(coro, timeout=_DERIBIT_CALL_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - timeout or venue error → degrade
                return None

        pcr, mp, dvol_payload = await asyncio.gather(
            _guard(state.deribit_feed.compute_put_call_ratio(currency)),
            _guard(state.deribit_feed.compute_max_pain(currency)),
            _guard(state.deribit_feed.get_dvol(currency=currency, hours=24)),
        )
        result = (pcr, mp, dvol_payload)
        # Only cache when at least one leg produced data - keep retrying fast
        # while Deribit is unreachable.
        if any(x for x in result):
            _deribit_cache[currency] = (now, result)
        return result

    @router.get("/matrix/{symbol}")
    async def get_matrix(symbol: str) -> Dict:
        sym = symbol.upper()

        now = time.time()
        hit = _resp_cache.get(sym)
        if hit and now - hit[0] < _RESP_TTL_S:
            return hit[1]
        lock = _locks.setdefault(sym, asyncio.Lock())
        async with lock:
            hit = _resp_cache.get(sym)
            if hit and time.time() - hit[0] < _RESP_TTL_S:
                return hit[1]
            payload = await _compute_matrix(sym)
            _resp_cache[sym] = (time.time(), payload)
            return payload

    async def _compute_matrix(sym: str) -> Dict:
        state.ensure_engines(sym)

        klines = list(state.binance_data.kline_history.get(sym, []))
        closes = [float(k.get("close", 0)) for k in klines if k.get("close")]
        returns = _log_returns(closes[-256:]) if closes else []

        # ------------------------------------------------------------------
        # Regime + Hurst + Entropy
        # ------------------------------------------------------------------
        regime_label = "unknown"
        regime_conf = 0.0
        try:
            if len(klines) >= 20:
                volumes = [float(k.get("volume", 0)) for k in klines]
                highs = [float(k.get("high", 0)) for k in klines]
                lows = [float(k.get("low", 0)) for k in klines]
                rd = state.regime_classifier.classify(closes, volumes, highs, lows)
                regime_label = rd.get("regime", "unknown")
                regime_conf = float(rd.get("confidence", 0.0) or 0.0)
        except Exception as exc:  # noqa: BLE001
            logger.debug("regime classify %s: %s", sym, exc)

        H = hurst_exponent(returns) if len(returns) >= 48 else None
        H_score = hurst_score(H)
        E = sign_entropy(returns[-64:]) if len(returns) >= 8 else None
        E_score = entropy_score(E)

        # ------------------------------------------------------------------
        # CVD / Flow / Absorption / VPIN
        # ------------------------------------------------------------------
        cvd = state.cvd_computers.get(sym)
        cvd_mtf = cvd.get_multi_timeframe() if cvd else {}

        # Strict null contract: cvd module now returns None when no trades.
        # We preserve null in the surfaced response (flow.cvd_*) AND avoid
        # producing spurious 0 z-scores for the flow layer.
        def _get_or_none(d: dict | None, k: str):
            v = (d or {}).get(k) if isinstance(d, dict) else None
            return v if isinstance(v, (int, float)) else None

        cvd_1h = _get_or_none(cvd_mtf.get("1h") if isinstance(cvd_mtf, dict) else None, "net_delta")
        cvd_1h_buy = _get_or_none(cvd_mtf.get("1h") if isinstance(cvd_mtf, dict) else None, "buy_volume")
        cvd_1h_sell = _get_or_none(cvd_mtf.get("1h") if isinstance(cvd_mtf, dict) else None, "sell_volume")
        cvd_total = ((cvd_1h_buy or 0.0) + (cvd_1h_sell or 0.0)) if (cvd_1h_buy is not None and cvd_1h_sell is not None) else 0.0
        cvd_z = ((cvd_1h or 0.0) / cvd_total) if cvd_total > 1e-6 else None
        flow_ratio = ((cvd_1h_buy or 0.0) / cvd_total) if cvd_total > 1e-6 else None

        # OBI snapshot + z-score: summary() exposes mean/std over a rolling
        # window, so we can z-score the latest reading vs its own distribution.
        # Dual notional + qty tracking (P1-6): expose both so the frontend can
        # compare large-price wall pressure against raw size pressure.
        obi_tracker = state.obi_trackers.get(sym)
        obi_val: Optional[float] = None
        obi_z: Optional[float] = None
        obi_bias: Optional[str] = None
        obi_qty_val: Optional[float] = None
        obi_qty_z: Optional[float] = None
        obi_qty_bias: Optional[str] = None
        try:
            if obi_tracker and hasattr(obi_tracker, "summary"):
                obi_summary = obi_tracker.summary(window=180)
                if isinstance(obi_summary, dict):
                    obi_val = obi_summary.get("latest")
                    obi_bias = obi_summary.get("bias")
                    mu = obi_summary.get("mean")
                    sd = obi_summary.get("std")
                    if (obi_val is not None and mu is not None and sd is not None
                            and isinstance(sd, (int, float)) and sd > 1e-6):
                        obi_z = (obi_val - mu) / sd
                    obi_qty_val = obi_summary.get("latest_qty")
                    obi_qty_bias = obi_summary.get("bias_qty")
                    qmu = obi_summary.get("mean_qty")
                    qsd = obi_summary.get("std_qty")
                    if (obi_qty_val is not None and qmu is not None and qsd is not None
                            and isinstance(qsd, (int, float)) and qsd > 1e-6):
                        obi_qty_z = (obi_qty_val - qmu) / qsd
        except Exception:  # noqa: BLE001
            obi_val = None
            obi_z = None
            obi_qty_val = None
            obi_qty_z = None

        # VPIN
        vpin_tracker = state.vpin_trackers.get(sym)
        vpin_val: Optional[float] = None
        try:
            if vpin_tracker:
                snap = vpin_tracker.snapshot()
                vpin_val = float(getattr(snap, "running", 0.0) or 0.0) or None
        except Exception:  # noqa: BLE001
            vpin_val = None

        # Absorption - read cached detector state
        det = state.absorption_detectors.get(sym) if hasattr(state, "absorption_detectors") else None
        absorption_state = {"detected": False, "side": "none", "strength": 0.0}
        if det is not None:
            last = getattr(det, "_last_result", None)
            if last:
                side = "bid" if last.get("type") == "bid_absorption" else "ask"
                absorption_state = {
                    "detected": True,
                    "side": side,
                    "strength": float(last.get("strength", 0.0) or 0.0),
                    "buy_sell_ratio": last.get("buy_sell_ratio"),
                    "volume_usd": last.get("total_volume_usd"),
                }

        # ------------------------------------------------------------------
        # OI / Funding
        # ------------------------------------------------------------------
        oi = state.oi_trackers.get(sym)
        oi_trend = oi.get_trend() if oi else {}
        oi_change_pct = float(oi_trend.get("change_pct", 0) or 0.0)
        oi_zscore_val = None
        try:
            if oi:
                roc = oi.roc_zscore(window="4h", baseline_window="7d")
                oi_zscore_val = float(roc.get("zscore", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            pass

        funding = state.funding_trackers.get(sym)
        funding_pct = None
        funding_persistence = None
        try:
            if funding:
                # In-memory read - the 30s oi_poll_loop keeps the tracker
                # fresh; re-fetching Binance+OKX REST per matrix poll was a
                # major contributor to the 25s cold responses.
                snap = funding._history[-1] if funding._history else None
                if isinstance(snap, dict):
                    funding_pct = float(snap.get("weighted_rate", 0.0) or 0.0) * 100.0
                    # Persistence: ratio of same-sign venues (when ≥3 venues).
                    venues = snap.get("venues") or {}
                    if isinstance(venues, dict) and len(venues) >= 2:
                        signs = [
                            (1 if (v or 0) > 0 else -1 if (v or 0) < 0 else 0)
                            for v in venues.values()
                        ]
                        nz = [s for s in signs if s != 0]
                        if nz:
                            same = sum(1 for s in nz if s == nz[0])
                            funding_persistence = (same / len(nz)) * 2 - 1.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("funding %s: %s", sym, exc)

        # ------------------------------------------------------------------
        # Basis: perp mark vs index. Cross-venue dispersion = stdev of
        # per-venue (mid - reference) % deviation, capturing "this venue is
        # paying a different premium than the others" → arb signal.
        # ------------------------------------------------------------------
        mark = state.binance_data.mark_prices.get(sym, {})
        mark_p = float(mark.get("mark_price", 0) or 0.0)
        index_p = float(mark.get("index_price", 0) or 0.0) or mark_p
        basis_pct = ((mark_p - index_p) / index_p * 100.0) if index_p > 0 else None

        # Cross-venue dispersion: pull mids from all WS-connected venues and
        # measure stdev of (mid_v - ref_mid) / ref_mid * 100.
        basis_dispersion: Optional[float] = None
        try:
            mids: list[float] = []
            for store_name in ("binance_data", "okx_data", "mexc_data"):
                pass  # placeholder - direct module lookup below
            # Use the venue stores directly via state.binance_data + globals
            from backend.ingestion.okx_ws import okx_data as _okx
            from backend.ingestion.mexc_ws import mexc_data as _mexc
            for venue_book in (
                state.binance_data.order_books.get(sym),
                _okx.order_books.get(sym),
                _mexc.order_books.get(sym),
            ):
                if not venue_book:
                    continue
                bids = venue_book.get("bids") or []
                asks = venue_book.get("asks") or []
                if not bids or not asks:
                    continue
                bb = float(bids[0][0]); ba = float(asks[0][0])
                if bb > 0 and ba > 0:
                    mids.append((bb + ba) / 2.0)
            if len(mids) >= 2:
                ref = sum(mids) / len(mids)
                if ref > 0:
                    devs_pct = [((m - ref) / ref * 100.0) for m in mids]
                    mu = sum(devs_pct) / len(devs_pct)
                    var = sum((x - mu) ** 2 for x in devs_pct) / max(len(devs_pct) - 1, 1)
                    basis_dispersion = math.sqrt(var)
        except Exception as exc:  # noqa: BLE001
            logger.debug("basis_dispersion %s: %s", sym, exc)

        # ------------------------------------------------------------------
        # Volatility - pull from /api/indicators latest path (we recompute
        # cheaply here from kline_history rather than dispatching that route).
        # ------------------------------------------------------------------
        bb_width_pct = None
        bb_width_avg = None
        atr_pct = None
        atr_avg = None
        try:
            if len(closes) >= 30:
                import numpy as _np
                arr = _np.asarray(closes[-50:], dtype=float)
                mid = arr.mean()
                sd = arr.std(ddof=0)
                bb_width_pct = (4 * sd / mid * 100) if mid > 0 else None
                # Rolling 20-period BB widths for baseline
                widths = []
                for i in range(20, len(closes)):
                    w = closes[i - 20:i]
                    mu = sum(w) / 20
                    s2 = sum((x - mu) ** 2 for x in w) / 20
                    s = math.sqrt(s2)
                    if mu > 0:
                        widths.append(4 * s / mu * 100)
                if widths:
                    bb_width_avg = sum(widths) / len(widths)
                # ATR proxy from realized volatility of returns (annualized → not needed here)
                if returns:
                    rv = (sum(r * r for r in returns[-20:]) / max(len(returns[-20:]), 1)) ** 0.5
                    atr_pct = rv * 100
                    rv_avg = (sum(r * r for r in returns) / len(returns)) ** 0.5
                    atr_avg = rv_avg * 100
        except Exception as exc:  # noqa: BLE001
            logger.debug("vol calc %s: %s", sym, exc)

        # ------------------------------------------------------------------
        # Liquidations
        # ------------------------------------------------------------------
        long_liq = None
        short_liq = None
        try:
            agg = state.liq_aggregators.get(sym)
            if agg and hasattr(agg, "imbalance"):
                im = agg.imbalance(window_seconds=600)
                long_liq = float(im.get("long_usd", 0) or 0.0)
                short_liq = float(im.get("short_usd", 0) or 0.0)
        except Exception:  # noqa: BLE001
            pass

        # ------------------------------------------------------------------
        # Dealer / GEX proxy via Deribit aggregates
        # ------------------------------------------------------------------
        gex_proxy_val: Optional[float] = None
        funding_skew_val: Optional[float] = None
        try:
            currency = "BTC" if sym.startswith("BTC") else "ETH" if sym.startswith("ETH") else None
            if currency and state.deribit_feed:
                # Concurrent + per-call timeout + 60s cache (options aggregates
                # move slowly). Was three serial uncached awaits per poll.
                pcr, mp, dvol_payload = await _deribit_aggregates(currency)
                dvol_latest = (dvol_payload or {}).get("latest")
                pcr_val = float((pcr or {}).get("ratio", 0) or 0.0) or None
                mp_strike = float((mp or {}).get("max_pain", 0) or 0.0) or None
                spot = mark_p or index_p
                mp_dist_pct = ((spot - mp_strike) / mp_strike * 100.0) if (spot and mp_strike) else None
                dvol_val = float(dvol_latest or 0.0) or None
                gx = infer_gex_proxy(pcr_val, dvol_val, mp_dist_pct)
                if gx.source != "none":
                    gex_proxy_val = gx.value
        except Exception as exc:  # noqa: BLE001
            logger.debug("deribit proxy %s: %s", sym, exc)

        # Funding term-structure skew (P1-1): front 1h annualized vs back 8h
        # realized 7d mean. Available only when ≥10 history samples - the
        # FundingTracker gates `available` itself; we propagate None below
        # that bar so the dealer layer downgrades confidence cleanly.
        funding_skew_payload: Optional[Dict[str, Any]] = None
        try:
            if funding:
                skew = funding.term_structure_skew()
                funding_skew_payload = skew
                if skew.get("available"):
                    funding_skew_val = skew.get("skew_pct")
        except Exception as exc:  # noqa: BLE001
            logger.debug("funding_skew %s: %s", sym, exc)

        # ------------------------------------------------------------------
        # Build layers
        # ------------------------------------------------------------------
        ema50_slope_pct = None
        adx = None
        try:
            if len(closes) >= 30:
                # Use simple slope of last 10 closes
                slope = (closes[-1] - closes[-10]) / closes[-10] * 100 / 10
                ema50_slope_pct = slope
        except Exception:  # noqa: BLE001
            pass

        layer_trend = matrix_score.layer_trend(
            ema50_slope_pct=ema50_slope_pct, adx=adx, hurst_signed=H_score,
        )
        # Use OBI z-score when available (more informative than raw level);
        # falls back to the raw OBI which is already in [-1,+1].
        obi_for_flow = obi_z if obi_z is not None else obi_val
        layer_flow = matrix_score.layer_flow(
            cvd_1h_z=cvd_z, obi=obi_for_flow, vpin=vpin_val, flow_ratio=flow_ratio,
        )
        layer_oi = matrix_score.layer_oi(
            oi_change_pct=oi_change_pct or None,
            funding_persistence=funding_persistence,
        )
        layer_basis = matrix_score.layer_basis(
            basis_pct=basis_pct, basis_dispersion=basis_dispersion,
        )
        layer_vol = matrix_score.layer_vol(
            bb_width_pct=bb_width_pct, bb_width_avg=bb_width_avg,
            atr_pct=atr_pct, atr_avg=atr_avg,
        )
        layer_liq = matrix_score.layer_liq(
            long_liq_usd=long_liq, short_liq_usd=short_liq, liq_vacuum=None,
        )
        layer_dealer = matrix_score.layer_dealer(
            gex_proxy=gex_proxy_val, funding_skew=funding_skew_val,
        )

        composite = matrix_score.assemble(
            {
                "trend":  layer_trend,
                "flow":   layer_flow,
                "oi":     layer_oi,
                "basis":  layer_basis,
                "vol":    layer_vol,
                "liq":    layer_liq,
                "dealer": layer_dealer,
            },
            regime=regime_label,
            venue_agreement_pct=100.0 * regime_conf if regime_conf else 50.0,
        )

        # ------------------------------------------------------------------
        # Risk: VaR + ES
        # ------------------------------------------------------------------
        risk_block: Dict[str, Any] = {
            "var_ens": None, "var_stressed": None, "es_95": None,
            "liq_proximity_pct": None, "vpin_toxicity": vpin_val,
            "samples": len(returns),
        }
        if len(returns) >= 31:
            try:
                var_out = state.var_calculator.compute(returns, position_usd=10000.0, leverage=1.0)
                ens = (var_out.get("ensemble_max") or {}).get("var_95") or {}
                risk_block["var_ens"] = ens.get("return_pct")
                stressed = var_out.get("stressed_var") or {}
                risk_block["var_stressed"] = stressed.get("return_pct")
                liq = var_out.get("liquidation_risk") or {}
                risk_block["liq_proximity_pct"] = liq.get("probability_horizon")
                es_out = _es_calculator.compute(returns, position_usd=10000.0, leverage=1.0)
                es_ens = (es_out.get("ensemble_max") or {}).get("es_95") or {}
                risk_block["es_95"] = es_ens.get("return_pct")
            except Exception as exc:  # noqa: BLE001
                logger.debug("risk %s: %s", sym, exc)

        # ------------------------------------------------------------------
        # Venue health from ws_manager.gap_report
        # ------------------------------------------------------------------
        venues: list[Dict] = []
        try:
            gap_report = state.ws_manager.gap_report()
            if isinstance(gap_report, dict):
                for name, data in gap_report.items():
                    sec_since = float(data.get("seconds_since_last_event", 999) or 999)
                    venues.append({
                        "name": name,
                        "staleness_ms": int(sec_since * 1000),
                        "healthy": sec_since < 30,
                        "gaps": int(data.get("gap_count", 0) or 0),
                    })
        except Exception:  # noqa: BLE001
            pass

        return {
            "ts": time.time(),
            "symbol": sym,
            "composite": {
                "score": composite.score,
                "verdict": composite.verdict,
                "confidence": composite.confidence,
                "agreement": composite.agreement,
                "venue_agreement": composite.venue_agreement,
            },
            "layers": composite.layers,
            "weights_used": composite.weights_used,
            "regime": {
                "label": regime_label,
                "confidence": round(regime_conf, 3),
                "hurst": round(H, 4) if H is not None else None,
                "hurst_signed": round(H_score, 4),
                "entropy": round(E, 4) if E is not None else None,
                "entropy_signed": round(E_score, 4),
            },
            "flow": {
                "cvd_5m": _get_or_none(cvd_mtf.get("5m") if isinstance(cvd_mtf, dict) else None, "net_delta"),
                "cvd_15m": _get_or_none(cvd_mtf.get("15m") if isinstance(cvd_mtf, dict) else None, "net_delta"),
                "cvd_1h": cvd_1h,
                "cvd_4h": _get_or_none(cvd_mtf.get("4h") if isinstance(cvd_mtf, dict) else None, "net_delta"),
                "trades_5m": _get_or_none(cvd_mtf.get("5m") if isinstance(cvd_mtf, dict) else None, "trade_count"),
                "trades_1h": _get_or_none(cvd_mtf.get("1h") if isinstance(cvd_mtf, dict) else None, "trade_count"),
                "flow_ratio": round(flow_ratio, 4) if flow_ratio is not None else None,
                "absorption": absorption_state,
                "vpin": round(vpin_val, 4) if vpin_val is not None else None,
                "obi": round(obi_val, 4) if obi_val is not None else None,
                "obi_z": round(obi_z, 3) if obi_z is not None else None,
                "obi_bias": obi_bias,
                "obi_qty": round(obi_qty_val, 4) if obi_qty_val is not None else None,
                "obi_qty_z": round(obi_qty_z, 3) if obi_qty_z is not None else None,
                "obi_qty_bias": obi_qty_bias,
            },
            "oi": {
                "change_pct_1h": round(oi_change_pct, 4),
                "zscore_4h_7d": round(oi_zscore_val, 4) if oi_zscore_val is not None else None,
            },
            "research": {
                "basis_pct": round(basis_pct, 4) if basis_pct is not None else None,
                "basis_dispersion_pct": round(basis_dispersion, 5) if basis_dispersion is not None else None,
                "funding_pct": round(funding_pct, 4) if funding_pct is not None else None,
                "funding_persistence": round(funding_persistence, 3) if funding_persistence is not None else None,
                "funding_skew_pct": round(funding_skew_val, 4) if funding_skew_val is not None else None,
                "funding_skew": funding_skew_payload,
                "gex_proxy": round(gex_proxy_val, 4) if gex_proxy_val is not None else None,
                "dealer_skew": round(funding_skew_val, 4) if funding_skew_val is not None else None,
            },
            "risk": risk_block,
            "venues": venues,
            "samples": {"klines": len(closes), "returns": len(returns)},
        }

    return router
