"""
Nexus - FastAPI Application Entry Point
Institutional-grade crypto derivatives research terminal.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

# Fix SSL certificate verification on Windows (Python 3.14+)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import DEFAULT_SYMBOLS, DEFAULT_INTERVAL, INSTITUTIONAL_DEPTH

# --- Ingestion ---
from backend.ingestion.ws_manager import WSManager
from backend.ingestion.binance_ws import create_binance_connection, binance_data
from backend.ingestion.okx_ws import create_okx_connection, okx_data
from backend.ingestion.mexc_ws import create_mexc_connection, mexc_data
from backend.ingestion.news_feed import NewsFeed
from backend.ingestion.deribit_feed import DeribitFeed
from backend.ingestion.macro_feed import MacroFeed
from backend.ingestion.blofin_client import BloFinClient
from backend.ingestion.consolidated_book import merge_books
from backend.ingestion.weighted_mid import compute_weighted_mid
from backend.ingestion.feed_validator import feed_health_summary
from backend.ingestion.trade_router import fetch_new_trades, active_sources

# --- Computation ---
from backend.computation.golden_zone import GoldenZoneEngine
from backend.computation.cvd import CVDComputer
from backend.computation.oi_analysis import OITracker
from backend.computation.funding import FundingTracker
from backend.computation.squeeze_risk import SqueezeRiskMeter
from backend.computation.regime import RegimeClassifier
from backend.computation.alpha_engine import AlphaEngine
from backend.computation.liquidity_heatmap import LiquidityHeatmap
from backend.computation.smart_money import SmartMoneyTracker
from backend.computation.obi_tracker import OBITracker
from backend.computation.tape_speed import TapeSpeedTracker
from backend.computation.liquidation_imbalance import LiquidationAggregator
from backend.computation.vol_spread import compute_spread as compute_vol_spread
from backend.computation.correlation import correlation_matrix, pairwise_sorted
from backend.computation.vpin import VPINTracker
from backend.computation.absorption import AbsorptionDetector

# --- Risk ---
from backend.risk.kelly import KellySizer
from backend.risk.var import VaRCalculator
from backend.risk.circuit_breaker import CircuitBreaker

# --- Background jobs ---
from backend.jobs.oi_poller import oi_poll_loop
from backend.jobs.absorption_sampler import absorption_sample_loop
from backend.jobs.agg_trade_rest_poller import agg_trade_rest_loop

# --- Unified Matrix API ---
from backend.api.matrix import make_router as make_matrix_router

# --- Monitoring / event bus ---
from backend.monitoring.event_bus import bus as event_bus, wire_circuit_breaker
from backend.risk.liquidation import estimate_liquidation_price
from backend.risk.portfolio_margin import PortfolioMarginClient

# --- Macro ---
from backend.macro.calendar import EconomicCalendar
from backend.macro.gate import MacroGate
from backend.macro.sentinel_bridge import SentinelBridge

# --- AI ---
from backend.ai.gemma4 import Gemma4
from backend.ai.finbert import FinBERTScorer
from backend.ai.brief_generator import BriefGenerator

# --- Alerts ---
from backend.alerts.telegram import TelegramBot
from backend.alerts.scheduler import AlertScheduler

# --- Storage ---
from backend.storage import db as storage_db
from backend.storage.zones import get_watchlist, add_to_watchlist
from backend.storage.alerts import get_recent_alerts, save_alert
from backend.storage.briefs import get_last_brief, save_brief
from backend.storage.metrics import save_snapshots as save_metric_snapshots, prune_old as prune_metric_snapshots, fetch_range as fetch_metric_range
from backend.computation.backtest import backtest_zones, ZoneBand

# ---Journal---
from backend.journal_router import router as journal_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nexus")

# ---------------------------------------------------------------------------
# Singleton instances
# ---------------------------------------------------------------------------
ws_manager = WSManager()
news_feed = NewsFeed()
deribit_feed = DeribitFeed()
macro_feed = MacroFeed()
blofin = BloFinClient()

# Per-symbol engines
zone_engines: dict[str, GoldenZoneEngine] = {}
cvd_computers: dict[str, CVDComputer] = {}
oi_trackers: dict[str, OITracker] = {}
funding_trackers: dict[str, FundingTracker] = {}
squeeze_meters: dict[str, SqueezeRiskMeter] = {}

regime_classifier = RegimeClassifier()
alpha_engines: dict[str, AlphaEngine] = {}
heatmaps: dict[str, LiquidityHeatmap] = {}
smart_money_trackers: dict[str, SmartMoneyTracker] = {}
obi_trackers: dict[str, OBITracker] = {}
tape_trackers: dict[str, TapeSpeedTracker] = {}
liq_aggregators: dict[str, LiquidationAggregator] = {}
vpin_trackers: dict[str, VPINTracker] = {}
absorption_detectors: dict[str, AbsorptionDetector] = {}

# Default VPIN bucket: ~$2M notional ≈ daily $-vol/50 for liquid majors. Refreshed
# nightly elsewhere is a P3; at startup the default is fine for warm-up.
_VPIN_DEFAULT_BUCKET_USD = 2_000_000.0

# Per-symbol last ingested trade timestamp (ms) so we only forward new trades to
# CVD / smart-money on each zone-loop tick.
_last_trade_cursor: dict[str, int] = {}
kelly_sizer = KellySizer()
var_calculator = VaRCalculator()
circuit_breaker = CircuitBreaker()
pm_client = PortfolioMarginClient()

calendar = EconomicCalendar()
macro_gate = MacroGate(calendar)
sentinel_bridge = SentinelBridge(calendar)

gemma4 = Gemma4()
finbert = FinBERTScorer()
brief_generator = BriefGenerator()

telegram = TelegramBot()
alert_scheduler = AlertScheduler(telegram)


def _book_mid(book: dict | None) -> float | None:
    """Top-of-book mid from a {bids, asks} dict. Returns None on bad data."""
    if not isinstance(book, dict):
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return None
    try:
        bb = float(bids[0][0]); ba = float(asks[0][0])
    except (TypeError, ValueError, IndexError):
        return None
    if bb <= 0 or ba <= 0 or ba <= bb:
        return None
    return (bb + ba) / 2.0


def _build_cross_exchange_mids(symbol: str) -> dict[str, dict]:
    """Build the {venue: {mid_price: float}} dict the alpha engine's
    `compute_cross_exchange_spread` expects.

    Sources (in order):
      - binance      = Binance Futures L2 top-of-book mid
      - binance_mark = Binance Futures mark-price stream (funding-adjusted
                       index - independent feed from L2; useful even when
                       OKX/MEXC books are empty so we always have ≥2
                       sources to spread against)
      - okx          = OKX SWAP L2 mid
      - mexc         = MEXC futures L2 mid

    The alpha engine's `compute_cross_exchange_spread` will use whichever
    arrive - guaranteeing the spread can always score at least
    perp-mid vs mark-price-index even on cold start before OKX/MEXC books
    populate.
    """
    out: dict[str, dict] = {}
    bin_book = binance_data.order_books.get(symbol)
    bin_mid = _book_mid(bin_book)
    if bin_mid:
        out["binance"] = {"mid_price": bin_mid}

    # Mark price is a separate WS stream and represents the funding-adjusted
    # index - small but real spread vs L2 mid. Surface as its own source so
    # the cross-exchange engine always has ≥2 prices to compare on Binance.
    mp = binance_data.mark_prices.get(symbol, {})
    try:
        mark_p = float(mp.get("mark_price", 0) or 0) or None
    except (TypeError, ValueError):
        mark_p = None
    if mark_p:
        # Skip when L2 mid and mark are bit-identical (would be useless).
        if bin_mid is None or abs(bin_mid - mark_p) > 1e-9:
            out["binance_mark"] = {"mid_price": mark_p}
        if bin_mid is None:
            # Promote mark to "binance" so the leader-laggard logic in the
            # engine still names a venue (it special-cases binance).
            out["binance"] = {"mid_price": mark_p}

    okx_mid = _book_mid(okx_data.order_books.get(symbol))
    if okx_mid:
        out["okx"] = {"mid_price": okx_mid}

    mexc_mid = _book_mid(mexc_data.order_books.get(symbol))
    if mexc_mid:
        out["mexc"] = {"mid_price": mexc_mid}

    return out


def _init_symbol_engines():
    for sym in DEFAULT_SYMBOLS:
        _ensure_symbol_engines(sym)


def _ensure_symbol_engines(symbol: str) -> None:
    """Lazily create per-symbol engines so any searched Binance USDT-M pair
    works without a restart. DEFAULT_SYMBOLS get WS feeds + zone loops; others
    get engines only (REST-backed computation)."""
    sym = (symbol or "").strip().upper()
    if not sym:
        # A blank key would poison every 30s poll loop with symbol= requests
        # (Binance answers 418 and rate-bans the IP). Refuse to register it.
        logger.warning("_ensure_symbol_engines called with empty symbol - ignored")
        return
    if sym not in zone_engines:
        zone_engines[sym] = GoldenZoneEngine(sym)
    if sym not in cvd_computers:
        cvd_computers[sym] = CVDComputer(sym)
    if sym not in oi_trackers:
        oi_trackers[sym] = OITracker(sym)
    if sym not in funding_trackers:
        funding_trackers[sym] = FundingTracker(sym)
    if sym not in squeeze_meters:
        squeeze_meters[sym] = SqueezeRiskMeter(sym)
    if sym not in alpha_engines:
        alpha_engines[sym] = AlphaEngine(sym, binance_data=binance_data)
    if sym not in heatmaps:
        heatmaps[sym] = LiquidityHeatmap(sym)
    if sym not in smart_money_trackers:
        smart_money_trackers[sym] = SmartMoneyTracker(sym)
    if sym not in obi_trackers:
        obi_trackers[sym] = OBITracker(sym)
    if sym not in tape_trackers:
        tape_trackers[sym] = TapeSpeedTracker(sym)
    if sym not in liq_aggregators:
        liq_aggregators[sym] = LiquidationAggregator(sym)
    if sym not in vpin_trackers:
        vpin_trackers[sym] = VPINTracker(bucket_target_notional=_VPIN_DEFAULT_BUCKET_USD)
    if sym not in absorption_detectors:
        absorption_detectors[sym] = AbsorptionDetector(sym)


# ---------------------------------------------------------------------------
# Trade ingestion loop - fans fresh aggTrades out to CVD, smart-money and
# Alpha VWAP at 2s cadence (the zone check loop at 60s was too slow for
# derivative order-flow metrics).
# ---------------------------------------------------------------------------
async def _trade_ingest_loop():
    while True:
        try:
            # Union of trade-bearing symbols across primary + fallback venues so a
            # full Binance outage doesn't stall ingestion for symbols only the
            # fallback venue currently has trades for.
            all_symbols = set()
            all_symbols.update(binance_data.agg_trades.keys())
            all_symbols.update(okx_data.trades.keys())
            all_symbols.update(mexc_data.trades.keys())
            for sym in all_symbols:
                _ensure_symbol_engines(sym)
                source, new_trades = fetch_new_trades(sym, ws_manager=ws_manager)
                if not new_trades:
                    continue

                cvd = cvd_computers.get(sym)
                smt = smart_money_trackers.get(sym)
                alpha = alpha_engines.get(sym)
                tape = tape_trackers.get(sym)
                vpin = vpin_trackers.get(sym)

                bucket_closed = False
                for t in new_trades:
                    price = float(t.get("price", 0))
                    qty = float(t.get("qty", 0))
                    if price <= 0 or qty <= 0:
                        continue
                    is_buyer_maker = bool(t.get("is_buyer_maker", True))
                    ts_ms = int(t.get("time", time.time() * 1000))
                    if cvd:
                        cvd.ingest_trade(price, qty, is_buyer_maker, ts_ms)
                    if smt:
                        smt.process_trade(
                            price=price, qty=qty,
                            is_buyer_maker=is_buyer_maker,
                            timestamp=ts_ms / 1000,
                        )
                    if alpha:
                        alpha.ingest_trade(price, qty)
                    if tape:
                        tape.record(ts_ms / 1000)
                    if vpin:
                        # is_buyer_maker=True → taker is seller
                        side = "sell" if is_buyer_maker else "buy"
                        if vpin.add_trade(price, qty, side=side, ts=ts_ms / 1000):
                            bucket_closed = True

                # Publish VPIN once per tick if any bucket closed - prevents
                # high-frequency spam while keeping the breaker reactive.
                if vpin and bucket_closed:
                    snap = vpin.snapshot()
                    try:
                        await event_bus.publish("vpin.update", {
                            "stream": sym,
                            "vpin": snap.running,
                            "toxic": snap.toxic,
                        })
                    except Exception as e:
                        logger.debug(f"vpin publish error {sym}: {e}")
                # Sample tape speed once per tick for this symbol
                if tape:
                    sample = tape.sample()
                    if sample:
                        try:
                            save_metric_snapshots(sym, "tape", [(
                                sample["time"], sample["tps"],
                                {"count": sample["count"], "window": sample["window"]},
                            )])
                        except Exception as e:
                            logger.debug(f"tape persist error {sym}: {e}")
                # Cursor is owned by trade_router now; keep _last_trade_cursor
                # for backwards-compat read-only consumers (UI status panels).
                _last_trade_cursor[sym] = int(new_trades[-1].get("time", _last_trade_cursor.get(sym, 0)))
        except Exception as e:
            logger.error(f"trade_ingest_loop error: {e}")
        await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Liquidation aggregation loop - pulls fresh liquidation events from all
# exchange feeds into the per-symbol aggregator and samples imbalance every 5s.
# ---------------------------------------------------------------------------
# Track cascade state per symbol so we only fire the alert on the rising edge
_liq_cascade_state: dict[str, bool] = {}


async def _liquidation_loop():
    while True:
        try:
            symbols = set()
            symbols.update(binance_data.liquidations.keys())
            symbols.update(okx_data.liquidations.keys())
            for sym in symbols:
                _ensure_symbol_engines(sym)
                agg = liq_aggregators.get(sym)
                if not agg:
                    continue
                if sym in binance_data.liquidations:
                    agg.ingest_binance(list(binance_data.liquidations[sym]))
                if sym in okx_data.liquidations:
                    agg.ingest_okx(list(okx_data.liquidations[sym]))
                snap = agg.sample()
                summary = agg.summary()

                # Persist one row per tick
                try:
                    save_metric_snapshots(sym, "liq", [(
                        snap["time"],
                        snap["imbalance"],
                        {
                            "long_usd": snap["long_usd"],
                            "short_usd": snap["short_usd"],
                            "total_usd": snap["total_usd"],
                            "bias": summary.get("bias"),
                            "cascade": summary.get("cascade"),
                        },
                    )])
                except Exception as e:
                    logger.debug(f"liq persist error {sym}: {e}")

                # Rising-edge cascade alert
                was = _liq_cascade_state.get(sym, False)
                is_now = bool(summary.get("cascade"))
                if is_now and not was:
                    bias = summary.get("bias", "balanced")
                    total = summary.get("total_usd", 0)
                    imb = summary.get("imbalance", 0)
                    msg = (
                        f"⚠️ Liquidation cascade - {sym} · {bias.replace('_', ' ').upper()} "
                        f"· ${total:,.0f} in 5m · imb {imb * 100:+.1f}%"
                    )
                    logger.warning(msg)
                    try:
                        save_alert("liquidation_cascade", msg, symbol=sym, data={
                            "imbalance": imb, "long_usd": snap["long_usd"],
                            "short_usd": snap["short_usd"], "total_usd": total, "bias": bias,
                        })
                    except Exception as e:
                        logger.debug(f"save_alert error: {e}")
                    try:
                        await telegram.send_message(msg)
                    except Exception as e:
                        logger.debug(f"telegram cascade send error: {e}")
                _liq_cascade_state[sym] = is_now
        except Exception as e:
            logger.error(f"liquidation_loop error: {e}")
        await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Circuit-breaker producer loop - periodically publishes:
#   - ws.gap            (full gap_report from WSManager)
#   - correlation.snapshot (avg |ρ| across DEFAULT_SYMBOLS, 96-bar lookback)
#   - funding.zscore    (per-symbol rolling z-score, 168h window)
#
# var.breach is published ad-hoc by the position layer when realized PnL
# crosses the VaR99 envelope (no live positions today → no producer wired).
# vpin.update fires from _trade_ingest_loop on bucket close.
#
# Cadence: 30s. Light enough to not contend with the 2s trade loop, fast
# enough that a 60s WS outage trips the breaker on the next tick.
# ---------------------------------------------------------------------------
async def _circuit_breaker_loop():
    while True:
        try:
            # 1) WS gap report → ws.gap
            try:
                report = ws_manager.gap_report()
                if report:
                    await event_bus.publish("ws.gap", {"gap_report": report})
            except Exception as e:
                logger.debug(f"cb_loop ws.gap publish error: {e}")

            # 2) Correlation snapshot → correlation.snapshot
            try:
                series: dict[str, list[float]] = {}
                for sym in DEFAULT_SYMBOLS:
                    hist = list(binance_data.kline_history.get(sym, []))
                    closes = [float(c.get("close", 0)) for c in hist[-96:] if c.get("close")]
                    if closes:
                        series[sym] = closes
                if len(series) >= 2:
                    matrix = correlation_matrix(series)
                    pairs = pairwise_sorted(matrix, limit=50)
                    if pairs:
                        avg_rho = sum(abs(p.get("corr", 0.0)) for p in pairs) / len(pairs)
                        await event_bus.publish("correlation.snapshot", {
                            "avg_rho": avg_rho,
                            "ts": time.time(),
                        })
            except Exception as e:
                logger.debug(f"cb_loop correlation publish error: {e}")

            # 3) Funding z-score per symbol → funding.zscore
            for sym, tracker in list(funding_trackers.items()):
                try:
                    z = tracker.funding_zscore_rolling(window_hours=168.0)
                    if z.get("classification") != "insufficient_data":
                        await event_bus.publish("funding.zscore", {
                            "stream": sym,
                            "zscore": float(z.get("zscore", 0.0)),
                        })
                except Exception as e:
                    logger.debug(f"cb_loop funding publish error {sym}: {e}")
        except Exception as e:
            logger.error(f"circuit_breaker_loop error: {e}")
        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Metric pruner - trims metric_snapshots table to retention window hourly.
# ---------------------------------------------------------------------------
async def _metrics_pruner():
    while True:
        try:
            deleted = prune_metric_snapshots()
            if deleted:
                logger.info(f"metrics pruner: deleted {deleted} old rows")
        except Exception as e:
            logger.error(f"metrics pruner error: {e}")
        await asyncio.sleep(3600)


# ---------------------------------------------------------------------------
# Zone check callback (runs every 60s)
# ---------------------------------------------------------------------------
async def _zone_check_loop():
    alerts = []
    for sym in DEFAULT_SYMBOLS:
        engine = zone_engines.get(sym)
        if not engine:
            continue

        if sym in binance_data.order_books:
            engine.update_order_book("binance", binance_data.order_books[sym])

        # Sample OBI from the best available venue book. Primary = Binance
        # (deepest book, tightest spread), fall back to OKX → MEXC if the
        # primary feed is missing for this tick. Without this fallback a
        # Binance WS hiccup zeros out the OBI series silently.
        ob = (
            binance_data.order_books.get(sym)
            or okx_data.order_books.get(sym)
            or mexc_data.order_books.get(sym)
        )
        if ob:
            obi = obi_trackers.get(sym)
            if obi:
                obi_sample = obi.update(ob)
                if obi_sample:
                    try:
                        save_metric_snapshots(sym, "obi", [(
                            obi_sample.get("time", time.time()),
                            obi_sample.get("obi"),
                            {"bid_vol": obi_sample.get("bid_vol"), "ask_vol": obi_sample.get("ask_vol")},
                        )])
                    except Exception as e:
                        logger.debug(f"obi persist error {sym}: {e}")

        # Feed heatmap with an AGGREGATED snapshot across all exchanges.
        # Walls reported by the heatmap are now cross-venue institutional
        # liquidity, not just Binance-only depth.
        hmap = heatmaps.get(sym)
        if hmap:
            books_by_exchange = {}
            if sym in binance_data.order_books:
                books_by_exchange["binance"] = binance_data.order_books[sym]
            if sym in okx_data.order_books:
                books_by_exchange["okx"] = okx_data.order_books[sym]
            if sym in mexc_data.order_books:
                books_by_exchange["mexc"] = mexc_data.order_books[sym]
            if books_by_exchange:
                hmap.add_aggregated_snapshot(books_by_exchange, time.time())

        if sym in okx_data.order_books:
            engine.update_order_book("okx", okx_data.order_books[sym])
        if sym in mexc_data.order_books:
            engine.update_order_book("mexc", mexc_data.order_books[sym])

        # Trade ingestion runs on a dedicated 2s loop (_trade_ingest_loop)
        # so CVD / smart-money / Alpha stay near-real-time.

        zones = engine.detect_zones()
        golden_plus = [z for z in zones if z.tier in ("golden", "platinum") and z.persistent]

        mark = binance_data.mark_prices.get(sym, {}).get("mark_price", 0)
        if mark <= 0:
            continue

        for zone in golden_plus:
            distance_pct = abs(mark - zone.price_center) / mark * 100
            if distance_pct <= 0.5:
                alerts.append({
                    "type": "zone_approach",
                    "symbol": sym,
                    "price": mark,
                    "tier": zone.tier,
                    "zone_type": zone.zone_type,
                    "exchange_count": zone.exchange_count,
                    "distance_pct": distance_pct,
                })

    gate_status = macro_gate.evaluate()
    if gate_status.is_restricted:
        alerts.append({
            "type": "macro_danger",
            "event_name": gate_status.active_event,
            "minutes_until": gate_status.minutes_until_event,
            "confidence_threshold": gate_status.confidence_threshold,
            "max_position_pct": gate_status.max_position_pct * 100,
        })

    return alerts


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Nexus starting up...")

    storage_db.get_connection()
    _init_symbol_engines()

    # ---- P0-4 gap-fill consumer hooks ----
    # WSManager fires `on_gap(name, gap_start, gap_end)` after every reconnect
    # whose outage exceeded 1s. The per-venue handlers below run a *bounded*
    # REST backfill so the live buffers don't have a hole in them. We do not
    # backfill trades for OKX/MEXC inline - the existing
    # `agg_trade_rest_loop` covers Binance, and OKX/MEXC public REST trade
    # endpoints return at most the last ~100 prints so they're best effort.
    async def _on_binance_gap(name: str, gap_start: float, gap_end: float) -> None:
        gap_s = gap_end - gap_start
        if gap_s < 1.0:
            return
        logger.warning(
            "[%s] WS gap %.1fs detected - backfilling klines via REST", name, gap_s
        )
        for sym in DEFAULT_SYMBOLS:
            try:
                # Re-fetch the last 100 candles on the default interval. The
                # in-memory deque is keyed by close_time, so overlapping bars
                # are upserted rather than duplicated.
                await binance_data.fetch_historical_klines(
                    sym, DEFAULT_INTERVAL, limit=100,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[%s] kline backfill %s: %s", name, sym, exc)

    async def _on_okx_gap(name: str, gap_start: float, gap_end: float) -> None:
        gap_s = gap_end - gap_start
        if gap_s < 1.0:
            return
        # OKX trade REST has no historical window worth backfilling (last ~100
        # prints only). Surface the gap to monitoring; the live stream
        # resumes automatically after reconnect.
        logger.warning(
            "[%s] WS gap %.1fs - relying on stream reconnect (no REST backfill)",
            name, gap_s,
        )

    async def _on_mexc_gap(name: str, gap_start: float, gap_end: float) -> None:
        gap_s = gap_end - gap_start
        if gap_s < 1.0:
            return
        logger.warning(
            "[%s] WS gap %.1fs - relying on stream reconnect (no REST backfill)",
            name, gap_s,
        )

    binance_conn = create_binance_connection()
    binance_conn.on_gap = _on_binance_gap
    okx_conn = create_okx_connection()
    okx_conn.on_gap = _on_okx_gap
    mexc_conn = create_mexc_connection()
    mexc_conn.on_gap = _on_mexc_gap

    ws_manager.add(binance_conn)
    ws_manager.add(okx_conn)
    ws_manager.add(mexc_conn)
    await ws_manager.start_all()

    # Fetch historical klines for regime classifier (needs 20+ candles)
    for sym in DEFAULT_SYMBOLS:
        await binance_data.fetch_historical_klines(sym, DEFAULT_INTERVAL, limit=100)

    alert_scheduler.set_zone_check_callback(_zone_check_loop)
    asyncio.create_task(alert_scheduler.start())
    asyncio.create_task(_trade_ingest_loop())
    asyncio.create_task(_liquidation_loop())
    asyncio.create_task(_metrics_pruner())
    # OI / funding background poller (P0 fix - was REST-only on demand)
    asyncio.create_task(oi_poll_loop(oi_trackers, funding_trackers, interval_s=30))
    # Absorption sampler - replaces inline single-shot heuristic in /api/orderflow
    asyncio.create_task(absorption_sample_loop(absorption_detectors, cvd_computers, interval_s=5.0))
    # aggTrade REST fallback - kicks in only when WS trades stall (PH/PLDT
    # users see this regularly: depth20 flows, aggTrade does not).
    asyncio.create_task(agg_trade_rest_loop(DEFAULT_SYMBOLS))

    # Wire circuit-breaker handlers to event-bus topics, then start the
    # producer loop. Order matters: subscribers first, producers second.
    wire_circuit_breaker(circuit_breaker)
    asyncio.create_task(_circuit_breaker_loop())

    gemma_ok = await gemma4.check_health()
    logger.info(f"Gemma 4 (gemma4:e4b): {'available' if gemma_ok else 'NOT available'}")
    logger.info(f"BloFin (paper): {'connected' if blofin.connected else 'not configured'}")
    logger.info("Nexus ready.")
    yield

    logger.info("Nexus shutting down...")
    await alert_scheduler.stop()
    await ws_manager.stop_all()
    storage_db.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Nexus",
    description="Institutional-grade crypto derivatives research terminal",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(journal_router)


# ---------------------------------------------------------------------------
# Unified Matrix Engine endpoint - /api/matrix/{symbol}
# Bound to module-level state via a small adapter object so the router can
# read everything it needs without circular imports.
# ---------------------------------------------------------------------------
class _MatrixState:
    """Adapter exposing module-level state to the matrix router."""

    cvd_computers = cvd_computers
    oi_trackers = oi_trackers
    funding_trackers = funding_trackers
    obi_trackers = obi_trackers
    liq_aggregators = liq_aggregators
    vpin_trackers = vpin_trackers
    absorption_detectors = absorption_detectors
    alpha_engines = alpha_engines
    regime_classifier = regime_classifier
    var_calculator = var_calculator
    binance_data = binance_data
    deribit_feed = deribit_feed
    ws_manager = None  # bound below after ws_manager is created

    @staticmethod
    def ensure_engines(symbol: str) -> None:
        _ensure_symbol_engines(symbol)


_matrix_state = _MatrixState()
# ws_manager is created earlier in this file but referenced by name; bind now.
try:
    _matrix_state.ws_manager = ws_manager  # type: ignore[attr-defined]
except NameError:
    pass

app.include_router(make_matrix_router(state=_matrix_state))

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "0.3.0",
        "websockets": ws_manager.status,
        "ws_gap_report": ws_manager.gap_report(),
        "symbols": DEFAULT_SYMBOLS,
        "gemma4_model": gemma4.model,
        "blofin_connected": blofin.connected,
        "telegram_configured": telegram.configured,
        "circuit_breaker": circuit_breaker.state.to_dict(),
        "circuit_breaker_events": circuit_breaker.recent_events(32),
        "event_bus_recent": event_bus.recent(32),
        "uptime": time.time(),
    }


# ---------------------------------------------------------------------------
# Multi-exchange fusion: weighted mid, merged book, feed health
# ---------------------------------------------------------------------------
@app.get("/api/midprice/{symbol}")
async def get_midprice(symbol: str):
    sym = symbol.upper()
    return compute_weighted_mid(sym, ws_manager=ws_manager)


@app.get("/api/book/merged/{symbol}")
async def get_merged_book(symbol: str, depth: int = Query(20, ge=1, le=100)):
    sym = symbol.upper()
    return merge_books(sym, depth=depth)


@app.get("/api/feed/health")
async def get_feed_health():
    summary = feed_health_summary(ws_manager=ws_manager)
    summary["active_trade_sources"] = active_sources()
    return summary


# ---------------------------------------------------------------------------
# Crypto ticker strip - 24h stats for the marquee under the header.
# One bulk Binance call (ticker/24hr without symbol → all pairs) filtered to
# the strip watchlist; cached 5s with single-flight so polls never stack.
# ---------------------------------------------------------------------------
STRIP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "SUIUSDT",
]
_strip_cache: dict = {}
_strip_lock = asyncio.Lock()
_STRIP_TTL_SEC = 5.0


@app.get("/api/crypto/strip")
async def get_crypto_strip():
    now = time.time()
    hit = _strip_cache.get("data")
    if hit and now - hit[0] < _STRIP_TTL_SEC:
        return hit[1]
    async with _strip_lock:
        hit = _strip_cache.get("data")
        if hit and time.time() - hit[0] < _STRIP_TTL_SEC:
            return hit[1]
        data = await _afetch("/fapi/v1/ticker/24hr")
        quotes = []
        if isinstance(data, list):
            by_symbol = {d.get("symbol"): d for d in data if isinstance(d, dict)}
            for sym in STRIP_SYMBOLS:
                d = by_symbol.get(sym)
                if not d:
                    continue
                try:
                    quotes.append({
                        "symbol": sym,
                        "price": float(d.get("lastPrice", 0) or 0),
                        "change_pct": float(d.get("priceChangePercent", 0) or 0),
                        "high": float(d.get("highPrice", 0) or 0),
                        "low": float(d.get("lowPrice", 0) or 0),
                        "quote_volume": float(d.get("quoteVolume", 0) or 0),
                    })
                except (TypeError, ValueError):
                    continue
        payload = {
            "quotes": quotes,
            "count": len(quotes),
            "updated_at": time.time(),
            "source": "binance_futures",
        }
        if quotes:  # don't cache an empty answer - retry next poll
            _strip_cache["data"] = (time.time(), payload)
        return payload


# ---------------------------------------------------------------------------
# Research Brief
# ---------------------------------------------------------------------------
@app.get("/api/brief/{symbol}")
async def get_brief(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    engine = zone_engines.get(symbol)
    if not engine:
        raise HTTPException(500, f"Engine init failed for {symbol}")

    zones = engine.detect_zones()
    funding = await funding_trackers[symbol].fetch_all() if symbol in funding_trackers else {}
    oi = await oi_trackers[symbol].fetch_all() if symbol in oi_trackers else {}
    gate_status = macro_gate.evaluate().to_dict()

    try:
        klines = list(binance_data.kline_history.get(symbol, []))
        if len(klines) >= 20:
            closes = [float(k.get("close", 0)) for k in klines]
            volumes = [float(k.get("volume", 0)) for k in klines]
            highs = [float(k.get("high", 0)) for k in klines]
            lows = [float(k.get("low", 0)) for k in klines]
            regime_data = regime_classifier.classify(closes, volumes, highs, lows)
        else:
            regime_data = {"regime": "insufficient_data", "confidence": 0}
    except Exception:
        regime_data = {"regime": "unknown", "confidence": 0}

    squeeze = squeeze_meters[symbol].compute(
        funding_rate_pct=funding.get("weighted_rate_pct", 0),
        oi_change_pct=oi_trackers[symbol].get_trend().get("change_pct", 0) if symbol in oi_trackers else 0,
        regime=regime_data.get("regime"),
    ) if symbol in squeeze_meters else {}

    return {
        "symbol": symbol,
        "zones": [z.to_dict() for z in zones[:10]],
        "funding": funding,
        "open_interest": oi,
        "squeeze_risk": squeeze,
        "macro_gate": gate_status,
        "mark_price": binance_data.mark_prices.get(symbol, {}),
        "cvd": cvd_computers[symbol].get_multi_timeframe() if symbol in cvd_computers else {},
        "regime": regime_data,
    }


# ---------------------------------------------------------------------------
# Zone endpoints
# ---------------------------------------------------------------------------
@app.get("/api/zones/watchlist")
async def get_zone_watchlist():
    return {"watchlist": get_watchlist()}


@app.get("/api/zones/{symbol}")
async def get_zones(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    engine = zone_engines.get(symbol)
    if not engine:
        raise HTTPException(500, f"Engine init failed for {symbol}")
    zones = engine.detect_zones()
    return {"symbol": symbol, "zones": [z.to_dict() for z in zones], "count": len(zones)}


class WatchlistAdd(BaseModel):
    symbol: str
    price_center: float
    tier: str
    zone_type: str


@app.post("/api/zones/alert")
async def add_zone_alert(item: WatchlistAdd):
    wid = add_to_watchlist(item.symbol.upper(), item.price_center, item.tier, item.zone_type)
    return {"id": wid, "status": "added"}


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------
@app.get("/api/oi/{symbol}")
async def get_oi(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    tracker = oi_trackers.get(symbol)
    if not tracker:
        raise HTTPException(500, f"Tracker init failed for {symbol}")
    snapshot = await tracker.fetch_all()
    trend = tracker.get_trend()
    return {"symbol": symbol, "snapshot": snapshot, "trend": trend}


@app.get("/api/funding/{symbol}")
async def get_funding(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    tracker = funding_trackers.get(symbol)
    if not tracker:
        raise HTTPException(500, f"Tracker init failed for {symbol}")
    return await tracker.fetch_all()


# Cache derivatives strip series - these are kline-derived and stable per (sym, interval).
_DERIV_TTL_SEC = 8.0
_deriv_locks: dict = {}
_deriv_cache: dict = {}  # {(symbol, interval, limit): (ts, payload)}


@app.get("/api/derivatives/{symbol}")
async def get_derivatives_strip(
    symbol: str,
    interval: str = Query("1h"),
    limit: int = Query(500, ge=30, le=1500),
):
    """Compact time-series for the chart's lower strip:
      - basis_pct  : (perp_close − spot_close) / spot_close × 100, kline-aligned
      - funding    : in-memory rolling samples from FundingTracker
      - oi         : in-memory rolling samples from OITracker
    Single round-trip replaces 3 polls. Cached briefly per (sym, interval, limit)."""
    sym = symbol.upper()
    if interval not in _VALID_INTERVALS:
        raise HTTPException(400, f"Invalid interval. Allowed: {sorted(_VALID_INTERVALS)}")

    key = (sym, interval, limit)
    now = time.time()
    cached = _deriv_cache.get(key)
    if cached and now - cached[0] < _DERIV_TTL_SEC:
        return cached[1]

    # Single-flight: concurrent polls for the same key share one computation
    # instead of each hitting Binance cold (they used to stack 19s responses).
    lock = _deriv_locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _deriv_cache.get(key)
        if cached and time.time() - cached[0] < _DERIV_TTL_SEC:
            return cached[1]
        payload = await _build_derivatives_strip(sym, interval, limit)
        _deriv_cache[key] = (time.time(), payload)
        return payload


async def _build_derivatives_strip(sym: str, interval: str, limit: int) -> dict:
    perp_task = _afetch(f"/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}")

    def _spot_get():
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
        try:
            # Short strict-SSL attempt - on PLDT-style networks this path can
            # hang to full timeout before the permissive retry; 4s caps that.
            req = _url.Request(url, headers={"User-Agent": "Nexus/0.3"})
            with _url.urlopen(req, timeout=4) as resp:
                return _json.loads(resp.read())
        except Exception:
            try:
                ctx = _ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
                req = _url.Request(url, headers={"User-Agent": "Nexus/0.3"})
                with _url.urlopen(req, timeout=10, context=ctx) as resp:
                    return _json.loads(resp.read())
            except Exception:
                return None

    loop = asyncio.get_event_loop()
    with _cf.ThreadPoolExecutor() as pool:
        spot_task = loop.run_in_executor(pool, _spot_get)
        perp_data, spot_data = await asyncio.gather(perp_task, spot_task)

    basis: list = []
    if isinstance(perp_data, list) and isinstance(spot_data, list):
        # Index spot by open-time for lookup; spot may have fewer bars
        spot_by_t = {int(k[0]): float(k[4]) for k in spot_data if isinstance(k, list) and len(k) > 4}
        for k in perp_data:
            if not isinstance(k, list) or len(k) < 5:
                continue
            t_ms = int(k[0])
            spot_close = spot_by_t.get(t_ms)
            if spot_close is None or spot_close <= 0:
                continue
            perp_close = float(k[4])
            basis.append({"time": t_ms // 1000, "value": (perp_close - spot_close) / spot_close * 100.0})

    _ensure_symbol_engines(sym)
    # In-memory tracker reads - the 30s oi_poll_loop keeps both fresh, so
    # re-fetching Binance+OKX REST per request only added seconds of latency.
    ft = funding_trackers.get(sym)
    ot = oi_trackers.get(sym)
    funding_latest: dict = {}
    oi_latest: dict = {}
    try:
        if ft is not None and ft._history:
            funding_latest = ft._history[-1] or {}
    except Exception:
        funding_latest = {}
    try:
        if ot is not None and ot._history:
            oi_latest = ot._history[-1] or {}
    except Exception:
        oi_latest = {}

    # Dedupe by integer-second timestamp (tracker may sample multiple times per
    # second under rapid polling); last write wins. Then sort ascending.
    def _dedupe_asc(pairs):
        m = {}
        for t, v in pairs:
            m[int(t)] = float(v)
        return [{"time": t, "value": v} for t, v in sorted(m.items())]

    funding_series = []
    if ft is not None:
        funding_series = _dedupe_asc(
            (h["timestamp"], (h.get("weighted_rate") or 0.0) * 100.0)
            for h in ft._history[-limit:] if h.get("weighted_rate") is not None
        )

    oi_series = []
    if ot is not None:
        oi_series = _dedupe_asc(
            (h["timestamp"], h.get("total") or 0.0)
            for h in list(ot._history)[-limit:] if h.get("total") is not None
        )

    # Latest convenience snapshots - used by Matrix Engine when series is sparse.
    basis_latest_val = basis[-1]["value"] if basis else 0.0
    funding_latest_val = float(funding_latest.get("weighted_rate", 0.0)) * 100.0 if funding_latest else 0.0
    oi_latest_total = 0.0
    if isinstance(oi_latest, dict):
        oi_latest_total = float(oi_latest.get("total", 0.0) or 0.0)

    payload = {
        "symbol": sym,
        "interval": interval,
        "basis": basis,
        "funding": funding_series,
        "oi": oi_series,
        "latest": {
            "basis_pct":     basis_latest_val,
            "funding_pct":   funding_latest_val,
            "oi_total":      oi_latest_total,
            "funding_venues": funding_latest.get("venues") if isinstance(funding_latest, dict) else None,
        },
    }
    return payload


@app.get("/api/lsratio/{symbol}")
async def get_ls_ratio(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    meter = squeeze_meters.get(symbol)
    if not meter:
        raise HTTPException(500, f"Meter init failed for {symbol}")
    await meter.fetch_ls_ratio()
    await meter.fetch_top_trader_ls()
    return {
        "symbol": symbol,
        "ls_ratio": meter._ls_ratio,
        "top_trader_ls_ratio": meter._top_ls_ratio,
    }


@app.get("/api/cvd/{symbol}")
async def get_cvd(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    computer = cvd_computers.get(symbol)
    if not computer:
        raise HTTPException(500, f"Computer init failed for {symbol}")
    return {"symbol": symbol, "timeframes": computer.get_multi_timeframe()}


@app.get("/api/obi/{symbol}")
async def get_obi(symbol: str, limit: int = 240):
    """Order-book imbalance time-series. Samples are appended by the zone loop
    at 100ms cadence (tied to Binance depth@100ms stream)."""
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    tracker = obi_trackers.get(symbol)
    if not tracker:
        raise HTTPException(500, f"OBI tracker init failed for {symbol}")

    # One-shot sample for newly searched symbols that haven't hit the 60s loop yet
    if not tracker.latest() and symbol in binance_data.order_books:
        tracker.update(binance_data.order_books[symbol])

    return {
        "symbol": symbol,
        "latest": tracker.latest(),
        "summary": tracker.summary(),
        "series": tracker.series(limit=limit),
    }


@app.get("/api/backtest/zones/{symbol}")
async def backtest_zones_endpoint(symbol: str, interval: str = "15m", reaction_bars: int = 6, bounce_pct: float = 0.8):
    """Replay historical klines against the *current* detected zones and report
    touch / bounce / break stats. This is a scaffolding endpoint - the hit-rate
    gives a gut-check on whether the live zone map would have caught recent swings."""
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    engine = zone_engines.get(symbol)
    if not engine:
        raise HTTPException(500, f"Zone engine not initialized for {symbol}")

    # Ensure we have recent klines
    history = list(binance_data.kline_history.get(symbol, []))
    if len(history) < 20:
        await binance_data.fetch_historical_klines(symbol, interval, limit=200)
        history = list(binance_data.kline_history.get(symbol, []))

    zones = engine.detect_zones()
    bands = [
        ZoneBand(
            price_low=float(z.price_low),
            price_high=float(z.price_high),
            zone_type=str(z.zone_type),
            tier=str(z.tier),
            score=float(getattr(z, "score", 0)),
        )
        for z in zones if z.price_low > 0 and z.price_high > 0
    ]
    candles = [
        {"time": c.get("open_time"), "open": c.get("open"), "high": c.get("high"),
         "low": c.get("low"), "close": c.get("close")}
        for c in history
    ]
    result = backtest_zones(candles, bands, reaction_bars=reaction_bars, bounce_pct=bounce_pct)
    result["symbol"] = symbol
    result["interval"] = interval
    return result


@app.get("/api/metrics/history/{symbol}")
async def get_metric_history(symbol: str, metric: str, minutes: int = 60, limit: int = 2000):
    """Replay persisted metric snapshots (obi | tape | liq) for the last N minutes.
    Useful for back-testing and post-mortems when the in-memory ring has rolled over."""
    if metric not in ("obi", "tape", "liq"):
        raise HTTPException(400, "metric must be one of: obi, tape, liq")
    end = time.time()
    start = end - max(1, minutes) * 60
    rows = fetch_metric_range(symbol.upper(), metric, start, end, limit=limit)
    return {"symbol": symbol.upper(), "metric": metric, "count": len(rows), "rows": rows}


@app.get("/api/correlation")
async def get_correlation(lookback: int = 96):
    """Cross-asset Pearson correlation across DEFAULT_SYMBOLS using the last
    ``lookback`` closed klines. Interval matches whatever the regime classifier
    is fed (15m by default)."""
    series: dict[str, list[float]] = {}
    for sym in DEFAULT_SYMBOLS:
        hist = list(binance_data.kline_history.get(sym, []))
        closes = [float(c.get("close", 0)) for c in hist[-lookback:] if c.get("close")]
        if closes:
            series[sym] = closes
    matrix = correlation_matrix(series)
    top = pairwise_sorted(matrix, limit=10)
    return {
        "lookback": lookback,
        "generated_at": time.time(),
        **matrix,
        "top_pairs": top,
    }


@app.get("/api/vol-spread/{symbol}")
async def get_vol_spread(symbol: str, interval: str = "15m"):
    """Realized vs implied vol spread. RV from kline history, IV from Deribit DVOL
    (BTC for *BTC* pairs, ETH for *ETH*). Returns annualized percent."""
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    history = list(binance_data.kline_history.get(symbol, []))
    closes = [float(c.get("close", 0)) for c in history if c.get("close")]
    # Pick matching Deribit currency
    currency = "BTC" if "BTC" in symbol else "ETH" if "ETH" in symbol else "BTC"
    dvol = await _dvol_cached(currency, hours=48)
    iv = dvol.get("latest") if dvol else None
    spread = compute_vol_spread(closes, iv_pct=iv, interval=interval)
    return {
        "symbol": symbol,
        "currency": currency,
        "dvol_series": (dvol or {}).get("series", []),
        **spread,
    }


@app.get("/api/liquidations/{symbol}")
async def get_liquidations(symbol: str, limit: int = 180):
    """Cross-exchange liquidation imbalance with windowed long/short USD flow.

    When ALL windows (5m / 15m / 1h) have zero flow (genuinely quiet market),
    the response includes a `leverage_stress` block sourced from L/S ratio +
    Top Trader L/S - same risk dimension (leverage exposure imbalance), so
    the UI has an institutional-grade related metric to surface instead of
    showing a permanent QUIET / -.
    """
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    agg = liq_aggregators.get(symbol)
    if not agg:
        raise HTTPException(500, f"Liquidation aggregator init failed for {symbol}")
    summary = agg.summary()

    leverage_stress = None
    # Provide the related-metric block when the canonical metric is quiet.
    if not summary.get("available", True):
        meter = squeeze_meters.get(symbol)
        if meter is not None:
            try:
                ls = await meter.fetch_ls_ratio()
                top_ls = await meter.fetch_top_trader_ls()
            except Exception:  # noqa: BLE001
                ls, top_ls = None, None
            ls_v = float(ls) if isinstance(ls, (int, float)) else None
            top_v = float(top_ls) if isinstance(top_ls, (int, float)) else None
            if ls_v is not None or top_v is not None:
                # Map L/S ratio to a balanced [-1, +1] imbalance proxy:
                #   ratio > 1 → long-heavy (positive imbalance, downside liq risk)
                #   ratio < 1 → short-heavy (negative imbalance, upside squeeze risk)
                # Convert via (ratio - 1) / (ratio + 1) so it's bounded.
                def _to_imb(r):
                    if r is None or r <= 0:
                        return None
                    return (r - 1.0) / (r + 1.0)
                imb_retail = _to_imb(ls_v)
                imb_top = _to_imb(top_v)
                # Top traders are "smart money" - opposite sign of the crowd
                # is the institutional signal. Combined imbalance weights top
                # 2x because it leads.
                parts = [(imb_retail, 1.0), (imb_top, 2.0)]
                wsum = 0.0; w_total = 0.0
                for v, w in parts:
                    if v is not None:
                        wsum += v * w
                        w_total += w
                combined = (wsum / w_total) if w_total > 0 else None
                # Bias label
                if combined is None:
                    bias = "no_data"
                elif combined >= 0.15:
                    bias = "long_crowded"
                elif combined <= -0.15:
                    bias = "short_crowded"
                else:
                    bias = "balanced"
                leverage_stress = {
                    "ls_ratio": round(ls_v, 4) if ls_v is not None else None,
                    "top_trader_ls": round(top_v, 4) if top_v is not None else None,
                    "imbalance_retail": round(imb_retail, 4) if imb_retail is not None else None,
                    "imbalance_top": round(imb_top, 4) if imb_top is not None else None,
                    "imbalance_combined": round(combined, 4) if combined is not None else None,
                    "bias": bias,
                    "source": "binance_lsratio + top_trader_lsratio",
                }
    return {
        "symbol": symbol,
        "latest": agg.latest(),
        "summary": summary,
        "series": agg.series(limit=limit),
        "leverage_stress": leverage_stress,
    }


@app.get("/api/tape/{symbol}")
async def get_tape(symbol: str, limit: int = 180):
    """Tape-speed (trades/sec) time-series with burst detection."""
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    tracker = tape_trackers.get(symbol)
    if not tracker:
        raise HTTPException(500, f"Tape tracker init failed for {symbol}")
    return {
        "symbol": symbol,
        "latest": tracker.latest(),
        "summary": tracker.summary(),
        "series": tracker.series(limit=limit),
    }


_news_cache: dict = {}
_news_lock = asyncio.Lock()
_NEWS_TTL_SEC = 90.0  # matches the documented 90s news cycle


@app.get("/api/news")
async def get_news():
    """Aggregated headlines (RSS + Binance + BloFin + Finnhub). fetch_all()
    re-hits every source (~8-12s), so cache the result for the news cycle and
    single-flight concurrent polls - otherwise the Alerts tab blocks on a cold
    fetch every time it mounts."""
    now = time.time()
    hit = _news_cache.get("data")
    if hit and now - hit[0] < _NEWS_TTL_SEC:
        return hit[1]
    async with _news_lock:
        hit = _news_cache.get("data")
        if hit and time.time() - hit[0] < _NEWS_TTL_SEC:
            return hit[1]
        headlines = await news_feed.fetch_all()
        payload = {"news": headlines, "count": len(headlines)}
        if headlines:  # don't cache an empty/failed fetch
            _news_cache["data"] = (time.time(), payload)
        return payload

from backend.sentiment_router import router as sentiment_router
app.include_router(sentiment_router)

# ---------------------------------------------------------------------------
# Deribit options
# ---------------------------------------------------------------------------
@app.get("/api/deribit/options/{currency}")
async def get_deribit_options(currency: str = "BTC"):
    pc_ratio = await deribit_feed.compute_put_call_ratio(currency.upper())
    max_pain = await deribit_feed.compute_max_pain(currency.upper())
    funding = await deribit_feed.get_funding_rate()
    return {
        "put_call_ratio": pc_ratio,
        "max_pain": max_pain,
        "perpetual_funding": funding,
    }


@app.get("/api/deribit/trades/{instrument}")
async def get_deribit_trades(instrument: str = "BTC-PERPETUAL", count: int = 100):
    trades = await deribit_feed.get_last_trades(instrument_name=instrument, count=count)
    return {"instrument": instrument, "trades": trades, "count": len(trades)}


# ---------------------------------------------------------------------------
# BloFin paper trading
# ---------------------------------------------------------------------------
@app.get("/api/blofin/balance")
async def get_blofin_balance():
    if not blofin.connected:
        return {"error": "BloFin not configured", "connected": False}
    return await blofin.get_balance()


@app.get("/api/blofin/positions")
async def get_blofin_positions():
    if not blofin.connected:
        return {"error": "BloFin not configured", "connected": False}
    return {"positions": await blofin.get_positions()}


class BloFinOrder(BaseModel):
    symbol: str = "BTC/USDT:USDT"
    side: str  # buy or sell
    amount: float
    price: Optional[float] = None
    order_type: str = "limit"
    leverage: int = 5
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@app.post("/api/blofin/order")
async def place_blofin_order(req: BloFinOrder):
    if not blofin.connected:
        return {"error": "BloFin not configured"}
    result = await blofin.place_order(
        symbol=req.symbol,
        side=req.side,
        amount=req.amount,
        price=req.price,
        order_type=req.order_type,
        leverage=req.leverage,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
    )
    return result or {"error": "Order failed"}


@app.get("/api/blofin/orders")
async def get_blofin_orders(symbol: Optional[str] = None):
    if not blofin.connected:
        return {"error": "BloFin not configured"}
    return {"orders": await blofin.get_open_orders(symbol)}


# ---------------------------------------------------------------------------
# Risk engine
# ---------------------------------------------------------------------------
class KellyRequest(BaseModel):
    win_rate: float
    avg_win: float
    avg_loss: float
    leverage: int = 5
    total_collateral: float = 10000
    allocated_margin: float = 0
    zone_tier_weight: float = 1.0


@app.post("/api/risk/kelly")
async def compute_kelly(req: KellyRequest):
    return kelly_sizer.compute(
        win_rate=req.win_rate,
        avg_win=req.avg_win,
        avg_loss=req.avg_loss,
        leverage=req.leverage,
        total_collateral=req.total_collateral,
        allocated_margin=req.allocated_margin,
        zone_tier_weight=req.zone_tier_weight,
    )


@app.get("/api/risk/leverage")
async def get_leverage_status():
    summary = await pm_client.get_margin_summary()
    cb_state = circuit_breaker.state.to_dict()
    return {"margin": summary, "circuit_breaker": cb_state}


class SimulateRequest(BaseModel):
    symbol: str
    side: str
    entry_price: float
    leverage: int = 5
    margin_mode: str = "isolated"


@app.post("/api/risk/simulate")
async def simulate_position(req: SimulateRequest):
    liq = estimate_liquidation_price(
        entry_price=req.entry_price,
        leverage=req.leverage,
        position_side=req.side.upper(),
        margin_mode=req.margin_mode,
    )
    gate_params = macro_gate.get_adjusted_params(
        base_confidence=0.65,
        base_position_pct=0.02,
        base_leverage=req.leverage,
    )
    return {"liquidation": liq, "macro_adjusted": gate_params}


@app.get("/api/risk/margin")
async def get_margin_summary():
    return await pm_client.get_margin_summary()


# ---------------------------------------------------------------------------
# Macro gate
# ---------------------------------------------------------------------------
@app.get("/api/macro/calendar")
async def get_macro_calendar():
    events = calendar.get_next_n(10)
    return {"events": [e.to_dict() for e in events]}


@app.get("/api/macro/status")
async def get_macro_status():
    return macro_gate.evaluate().to_dict()


class SentinelUpdate(BaseModel):
    event_tier: int
    event_name: str
    minutes_until: int
    market_context: str = ""


@app.post("/api/macro/sentinel-update")
async def sentinel_update(data: SentinelUpdate):
    ok = sentinel_bridge.process_update(data.model_dump())
    return {"processed": ok}


# ---------------------------------------------------------------------------
# Market sentiment - Fear & Greed + aggregate cross-symbol long/short
# ---------------------------------------------------------------------------
_sentiment_cache: dict = {"data": None, "ts": 0.0}


@app.get("/api/sentiment")
async def get_market_sentiment():
    """Aggregate market-wide sentiment: Bitcoin Fear & Greed Index plus the
    cross-symbol average L/S ratio. Used by the header market bar and the
    Alerts tab's sentiment gauge. 60s TTL cache."""
    now = time.time()
    if _sentiment_cache["data"] and now - _sentiment_cache["ts"] < 60:
        return _sentiment_cache["data"]

    fg = await macro_feed.fetch_fear_greed()

    # Aggregate L/S across default symbols (already tracked, cheap).
    ls_values: list[float] = []
    top_ls_values: list[float] = []
    for sym in DEFAULT_SYMBOLS:
        meter = squeeze_meters.get(sym)
        if not meter:
            continue
        try:
            await meter.fetch_ls_ratio()
            await meter.fetch_top_trader_ls()
        except Exception:
            pass
        if getattr(meter, "_ls_ratio", None):
            ls_values.append(float(meter._ls_ratio))
        if getattr(meter, "_top_ls_ratio", None):
            top_ls_values.append(float(meter._top_ls_ratio))

    def _avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    ls_avg = _avg(ls_values)
    top_ls_avg = _avg(top_ls_values)

    long_pct = None
    if ls_avg and ls_avg > 0:
        long_pct = round(ls_avg / (1 + ls_avg) * 100, 1)

    result = {
        "fear_greed": fg,
        "ls_ratio_avg": ls_avg,
        "top_trader_ls_avg": top_ls_avg,
        "long_pct_24h": long_pct,
        "short_pct_24h": round(100 - long_pct, 1) if long_pct is not None else None,
        "sample_symbols": DEFAULT_SYMBOLS,
        "generated_at": now,
    }
    _sentiment_cache["data"] = result
    _sentiment_cache["ts"] = now
    return result


# ---------------------------------------------------------------------------
# Macro release calendar - recurring high-impact events with days-ahead
# ---------------------------------------------------------------------------
def _upcoming_fred_releases(now_ts: float, horizon_days: int = 45) -> list[dict]:
    """Procedurally generate the next-N high-impact US macro events.

    This is a deterministic schedule (FOMC approx every 6 weeks, CPI mid-month,
    NFP 1st Friday, PPI mid-month). Good enough for an awareness countdown -
    exact times are refined when FRED/investing.com feeds are wired.
    """
    from datetime import datetime, timedelta, timezone
    now = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    horizon = now + timedelta(days=horizon_days)

    events: list[tuple[datetime, str, str, str]] = []

    # Monthly: CPI (approx 2nd Tue-Thu), NFP (1st Fri), PPI (day after CPI)
    for month_offset in range(0, 3):
        y = now.year + ((now.month - 1 + month_offset) // 12)
        m = ((now.month - 1 + month_offset) % 12) + 1
        # 1st Friday of the month - NFP (Non-Farm Payrolls)
        d = datetime(y, m, 1, 13, 30, tzinfo=timezone.utc)  # 08:30 ET ~= 13:30 UTC
        while d.weekday() != 4:  # Friday
            d += timedelta(days=1)
        events.append((d, "NFP (Non-Farm Payrolls)", "Tier1_Critical", "US labour market print - direct USD/risk driver"))
        # 2nd Wednesday ~= CPI release day
        cpi = datetime(y, m, 1, 13, 30, tzinfo=timezone.utc)
        cnt = 0
        while cnt < 2:
            if cpi.weekday() == 2:
                cnt += 1
                if cnt == 2:
                    break
            cpi += timedelta(days=1)
        events.append((cpi, "CPI Inflation", "Tier1_Critical", "Headline + core CPI - primary inflation gauge"))
        # PPI - day after CPI
        events.append((cpi + timedelta(days=1), "PPI Inflation", "Tier2_High", "Producer price index - upstream inflation signal"))

    # FOMC - approximately every 6 weeks on a Wednesday. Seed a rolling list.
    # 2026 FOMC meetings (public schedule): Jan 28, Mar 18, Apr 29, Jun 17, Jul 29, Sep 16, Oct 28, Dec 9.
    fomc_2026 = [
        (2026, 1, 28), (2026, 3, 18), (2026, 4, 29), (2026, 6, 17),
        (2026, 7, 29), (2026, 9, 16), (2026, 10, 28), (2026, 12, 9),
    ]
    for (yy, mm, dd) in fomc_2026:
        events.append((
            datetime(yy, mm, dd, 18, 0, tzinfo=timezone.utc),
            "FOMC Rate Decision",
            "Tier1_Critical",
            "Fed interest rate + dot plot + Powell press conference",
        ))

    # Filter + sort
    horizon_ts = horizon.timestamp()
    out = []
    for (dt, name, tier, desc) in events:
        if dt < now:
            continue
        if dt.timestamp() > horizon_ts:
            continue
        delta_sec = dt.timestamp() - now_ts
        out.append({
            "name": name,
            "tier": tier,
            "timestamp": dt.timestamp(),
            "datetime_utc": dt.isoformat(),
            "days_until": round(delta_sec / 86400, 1),
            "hours_until": round(delta_sec / 3600, 1),
            "description": desc,
        })
    out.sort(key=lambda e: e["timestamp"])
    return out[:12]


@app.get("/api/macro/releases")
async def get_macro_releases():
    """Next high-impact US macro releases with days-ahead countdown."""
    return {"releases": _upcoming_fred_releases(time.time())}


# ---------------------------------------------------------------------------
# AI synthesis
# ---------------------------------------------------------------------------
@app.post("/api/ai/brief")
async def generate_ai_brief():
    sym = DEFAULT_SYMBOLS[0]
    engine = zone_engines.get(sym)
    zones = engine.detect_zones() if engine else []
    funding = await funding_trackers[sym].fetch_all() if sym in funding_trackers else {}
    oi = await oi_trackers[sym].fetch_all() if sym in oi_trackers else {}
    squeeze = squeeze_meters[sym].compute(
        funding_rate_pct=funding.get("weighted_rate_pct", 0),
        oi_change_pct=oi_trackers[sym].get_trend().get("change_pct", 0) if sym in oi_trackers else 0,
    ) if sym in squeeze_meters else {}
    gate_status = macro_gate.evaluate().to_dict()

    await news_feed.fetch_all()  # populates the feed cache read below
    headline_texts = news_feed.get_headline_texts()

    brief = await brief_generator.generate_brief(
        golden_zones=zones,
        funding_data=funding,
        oi_data=oi,
        squeeze_data=squeeze,
        macro_status=gate_status,
        news_headlines=headline_texts,
    )

    save_brief(brief["brief"], brief, brief["generated_at"])

    if telegram.configured:
        await telegram.send_alert("morning_brief", brief)

    return brief


@app.get("/api/ai/last-brief")
async def get_last_ai_brief():
    brief = get_last_brief()
    if not brief:
        return {"brief": None, "message": "No brief generated yet"}
    return brief


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
@app.get("/api/alerts")
async def get_alerts(limit: int = Query(default=50)):
    return {"alerts": get_recent_alerts(limit)}


@app.post("/api/alerts/telegram/test")
async def test_telegram():
    ok = await telegram.send_message("Nexus test alert - system operational.")
    return {"sent": ok, "configured": telegram.configured}


# ---------------------------------------------------------------------------
# Alpha Engine
# ---------------------------------------------------------------------------
_alpha_cache: dict = {}
_alpha_locks: dict = {}
_ALPHA_TTL_SEC = 5.0

_dvol_cache: dict = {}
_DVOL_TTL_SEC = 60.0


async def _dvol_cached(currency: str, hours: int) -> dict:
    """Deribit DVOL with a 60s cache + 5s hard timeout. DVOL moves slowly;
    per-request uncached awaits were a major alpha/matrix latency source."""
    key = (currency, hours)
    now = time.time()
    hit = _dvol_cache.get(key)
    if hit and now - hit[0] < _DVOL_TTL_SEC:
        return hit[1]
    try:
        dv = await asyncio.wait_for(
            deribit_feed.get_dvol(currency=currency, hours=hours), timeout=5.0,
        )
    except Exception:  # noqa: BLE001 - timeout/venue error → stale-or-empty
        return hit[1] if hit else {}
    if isinstance(dv, dict) and dv:
        _dvol_cache[key] = (now, dv)
        return dv
    return hit[1] if hit else {}


@app.get("/api/alpha/{symbol}")
async def get_alpha(symbol: str):
    """Response-cached + single-flight - the tab polls this route; cold
    computation is expensive, so overlapping polls share one run."""
    symbol = symbol.upper()
    now = time.time()
    hit = _alpha_cache.get(symbol)
    if hit and now - hit[0] < _ALPHA_TTL_SEC:
        return hit[1]
    lock = _alpha_locks.setdefault(symbol, asyncio.Lock())
    async with lock:
        hit = _alpha_cache.get(symbol)
        if hit and time.time() - hit[0] < _ALPHA_TTL_SEC:
            return hit[1]
        payload = await _compute_alpha(symbol)
        _alpha_cache[symbol] = (time.time(), payload)
        return payload


async def _compute_alpha(symbol: str):
    _ensure_symbol_engines(symbol)
    engine = alpha_engines.get(symbol)
    if not engine:
        raise HTTPException(500, f"Engine init failed for {symbol}")

    mark = binance_data.mark_prices.get(symbol, {})

    # Get supporting data
    # In-memory funding read - same payload shape fetch_all() returned (it
    # delegated to get_weighted_rate()); the network refresh belongs to the
    # 30s oi_poll_loop, not the request path.
    funding = funding_trackers[symbol].get_weighted_rate() if symbol in funding_trackers else {}
    cvd_data = cvd_computers[symbol].get_multi_timeframe() if symbol in cvd_computers else {}
    oi_trend = oi_trackers[symbol].get_trend() if symbol in oi_trackers else {}

    # Get regime
    try:
        klines = list(binance_data.kline_history.get(symbol, []))
        if len(klines) >= 20:
            closes = [float(k.get("close", 0)) for k in klines]
            volumes = [float(k.get("volume", 0)) for k in klines]
            highs = [float(k.get("high", 0)) for k in klines]
            lows = [float(k.get("low", 0)) for k in klines]
            regime_data = regime_classifier.classify(closes, volumes, highs, lows)
        else:
            regime_data = {"regime": "insufficient_data", "confidence": 0}
    except Exception:
        regime_data = {"regime": "unknown", "confidence": 0}

    # Get smart money data
    smt = smart_money_trackers.get(symbol)
    smart_money_data = {}
    if smt:
        smart_money_data = smt.get_whale_activity()

    # ----- P1 factor inputs -----
    # tsmom needs ~73+ 1h closes; pull from kline_history (1h DEFAULT_INTERVAL).
    closes_1h = []
    try:
        kh = list(binance_data.kline_history.get(symbol, []))
        closes_1h = [float(k.get("close", 0)) for k in kh if k.get("close")]
    except Exception:
        closes_1h = []
    tsmom_payload = None
    try:
        if len(closes_1h) >= 75:
            from backend.computation.factors.tsmom import compute_tsmom as _tsmom
            tsmom_payload = _tsmom(closes_1h)
    except Exception as _e:
        logger.debug("tsmom %s: %s", symbol, _e)

    # funding_carry needs FundingTracker history populated - already by oi_poller.
    funding_carry_payload = None
    try:
        ft = funding_trackers.get(symbol)
        if ft:
            funding_carry_payload = ft.carry_signal()
    except Exception as _e:
        logger.debug("funding_carry %s: %s", symbol, _e)

    # oi_momentum from OITracker (history seeded by oi_poller, ~30s cadence).
    # Adaptive cascade: prefer the institutional-standard 4h/7d but fall back
    # progressively when baseline samples are insufficient. With 30s polling
    # the smallest variant (5m/2h) starts producing signal within ~25 minutes
    # of startup vs ~20 hours for the canonical config.
    oi_momentum_payload = None
    try:
        ot = oi_trackers.get(symbol)
        if ot:
            cascade = [
                ("4h", "7d"),     # institutional standard - needs ~20h
                ("1h", "24h"),    # ~5h
                ("15m", "6h"),    # ~1.5h
                ("5m", "2h"),     # ~25 min
                ("1m", "30m"),    # ~5 min - earliest signal
            ]
            for w, base in cascade:
                payload = ot.roc_zscore(window=w, baseline_window=base)
                if (payload or {}).get("reason") not in ("baseline too thin", "insufficient_data", "no valid reference OI"):
                    oi_momentum_payload = payload
                    break
            else:
                # All variants thin - surface the smallest so reason+samples is informative.
                oi_momentum_payload = payload
    except Exception as _e:
        logger.debug("oi_momentum %s: %s", symbol, _e)

    # Squeeze risk (P1-A) - regime-aware contribution to composite alpha.
    # Reuses the same inputs as the brief endpoint: weighted funding, OI ROC,
    # current regime classification, optional VPIN toxicity amplification.
    squeeze_payload: Optional[Dict[str, Any]] = None
    try:
        meter = squeeze_meters.get(symbol)
        if meter:
            f_rate_pct = float((funding or {}).get("weighted_rate_pct", 0.0) or 0.0)
            oi_change_pct = 0.0
            try:
                ot = oi_trackers.get(symbol)
                if ot:
                    trend = ot.get_trend()
                    oi_change_pct = float((trend or {}).get("change_pct", 0.0) or 0.0)
            except Exception:
                pass
            vpin_now: Optional[float] = None
            try:
                vt = vpin_trackers.get(symbol) if "vpin_trackers" in globals() else None
                if vt:
                    snap = vt.snapshot()
                    vpin_now = getattr(snap, "running", None)
            except Exception:
                vpin_now = None
            squeeze_payload = meter.compute(
                funding_rate_pct=f_rate_pct,
                oi_change_pct=oi_change_pct,
                regime=(regime_data or {}).get("regime"),
                vpin=vpin_now,
            )
    except Exception as _e:
        logger.debug("squeeze %s: %s", symbol, _e)

    # Deribit DVOL for vol_regime - replaces the previous {} which permanently
    # capped vol_regime confidence at 0. We pull a 24h slice; alpha_engine reads
    # `deribit_data["latest"]` if present, otherwise falls back to realized vol.
    deribit_payload: dict = {}
    try:
        currency = "BTC" if symbol.startswith("BTC") else ("ETH" if symbol.startswith("ETH") else None)
        if currency:
            dv = await _dvol_cached(currency, hours=24)
            if isinstance(dv, dict) and dv:
                deribit_payload = dv
    except Exception as _e:
        logger.debug("deribit dvol %s: %s", symbol, _e)

    # Generate composite
    try:
        composite = engine.generate_composite(
            funding_data=funding,
            cvd_data=cvd_data,
            oi_data=oi_trend,
            deribit_data=deribit_payload,
            klines=list(binance_data.kline_history.get(symbol, [])),
            funding_carry_data=funding_carry_payload,
            tsmom_data=tsmom_payload,
            oi_momentum_data=oi_momentum_payload,
            squeeze_data=squeeze_payload,
            # Cross-exchange spread expects {"venue": {"mid_price": float}}.
            # Previously we passed raw order_books / mark_prices so the engine's
            # `v.get("mid_price")` lookup always returned 0 → "Too few valid
            # prices" → permanent 0%/0% confidence on cross_exchange_spread.
            # Compute the mid here, prefer book top-of-book, fall back to mark.
            all_exchange_data=_build_cross_exchange_mids(symbol),
        )
    except Exception as e:
        logger.error(f"Alpha engine error for {symbol}: {e}")
        composite = {
            "composite_score": 0,
            "composite_direction": "neutral",
            "confidence": 0,
            "agreement_ratio": 0,
            "signals": [],
        }

    return {
        "symbol": symbol,
        **composite,
        "regime": regime_data,
        # Key mapping fixed - SmartMoneyTracker.get_whale_activity() returns
        # `net_whale_flow`, `total_whale_trades`, `recent_trades`, `total_whale_usd`.
        # Old code looked up `net_flow_usd` / `large_trade_count` / `recent_large_trades`
        # which never existed → smart-money card stuck at $0 / 0 whales.
        # Also normalize per-whale records (usd→usd_value, ts→time) for the frontend.
        "smart_money": {
            "net_flow": smart_money_data.get("net_whale_flow", 0),
            "total_usd": smart_money_data.get("total_whale_usd", 0),
            "buy_usd": smart_money_data.get("buy_usd", 0),
            "sell_usd": smart_money_data.get("sell_usd", 0),
            "intensity": smart_money_data.get("intensity", "low"),
            "large_trade_count": smart_money_data.get("total_whale_trades", 0),
            "avg_size_usd": smart_money_data.get("avg_whale_size_usd", 0),
            "recent_whales": [
                {
                    "price": w.get("price"),
                    "qty": w.get("qty"),
                    "usd_value": w.get("usd"),
                    "side": w.get("side"),
                    "time": w.get("ts"),
                }
                for w in (smart_money_data.get("recent_trades") or [])[-10:]
            ],
        },
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data_age_ms": int((time.time() - mark.get("timestamp", time.time())) * 1000) if mark.get("timestamp") else 0,
        },
    }


# ---------------------------------------------------------------------------
# Liquidity Heatmap
# ---------------------------------------------------------------------------
@app.get("/api/heatmap/{symbol}")
async def get_heatmap(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)
    hmap = heatmaps.get(symbol)
    if not hmap:
        raise HTTPException(500, f"Heatmap init failed for {symbol}")

    # Feed latest aggregated snapshot across all exchanges so walls and
    # depth profile reflect institutional cross-venue liquidity, not just
    # Binance. Falls back to Binance-only if no other feed is up yet.
    books_by_exchange = {}
    if symbol in binance_data.order_books:
        books_by_exchange["binance"] = binance_data.order_books[symbol]
    if symbol in okx_data.order_books:
        books_by_exchange["okx"] = okx_data.order_books[symbol]
    if symbol in mexc_data.order_books:
        books_by_exchange["mexc"] = mexc_data.order_books[symbol]
    if books_by_exchange:
        hmap.add_aggregated_snapshot(books_by_exchange, time.time())

    inst_cfg = INSTITUTIONAL_DEPTH.get(symbol, INSTITUTIONAL_DEPTH["DEFAULT"])
    heatmap_data = hmap.generate_heatmap(
        lookback_minutes=30,
        min_usd_per_cell=inst_cfg["min_usd_per_level"],
    )
    inst_depth = hmap.get_institutional_depth_profile(
        bin_usd=inst_cfg["bin_usd"],
        min_usd_per_level=inst_cfg["min_usd_per_level"],
        max_levels_each_side=inst_cfg["max_levels_each_side"],
        near_pct=inst_cfg["near_pct"],
    )
    depth = hmap.get_depth_profile()
    walls = hmap.detect_liquidity_walls()
    voids = hmap.detect_liquidity_voids()

    # Real liquidation clusters from actual binance/okx feeds - replaces
    # hardcoded multiplier stub. Bucket events into 0.5% price bands relative
    # to the current mark, sum USD, classify side. If no liquidations in the
    # window we return [] (frontend renders no clusters - no fake data).
    mark = binance_data.mark_prices.get(symbol, {}).get("mark_price", 0)
    liq_clusters = []
    if mark > 0:
        cutoff_ms = (time.time() - 3600) * 1000  # last 60 min
        bucket_pct = 0.005  # 0.5% bands
        buckets: dict[tuple[int, str], float] = {}
        # Pull from binance liquidations (Binance side: BUY = short liq, SELL = long liq)
        for ev in list(binance_data.liquidations.get(symbol, [])):
            if ev.get("time", 0) < cutoff_ms or ev.get("price", 0) <= 0:
                continue
            price = float(ev["price"])
            usd = float(ev.get("usd_value", price * float(ev.get("qty", 0))))
            band_idx = int((price / mark - 1.0) / bucket_pct)
            side = "short" if ev.get("side") == "BUY" else "long"
            key = (band_idx, side)
            buckets[key] = buckets.get(key, 0.0) + usd
        # Pull from OKX liquidations if available (best-effort)
        try:
            okx_liqs = okx_data.liquidations.get(symbol, []) if hasattr(okx_data, "liquidations") else []
            for ev in list(okx_liqs):
                if ev.get("time", 0) < cutoff_ms or ev.get("price", 0) <= 0:
                    continue
                price = float(ev["price"])
                usd = float(ev.get("usd_value", price * float(ev.get("qty", 0))))
                band_idx = int((price / mark - 1.0) / bucket_pct)
                side = "long" if ev.get("side", "").lower() in ("sell", "long") else "short"
                key = (band_idx, side)
                buckets[key] = buckets.get(key, 0.0) + usd
        except Exception:
            pass
        for (idx, side), usd in buckets.items():
            band_mid = mark * (1.0 + (idx + 0.5) * bucket_pct)
            liq_clusters.append({
                "price": round(band_mid, 2),
                "estimated_size_usd": round(usd, 2),
                "side": side,
                "band_pct": round((idx + 0.5) * bucket_pct * 100, 3),
            })
        liq_clusters.sort(key=lambda c: -c["estimated_size_usd"])
        liq_clusters = liq_clusters[:30]

    # Transform depth profile for frontend
    depth_profile = {
        "bid_prices": [b["price"] for b in depth.get("bids", [])],
        "bid_cumulative": [b["cumulative"] for b in depth.get("bids", [])],
        "ask_prices": [a["price"] for a in depth.get("asks", [])],
        "ask_cumulative": [a["cumulative"] for a in depth.get("asks", [])],
        "imbalance": depth.get("imbalance", 0),
    }

    return {
        **heatmap_data,
        "liquidation_clusters": liq_clusters,
        "walls": walls,
        "voids": voids,
        "current_price": mark,
        "depth_profile": depth_profile,
        "institutional_depth": inst_depth,
        "exchanges": sorted(books_by_exchange.keys()),
        "exchange_count": len(books_by_exchange),
    }


# ---------------------------------------------------------------------------
# Order Flow
# ---------------------------------------------------------------------------
@app.get("/api/orderflow/{symbol}")
async def get_orderflow(symbol: str):
    symbol = symbol.upper()
    _ensure_symbol_engines(symbol)

    # CVD
    cvd_data = cvd_computers[symbol].get_multi_timeframe() if symbol in cvd_computers else {}

    # Absorption detection - read from the background sampler's cached result
    # (P0 fix: was a single-shot inline heuristic that almost never fired).
    absorption_data = {"detected": False, "side": "none", "strength": 0.0}
    det = absorption_detectors.get(symbol)
    if det is not None:
        last = getattr(det, "_last_result", None)
        if last:
            absorption_data = {
                "detected": True,
                "side": "bid" if last.get("type") == "bid_absorption" else "ask",
                "strength": float(last.get("strength", 0.0) or 0.0),
                "buy_sell_ratio": last.get("buy_sell_ratio"),
                "volume_usd": last.get("total_volume_usd"),
                "sample_age_s": round(time.time() - getattr(det, "_last_sample_ts", time.time()), 1),
            }

    # Large trades from smart money tracker
    smt = smart_money_trackers.get(symbol)
    large_trades = []
    if smt:
        large_trades = smt.get_large_trade_flow()

    # Volume profile - KEY MAPPING FIX: deque stores `price/qty/is_buyer_maker`
    # (see binance_ws.update_agg_trade), the previous code read nonexistent
    # `q/p/m` keys and produced a permanent 0/0 → fake 50/50 split.
    trades = list(binance_data.agg_trades.get(symbol, []))
    buy_vol = 0.0
    sell_vol = 0.0
    for t in trades:
        price = float(t.get("price", 0) or 0)
        qty = float(t.get("qty", 0) or 0)
        if price <= 0 or qty <= 0:
            continue
        qty_usd = qty * price
        if t.get("is_buyer_maker", True):
            sell_vol += qty_usd
        else:
            buy_vol += qty_usd

    total_vol = buy_vol + sell_vol
    # Strict null contract: no trades → null, never 0.5.
    trade_flow_ratio = (buy_vol / total_vol) if total_vol > 1e-9 else None

    # OI change - null when history thin (was returning 0 which masks warmup)
    oi_change: float | None = None
    oi_samples = 0
    if symbol in oi_trackers:
        trend = oi_trackers[symbol].get_trend()
        if trend.get("trend") != "insufficient_data":
            oi_change = float(trend.get("change_pct", 0) or 0)
        oi_samples = int(trend.get("samples", 0) or 0)

    # Active trade source - tells the frontend which venue is currently
    # feeding CVD/SmartMoney (binance/okx/mexc/None when all stale).
    from backend.ingestion.trade_router import select_source as _select_source
    active_source = _select_source(symbol, ws_manager=ws_manager)

    return {
        "symbol": symbol,
        "cvd": cvd_data,
        "absorption": absorption_data,
        "large_trades": large_trades[:20],
        "trade_flow_ratio": trade_flow_ratio,
        "volume_profile": {
            "buy_volume": buy_vol if total_vol > 0 else None,
            "sell_volume": sell_vol if total_vol > 0 else None,
            "total_volume": total_vol if total_vol > 0 else None,
            "trade_count": len(trades),
        },
        "oi_change_1h": oi_change,
        "oi_samples": oi_samples,
        "source": {
            "trades": active_source,
            "venues_active": ws_manager.status if hasattr(ws_manager, "status") else None,
        },
    }


@app.get("/api/risk/kelly/{symbol}")
async def get_kelly_for_symbol(
    symbol: str,
    leverage: int = Query(5, ge=1, le=125),
    total_collateral: float = Query(10000.0, ge=0),
):
    """Per-symbol Kelly with **realized** stats - replaces the previous
    same-for-all stub.

    win_rate / avg_win / avg_loss are derived from the symbol's recent kline
    log-returns (no journal dependency, works pre-trade). atr_pct and
    realized_vol_24h come from the same kline_history so the vol-adjusted
    branch of KellySizer.compute() activates.
    """
    import math as _m
    sym = symbol.upper()
    _ensure_symbol_engines(sym)
    hist = list(binance_data.kline_history.get(sym, []))
    closes = [float(c.get("close", 0)) for c in hist if c.get("close")]
    highs = [float(c.get("high", 0)) for c in hist if c.get("high")]
    lows = [float(c.get("low", 0)) for c in hist if c.get("low")]

    if len(closes) < 30:
        return {
            "symbol": sym,
            "warmup": True,
            "samples": len(closes),
            "needed": 30,
            "reason": "Insufficient klines for realized stats",
        }

    returns = [
        _m.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    wins = [r for r in returns if r > 0]
    losses = [abs(r) for r in returns if r < 0]
    win_rate = (len(wins) / len(returns)) if returns else 0.5
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0

    # ATR%: average true range over last 14 bars / last close
    atr_pct = None
    if len(highs) >= 15 and len(closes) >= 15:
        trs: list[float] = []
        for i in range(1, 15):
            tr = max(
                highs[-i] - lows[-i],
                abs(highs[-i] - closes[-i - 1]),
                abs(lows[-i] - closes[-i - 1]),
            )
            trs.append(tr)
        if trs and closes[-1] > 0:
            atr_pct = (sum(trs) / len(trs)) / closes[-1]

    # 24h realized vol - last 24 1-h returns std (or fewer scaled to 24)
    realized_vol_24h = None
    if len(returns) >= 24:
        last24 = returns[-24:]
        mu = sum(last24) / len(last24)
        var = sum((x - mu) ** 2 for x in last24) / max(len(last24) - 1, 1)
        realized_vol_24h = _m.sqrt(var) * _m.sqrt(24)

    # Correlation map for filter - best-effort, optional
    correlations = None
    open_positions: list[str] = []
    try:
        if len(closes) >= 30:
            pair_data = correlation_matrix(
                {s: list(binance_data.kline_history.get(s, [])) for s in DEFAULT_SYMBOLS},
                lookback=96,
            )
            correlations = pair_data.get("pairs") if isinstance(pair_data, dict) else None
    except Exception:
        correlations = None

    out = kelly_sizer.compute(
        win_rate=win_rate,
        avg_win=avg_win if avg_win > 0 else 0.01,
        avg_loss=avg_loss if avg_loss > 0 else 0.01,
        leverage=leverage,
        total_collateral=total_collateral,
        allocated_margin=0,
        zone_tier_weight=1.0,
        symbol=sym,
        atr_pct=atr_pct,
        realized_vol_24h=realized_vol_24h,
        correlations=correlations,
        open_positions=open_positions,
    )
    out["symbol"] = sym
    out["realized_stats"] = {
        "win_rate": round(win_rate, 4),
        "avg_win_pct": round(avg_win * 100, 4),
        "avg_loss_pct": round(avg_loss * 100, 4),
        "atr_pct": round(atr_pct * 100, 4) if atr_pct else None,
        "realized_vol_24h_pct": round(realized_vol_24h * 100, 4) if realized_vol_24h else None,
        "samples": len(returns),
    }
    return out


@app.get("/api/risk/var/{symbol}")
async def get_var_for_symbol(
    symbol: str,
    position_usd: float = Query(10000.0, ge=0),
    leverage: float = Query(1.0, ge=1.0, le=125.0),
    lookback: int = Query(200, ge=30, le=1000),
):
    """Three-method VaR ensemble (historical / parametric-t / Monte Carlo)
    on the symbol's recent kline log-returns. ``ensemble_max`` is the
    Kelly denominator the position sizer consumes."""
    sym = symbol.upper()
    hist = list(binance_data.kline_history.get(sym, []))
    closes = [float(c.get("close", 0)) for c in hist if c.get("close")]
    closes = closes[-lookback:]
    if len(closes) < 31:
        return {"symbol": sym, "error": "Insufficient data (need 30+ closes)", "samples": len(closes)}
    import math
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    out = var_calculator.compute(returns, position_usd=position_usd, leverage=leverage)
    out["symbol"] = sym
    out["samples"] = len(returns)
    return out


# ---------------------------------------------------------------------------
# Chart data - klines / candles / symbol discovery / ticker / indicators
# Works for ANY Binance USDT-M perpetual pair (not just DEFAULT_SYMBOLS).
# Fetched on-demand via the existing urllib-with-SSL-fallback helper.
# ---------------------------------------------------------------------------
import json as _json
import ssl as _ssl
import urllib.request as _url
import concurrent.futures as _cf


_VALID_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
_symbols_cache: dict = {"updated": 0, "symbols": []}
_klines_cache: dict = {}  # {(symbol,interval): (ts, data)}
_KLINES_TTL_SEC = 2.0


def _binance_fut_get(path: str, timeout: int = 10):
    """Blocking Binance USDT-M futures REST call with SSL fallback. Run in thread."""
    url = f"https://fapi.binance.com{path}"
    try:
        req = _url.Request(url, headers={"User-Agent": "Nexus/0.3"})
        with _url.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read())
    except Exception:
        pass
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        req = _url.Request(url, headers={"User-Agent": "Nexus/0.3"})
        with _url.urlopen(req, timeout=timeout, context=ctx) as resp:
            return _json.loads(resp.read())
    except Exception:
        return None


async def _afetch(path: str, timeout: int = 10):
    loop = asyncio.get_event_loop()
    with _cf.ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(pool, lambda: _binance_fut_get(path, timeout))


@app.get("/api/klines/{symbol}")
async def get_klines(
    symbol: str,
    interval: str = Query("1h", description="Binance interval: 1m,5m,15m,1h,4h,1d,..."),
    limit: int = Query(500, ge=10, le=1500),
):
    """Return OHLCV candles for any Binance USDT-M perpetual pair.
    Short-TTL cached per (symbol, interval) to smooth rapid tab-switching."""
    symbol = symbol.upper()
    if interval not in _VALID_INTERVALS:
        raise HTTPException(400, f"Invalid interval. Allowed: {sorted(_VALID_INTERVALS)}")

    key = (symbol, interval, limit)
    now = time.time()
    cached = _klines_cache.get(key)
    if cached and now - cached[0] < _KLINES_TTL_SEC:
        return cached[1]

    data = await _afetch(f"/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if not data or not isinstance(data, list):
        raise HTTPException(502, "Binance klines fetch failed")

    candles = []
    for k in data:
        if not isinstance(k, list) or len(k) < 6:
            continue
        candles.append({
            "time": int(k[0] // 1000),             # seconds - lightweight-charts convention
            "open_time": int(k[0]),                 # ms
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": int(k[6]) if len(k) > 6 else int(k[0]),
            "quote_volume": float(k[7]) if len(k) > 7 else 0.0,
            "trades": int(k[8]) if len(k) > 8 else 0,
        })

    payload = {"symbol": symbol, "interval": interval, "count": len(candles), "candles": candles}
    _klines_cache[key] = (now, payload)
    return payload


@app.get("/api/symbols/search")
async def search_symbols(q: str = Query("", description="Partial pair filter, e.g. 'btc'")):
    """Autocomplete for the global pair search input. Proxies Binance exchangeInfo
    and filters USDT-M PERPETUAL contracts in TRADING status. Cached for 5 minutes."""
    now = time.time()
    if now - _symbols_cache["updated"] > 300 or not _symbols_cache["symbols"]:
        info = await _afetch("/fapi/v1/exchangeInfo")
        if not info or "symbols" not in info:
            raise HTTPException(502, "exchangeInfo fetch failed")
        out = []
        for s in info["symbols"]:
            if (
                s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
                and s.get("quoteAsset") == "USDT"
            ):
                out.append({
                    "symbol": s["symbol"],
                    "base": s.get("baseAsset", ""),
                    "quote": s.get("quoteAsset", "USDT"),
                    "pricePrecision": int(s.get("pricePrecision", 2)),
                    "qtyPrecision": int(s.get("quantityPrecision", 3)),
                })
        # Sort: put majors first, then alpha
        MAJORS = {"BTCUSDT": 0, "ETHUSDT": 1, "SOLUSDT": 2, "BNBUSDT": 3, "XRPUSDT": 4}
        out.sort(key=lambda x: (MAJORS.get(x["symbol"], 999), x["symbol"]))
        _symbols_cache["updated"] = now
        _symbols_cache["symbols"] = out

    query = (q or "").strip().upper()
    pool = _symbols_cache["symbols"]
    # No hard cap - Binance USDT-M has ~500 pairs; majors are sorted first so
    # the first screenful is always the liquid ones. With a query, return every
    # match.
    if not query:
        filtered = pool
    else:
        filtered = [s for s in pool if query in s["symbol"] or query in s["base"]]

    return {"query": q, "count": len(filtered), "total": len(pool), "results": filtered}


@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    """24h ticker stats for any Binance futures symbol - price, 24h change,
    volume, high/low. Used by the header ticker strip for the active pair."""
    symbol = symbol.upper()
    data = await _afetch(f"/fapi/v1/ticker/24hr?symbol={symbol}")
    if not data or "symbol" not in data:
        raise HTTPException(502, "ticker fetch failed")
    try:
        return {
            "symbol": data["symbol"],
            "last_price": float(data.get("lastPrice", 0) or 0),
            "price_change": float(data.get("priceChange", 0) or 0),
            "price_change_pct": float(data.get("priceChangePercent", 0) or 0),
            "high_24h": float(data.get("highPrice", 0) or 0),
            "low_24h": float(data.get("lowPrice", 0) or 0),
            "open_24h": float(data.get("openPrice", 0) or 0),
            "volume_24h": float(data.get("volume", 0) or 0),
            "quote_volume_24h": float(data.get("quoteVolume", 0) or 0),
            "trades_24h": int(data.get("count", 0) or 0),
            "timestamp": int(data.get("closeTime", 0) or 0),
        }
    except Exception as e:
        raise HTTPException(502, f"ticker parse failed: {e}")


# ---------- Technical indicators (RSI / EMA / BB / MACD / Stoch / ADX / ATR) ----------
#
# These implementations match TradingView / Binance conventions so scores are
# comparable with the platforms users cross-check against. Key choices:
#
#   * EMA: canonical 2/(N+1) alpha, seeded with the SMA of the first N values
#     (most platforms do this - a single-value seed distorts the early curve).
#   * Bollinger: 20-period SMA ± 2 × population stdev. ✓ TV-standard.
#   * RSI: Wilder's smoothing (1/N equivalent). Pre-period positions are NaN so
#     confluence scoring never mistakes warm-up padding for a real reading.
#   * MACD: 12/26 EMA diff, signal = 9-EMA of MACD, histogram = macd - signal.
#   * Stochastic: raw %K = (C - LL) / (HH - LL) × 100, %D = 3-SMA of %K.
#   * ATR / ADX: Wilder's smoothing (alpha = 1/N), NOT generic EMA. This is the
#     definition on TradingView / Binance / Bloomberg. Using EMA produces a
#     noticeably different curve.
#   * Pivots: computed from the PRIOR closed candle (conventional intraday use).

import math


def _ema_series(values, period: int):
    """Canonical EMA with SMA seed for the first `period` values.

    Before the seed completes, outputs NaN so consumers can distinguish
    "still warming up" from a real value.
    """
    n = len(values)
    if n == 0 or period <= 0:
        return []
    if n < period:
        return [float("nan")] * n
    k = 2.0 / (period + 1)
    out = [float("nan")] * (period - 1)
    seed = sum(values[:period]) / period
    out.append(seed)
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _wilder_series(values, period: int):
    """Wilder's smoothing (a.k.a. RMA / Modified Moving Average).

    Equivalent to EMA with alpha = 1/N. Used by TradingView and Binance for
    RSI, ATR, and ADX. Seeded with the simple mean of the first N values.
    """
    n = len(values)
    if n == 0 or period <= 0:
        return []
    if n < period:
        return [float("nan")] * n
    out = [float("nan")] * (period - 1)
    seed = sum(values[:period]) / period
    out.append(seed)
    prev = seed
    for v in values[period:]:
        prev = (prev * (period - 1) + v) / period
        out.append(prev)
    return out


def _sma_series(values, period: int):
    """Simple moving average. Outputs NaN until `period` values have been seen."""
    n = len(values)
    if n == 0 or period <= 0:
        return []
    out = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i < period - 1:
            out.append(float("nan"))
        else:
            out.append(s / period)
    return out


def _rsi(values, period: int = 14):
    """Wilder's RSI. Returns NaN for positions before the indicator warms up."""
    n = len(values)
    if n < period + 1:
        return [float("nan")] * n
    gains, losses = [], []
    for i in range(1, n):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    # First averages use simple mean of first `period` gains/losses.
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    rsis = [float("nan")] * period  # indices 0..period-1 of `values` are warmup
    rs = (avg_g / avg_l) if avg_l > 0 else float("inf")
    rsis.append(100.0 if math.isinf(rs) else 100 - (100 / (1 + rs)))
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        rs = (avg_g / avg_l) if avg_l > 0 else float("inf")
        rsis.append(100.0 if math.isinf(rs) else 100 - (100 / (1 + rs)))
    # len(rsis) should now equal n
    return rsis


def _bollinger(values, period: int = 20, k: float = 2.0):
    """Classic Bollinger Bands - SMA ± k × population stdev over `period`.

    Warm-up positions return NaN (not a partial-window approximation, which
    produces misleading early values).
    """
    n = len(values)
    mid = _sma_series(values, period)
    upper, lower = [], []
    for i in range(n):
        if i < period - 1 or math.isnan(mid[i]):
            upper.append(float("nan"))
            lower.append(float("nan"))
            continue
        window = values[i - period + 1: i + 1]
        m = mid[i]
        var = sum((x - m) ** 2 for x in window) / len(window)  # population
        sd = var ** 0.5
        upper.append(m + k * sd)
        lower.append(m - k * sd)
    return upper, mid, lower


def _macd(values, fast: int = 12, slow: int = 26, signal: int = 9):
    if len(values) < slow:
        nan = [float("nan")] * len(values)
        return nan, nan, nan
    ef = _ema_series(values, fast)
    es = _ema_series(values, slow)
    macd = [
        (a - b) if (not math.isnan(a) and not math.isnan(b)) else float("nan")
        for a, b in zip(ef, es)
    ]
    # Signal line is EMA of macd - but EMA wants numeric input. Replace NaNs
    # with the first real value's position by slicing.
    first_real = next((i for i, v in enumerate(macd) if not math.isnan(v)), -1)
    if first_real < 0:
        return macd, macd, macd
    sig_part = _ema_series(macd[first_real:], signal)
    sig = [float("nan")] * first_real + sig_part
    hist = [
        (m - s) if (not math.isnan(m) and not math.isnan(s)) else float("nan")
        for m, s in zip(macd, sig)
    ]
    return macd, sig, hist


def _stoch(highs, lows, closes, k_period: int = 14, d_period: int = 3):
    """Stochastic %K/%D. Warm-up outputs NaN for unambiguous UI rendering."""
    k_vals = []
    n = len(closes)
    for i in range(n):
        if i < k_period - 1:
            k_vals.append(float("nan"))
            continue
        start = i - k_period + 1
        hh = max(highs[start:i + 1])
        ll = min(lows[start:i + 1])
        denom = hh - ll
        if denom <= 0:
            k_vals.append(50.0)  # flat range → midpoint (canonical handling)
        else:
            k_vals.append((closes[i] - ll) / denom * 100.0)
    # D = SMA of K - but only over the FINITE tail of K (otherwise NaN
    # warmup entries would poison the rolling sum forever).
    first = next((i for i, v in enumerate(k_vals) if not math.isnan(v)), -1)
    if first < 0:
        return k_vals, [float("nan")] * n
    d_tail = _sma_series(k_vals[first:], d_period)
    d_vals = [float("nan")] * first + d_tail
    return k_vals, d_vals


def _atr(highs, lows, closes, period: int = 14):
    """Wilder's ATR - the definition used by TradingView / Binance / Bloomberg.

    (Generic EMA produces a DIFFERENT number. Using Wilder here is what keeps
    our ATR identical to the values traders see on Binance.)
    """
    n = len(closes)
    if n < 2:
        return [float("nan")] * n
    trs = [float("nan")]  # TR[0] is undefined (needs prior close)
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    # Wilder on TR[1:], then pad front with NaN so length == n.
    wilder = _wilder_series(trs[1:], period)
    return [float("nan")] + wilder


def _adx(highs, lows, closes, period: int = 14):
    """Wilder's ADX - properly uses Wilder smoothing on TR, +DM, -DM, and DX."""
    n = len(closes)
    if n < period + 1:
        return [float("nan")] * n
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr_s = _wilder_series(trs, period)
    plus_ds = _wilder_series(plus_dm, period)
    minus_ds = _wilder_series(minus_dm, period)
    plus_di, minus_di = [], []
    for p, m, a in zip(plus_ds, minus_ds, atr_s):
        if math.isnan(a) or a <= 0:
            plus_di.append(float("nan"))
            minus_di.append(float("nan"))
        else:
            plus_di.append(100 * p / a)
            minus_di.append(100 * m / a)
    dx = []
    for p, m in zip(plus_di, minus_di):
        if math.isnan(p) or math.isnan(m):
            dx.append(float("nan"))
            continue
        denom = p + m
        dx.append(100 * abs(p - m) / denom if denom > 0 else 0.0)
    # ADX = Wilder smoothing of DX once DX has warmed up.
    first = next((i for i, v in enumerate(dx) if not math.isnan(v)), -1)
    if first < 0:
        return [float("nan")] * n
    adx_part = _wilder_series(dx[first:], period)
    # align to length `n`: prepend 1 (for i=0) + `first` NaNs
    return [float("nan")] * (1 + first) + adx_part


def _vwap_series(highs, lows, closes, volumes):
    """Cumulative VWAP over the fetched window. For intraday contexts a
    proper "session anchored" VWAP would reset at each UTC day boundary -
    but the terminal typically fetches at most a few days of intraday data
    and traders want a single continuous reference line across that slice.

    Returns a series the same length as `closes`; position [i] is the
    volume-weighted average of the typical price (H+L+C)/3 from index 0
    through i inclusive.
    """
    n = len(closes)
    out = []
    cum_pv = 0.0
    cum_v = 0.0
    for i in range(n):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        v = volumes[i] if i < len(volumes) else 0.0
        cum_pv += tp * v
        cum_v += v
        out.append((cum_pv / cum_v) if cum_v > 0 else float("nan"))
    return out


def _obv_series(closes, volumes):
    """On-Balance Volume. Cumulative sum of signed volume: +v on up closes,
    -v on down closes, 0 on unchanged. Seeded at 0 for index 0.
    """
    n = len(closes)
    out = [0.0] * n
    for i in range(1, n):
        v = volumes[i] if i < len(volumes) else 0.0
        if closes[i] > closes[i - 1]:
            out[i] = out[i - 1] + v
        elif closes[i] < closes[i - 1]:
            out[i] = out[i - 1] - v
        else:
            out[i] = out[i - 1]
    return out


def _ichimoku(highs, lows, closes,
              tenkan_p: int = 9, kijun_p: int = 26, senkou_b_p: int = 52,
              disp: int = 26):
    """Ichimoku Cloud components. Returns (tenkan, kijun, senkou_a, senkou_b,
    chikou) all aligned to `closes` length.

    Conventions:
      - tenkan[i]   = (max(high[i-8..i]) + min(low[i-8..i])) / 2
      - kijun[i]    = (max(high[i-25..i]) + min(low[i-25..i])) / 2
      - senkou_a[i] = (tenkan[i-26] + kijun[i-26]) / 2          (displaced +26)
      - senkou_b[i] = (max(high[i-77..i-26]) + min(low[i-77..i-26])) / 2
      - chikou[i]   = close[i+26]   (future close displayed 26 bars back)
    Warm-up values are NaN.
    """
    n = len(closes)
    def _donchian_mid(period: int):
        out = [float("nan")] * n
        for i in range(period - 1, n):
            hh = max(highs[i - period + 1: i + 1])
            ll = min(lows[i - period + 1: i + 1])
            out[i] = (hh + ll) / 2.0
        return out
    tenkan = _donchian_mid(tenkan_p)
    kijun = _donchian_mid(kijun_p)
    # senkou_a shifted forward `disp` bars: value AT index i comes from
    # the pair at index i-disp (earlier). Positions [0..disp-1] are NaN.
    senkou_a = [float("nan")] * n
    for i in range(disp, n):
        t = tenkan[i - disp]; k = kijun[i - disp]
        if math.isnan(t) or math.isnan(k):
            continue
        senkou_a[i] = (t + k) / 2.0
    # senkou_b: donchian(52) shifted forward `disp`.
    b_mid = _donchian_mid(senkou_b_p)
    senkou_b = [float("nan")] * n
    for i in range(disp, n):
        if math.isnan(b_mid[i - disp]):
            continue
        senkou_b[i] = b_mid[i - disp]
    # chikou: close shifted BACK `disp` bars (so chikou[i] = close[i+disp]).
    # For the last `disp` positions there is no future close available → NaN.
    chikou = [float("nan")] * n
    for i in range(0, n - disp):
        chikou[i] = closes[i + disp]
    return tenkan, kijun, senkou_a, senkou_b, chikou


def _stddev_channel(values, period: int = 100, k: float = 2.0):
    """Linear-regression standard-deviation channel (TradingView convention).

    For each position i (after warm-up), fit a least-squares line over the
    last `period` values; the midline at i is the regression value at i,
    and upper/lower are midline ± k * stdev of residuals within the window.

    Returns (upper, middle, lower) arrays aligned to `values` length.
    """
    n = len(values)
    upper = [float("nan")] * n
    middle = [float("nan")] * n
    lower = [float("nan")] * n
    if period < 2 or n < period:
        return upper, middle, lower
    # Precompute x-sums that are constant across windows.
    xs = list(range(period))
    x_mean = sum(xs) / period
    x_var = sum((x - x_mean) ** 2 for x in xs)  # constant denom
    for i in range(period - 1, n):
        window = values[i - period + 1: i + 1]
        y_mean = sum(window) / period
        # slope = Σ(x-x̄)(y-ȳ) / Σ(x-x̄)²
        num = sum((xs[j] - x_mean) * (window[j] - y_mean) for j in range(period))
        slope = num / x_var if x_var > 0 else 0.0
        intercept = y_mean - slope * x_mean
        # midline value at the END of the window (x = period - 1)
        mid_val = intercept + slope * (period - 1)
        # residuals stdev (population) across the whole window
        resid2 = 0.0
        for j in range(period):
            pred = intercept + slope * xs[j]
            resid2 += (window[j] - pred) ** 2
        sd = (resid2 / period) ** 0.5
        middle[i] = mid_val
        upper[i] = mid_val + k * sd
        lower[i] = mid_val - k * sd
    return upper, middle, lower


def _pivots_classic(ph: float, pl: float, pc: float):
    """Classic (a.k.a. Floor) pivot levels from prior period H/L/C."""
    p = (ph + pl + pc) / 3.0
    rng = ph - pl
    return {
        "r3": ph + 2 * (p - pl),
        "r2": p + rng,
        "r1": 2 * p - pl,
        "pivot": p,
        "s1": 2 * p - ph,
        "s2": p - rng,
        "s3": pl - 2 * (ph - p),
    }


def _pivots_camarilla(ph: float, pl: float, pc: float):
    """Camarilla pivots. The 1.1 constant is the Camarilla equation constant.
    L3/H3 and L4/H4 are the most-watched intraday breakout/reversal zones.
    """
    r = ph - pl
    return {
        "h4": pc + r * 1.1 / 2.0,
        "h3": pc + r * 1.1 / 4.0,
        "h2": pc + r * 1.1 / 6.0,
        "h1": pc + r * 1.1 / 12.0,
        "pivot": (ph + pl + pc) / 3.0,
        "l1": pc - r * 1.1 / 12.0,
        "l2": pc - r * 1.1 / 6.0,
        "l3": pc - r * 1.1 / 4.0,
        "l4": pc - r * 1.1 / 2.0,
    }


def _pivots_woodie(ph: float, pl: float, pc: float):
    """Woodie pivots. Weights the close more heavily than Classic.
    (Strict Woodie uses the CURRENT session's open; for continuous intraday
    data we approximate with the prior close, which is the common fallback.)
    """
    p = (ph + pl + 2 * pc) / 4.0
    r = ph - pl
    return {
        "r2": p + r,
        "r1": 2 * p - pl,
        "pivot": p,
        "s1": 2 * p - ph,
        "s2": p - r,
    }


def _safe(v, digits: int | None = None):
    """NaN/inf-safe JSON serialization. Returns None for non-finite numbers."""
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(fv):
        return None
    return round(fv, digits) if digits is not None else fv


def _safe_series(arr):
    """Replace NaN/inf with None so JSON encoding succeeds and charts draw gaps."""
    out = []
    for v in arr:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(fv if math.isfinite(fv) else None)
    return out


@app.get("/api/indicators/{symbol}")
async def get_indicators(
    symbol: str,
    interval: str = Query("1h"),
    limit: int = Query(500, ge=50, le=1500),
):
    """Compute a full technical-indicator snapshot for any pair. Returns
    latest values AND series (so the frontend can overlay them on a chart).

    Algorithms match TradingView / Binance conventions (Wilder's smoothing
    for RSI / ATR / ADX; EMA seeded with SMA; Bollinger uses population
    stdev). NaNs from warm-up are serialized as null so the chart shows a
    clean gap before the indicator is ready.
    """
    data = await get_klines(symbol, interval, limit)
    candles = data["candles"]
    if len(candles) < 30:
        raise HTTPException(422, "not enough candles for indicators")

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0.0) for c in candles]
    times = [c["time"] for c in candles]

    ema50 = _ema_series(closes, 50)
    ema200 = _ema_series(closes, 200) if len(closes) >= 200 else _ema_series(closes, len(closes) // 2)
    upper, mid, lower = _bollinger(closes, 20, 2.0)
    rsi14 = _rsi(closes, 14)
    macd_line, macd_sig, macd_hist = _macd(closes, 12, 26, 9)
    k_line, d_line = _stoch(highs, lows, closes, 14, 3)
    atr14 = _atr(highs, lows, closes, 14)
    adx14 = _adx(highs, lows, closes, 14)
    vwap = _vwap_series(highs, lows, closes, volumes)
    obv = _obv_series(closes, volumes)
    ichi_tenkan, ichi_kijun, ichi_sa, ichi_sb, ichi_chikou = _ichimoku(highs, lows, closes)
    # Std-dev channel sized for the dataset - 100 is a common default but
    # small windows would produce NaN-only output, so floor at period=20.
    stdc_period = 100 if len(closes) >= 100 else max(20, len(closes) // 3)
    sdc_upper, sdc_mid, sdc_lower = _stddev_channel(closes, stdc_period, 2.0)

    # Pivots - computed from the PREVIOUS closed candle. Using the
    # in-progress last candle (highs[-1]) makes pivots jitter every tick
    # while the current bar is still forming.
    if len(candles) >= 2:
        ph, pl, pc = highs[-2], lows[-2], closes[-2]
    else:
        ph, pl, pc = highs[-1], lows[-1], closes[-1]
    classic_p = _pivots_classic(ph, pl, pc)
    camarilla_p = _pivots_camarilla(ph, pl, pc)
    woodie_p = _pivots_woodie(ph, pl, pc)
    pivot = classic_p["pivot"]
    r1, r2 = classic_p["r1"], classic_p["r2"]
    s1, s2 = classic_p["s1"], classic_p["s2"]

    last_close = closes[-1]

    # Last-value helpers. Use the latest FINITE value so "latest.rsi_14" still
    # makes sense even when the last few positions are warmup or the series
    # was just created.
    def last_finite(arr):
        for v in reversed(arr):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv):
                return fv
        return None

    ema50_last = last_finite(ema50)
    ema200_last = last_finite(ema200)
    mid_last = last_finite(mid)
    upper_last = last_finite(upper)
    lower_last = last_finite(lower)
    macd_last = last_finite(macd_line)
    sig_last = last_finite(macd_sig)
    hist_last = last_finite(macd_hist)
    k_last = last_finite(k_line)
    d_last = last_finite(d_line)
    atr_last = last_finite(atr14)
    adx_last = last_finite(adx14)
    rsi_last = last_finite(rsi14)
    vwap_last = last_finite(vwap)
    obv_last = last_finite(obv)
    tenkan_last = last_finite(ichi_tenkan)
    kijun_last = last_finite(ichi_kijun)
    senkou_a_last = last_finite(ichi_sa)
    senkou_b_last = last_finite(ichi_sb)
    sdc_mid_last = last_finite(sdc_mid)
    sdc_upper_last = last_finite(sdc_upper)
    sdc_lower_last = last_finite(sdc_lower)

    bb_width_pct = (
        ((upper_last - lower_last) / mid_last * 100)
        if (upper_last is not None and lower_last is not None and mid_last)
        else 0.0
    )

    ema_trend = "neutral"
    if ema50_last is not None and ema200_last is not None:
        ema_trend = "bullish" if ema50_last > ema200_last else "bearish"

    ema_cross = None
    if ema50_last is not None and ema200_last is not None:
        ema_cross = ema50_last - ema200_last

    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "count": len(candles),
        "last_close": last_close,
        "latest": {
            "rsi_14": _safe(rsi_last, 2),
            "ema_50": _safe(ema50_last, 6),
            "ema_200": _safe(ema200_last, 6),
            "ema_cross": _safe(ema_cross, 6),
            "ema_trend": ema_trend,
            "bb_upper": _safe(upper_last, 6),
            "bb_middle": _safe(mid_last, 6),
            "bb_lower": _safe(lower_last, 6),
            "bb_width_pct": _safe(bb_width_pct, 4) or 0.0,
            "macd": _safe(macd_last, 6),
            "macd_signal": _safe(sig_last, 6),
            "macd_hist": _safe(hist_last, 6),
            "macd_bias": (
                "bullish" if (hist_last is not None and hist_last > 0)
                else ("bearish" if hist_last is not None else None)
            ),
            "stoch_k": _safe(k_last, 2),
            "stoch_d": _safe(d_last, 2),
            "atr_14": _safe(atr_last, 6),
            "adx_14": _safe(adx_last, 2),
            "adx_regime": "trending" if (adx_last is not None and adx_last >= 25) else "ranging",
            "vwap": _safe(vwap_last, 6),
            "obv": _safe(obv_last, 2),
            "ichimoku_tenkan": _safe(tenkan_last, 6),
            "ichimoku_kijun": _safe(kijun_last, 6),
            "ichimoku_senkou_a": _safe(senkou_a_last, 6),
            "ichimoku_senkou_b": _safe(senkou_b_last, 6),
            "ichimoku_bias": (
                "bullish" if (senkou_a_last is not None and senkou_b_last is not None and senkou_a_last > senkou_b_last)
                else ("bearish" if (senkou_a_last is not None and senkou_b_last is not None) else None)
            ),
            "stddev_channel_upper": _safe(sdc_upper_last, 6),
            "stddev_channel_middle": _safe(sdc_mid_last, 6),
            "stddev_channel_lower": _safe(sdc_lower_last, 6),
        },
        "pivots": {
            # Back-compat: flat classic keys so existing frontend callers
            # keep working. New nested `variants` block exposes all three.
            "r2": _safe(r2, 6),
            "r1": _safe(r1, 6),
            "pivot": _safe(pivot, 6),
            "s1": _safe(s1, 6),
            "s2": _safe(s2, 6),
            "variants": {
                "classic": {k: _safe(v, 6) for k, v in classic_p.items()},
                "camarilla": {k: _safe(v, 6) for k, v in camarilla_p.items()},
                "woodie": {k: _safe(v, 6) for k, v in woodie_p.items()},
            },
        },
        "series": {
            "time": times,
            "ema_50": _safe_series(ema50),
            "ema_200": _safe_series(ema200),
            "bb_upper": _safe_series(upper),
            "bb_middle": _safe_series(mid),
            "bb_lower": _safe_series(lower),
            "rsi_14": _safe_series(rsi14),
            "macd": _safe_series(macd_line),
            "macd_signal": _safe_series(macd_sig),
            "macd_hist": _safe_series(macd_hist),
            "vwap": _safe_series(vwap),
            "obv": _safe_series(obv),
            "ichimoku_tenkan": _safe_series(ichi_tenkan),
            "ichimoku_kijun": _safe_series(ichi_kijun),
            "ichimoku_senkou_a": _safe_series(ichi_sa),
            "ichimoku_senkou_b": _safe_series(ichi_sb),
            "ichimoku_chikou": _safe_series(ichi_chikou),
            "stddev_channel_upper": _safe_series(sdc_upper),
            "stddev_channel_middle": _safe_series(sdc_mid),
            "stddev_channel_lower": _safe_series(sdc_lower),
        },
    }


# ---------------------------------------------------------------------------
# Research AI brief - narrative synthesis from indicators + market context.
#
# This is rule-based (not an LLM) so the output is deterministic, fast, and
# reproducible. Traders want the SAME intel every time they regen a brief
# for the same market state. If an LLM is later wired in, the shape here
# stays stable: five sections of plain text + a small structured payload
# (numeric levels/signals) the UI can bind directly.
# ---------------------------------------------------------------------------
def _brief_bias(ind: dict) -> tuple[str, list[str]]:
    latest = ind.get("latest", {})
    votes: list[str] = []
    trend = latest.get("ema_trend")
    if trend == "bullish":
        votes.append(f"EMA 50 > EMA 200 (cross: +{_safe(latest.get('ema_cross'), 4)})")
    elif trend == "bearish":
        votes.append(f"EMA 50 < EMA 200 (cross: {_safe(latest.get('ema_cross'), 4)})")
    ichi = latest.get("ichimoku_bias")
    if ichi:
        votes.append(f"Ichimoku cloud {ichi}")
    macd = latest.get("macd_bias")
    if macd:
        votes.append(f"MACD histogram {macd}")
    adx = latest.get("adx_14")
    regime = latest.get("adx_regime")
    if adx is not None:
        votes.append(f"ADX {adx:.1f} - market is {regime}")
    # Dominant direction from the votes
    bull = sum(1 for v in votes if "bullish" in v.lower() or "EMA 50 > EMA 200" in v)
    bear = sum(1 for v in votes if "bearish" in v.lower() or "EMA 50 < EMA 200" in v)
    if bull > bear + 1:
        head = "BULLISH"
    elif bear > bull + 1:
        head = "BEARISH"
    else:
        head = "NEUTRAL"
    return head, votes


def _brief_levels(ind: dict) -> list[str]:
    out: list[str] = []
    pivots = (ind.get("pivots") or {})
    variants = (pivots.get("variants") or {}).get("classic") or pivots
    last = ind.get("last_close")
    if last is not None:
        out.append(f"Last close: {last:.6g}")
    order = [("R3", "r3"), ("R2", "r2"), ("R1", "r1"), ("Pivot", "pivot"), ("S1", "s1"), ("S2", "s2"), ("S3", "s3")]
    for lbl, key in order:
        v = variants.get(key)
        if v is None:
            continue
        out.append(f"{lbl}: {float(v):.6g}")
    latest = ind.get("latest", {})
    for key, lbl in [("bb_upper", "BB Upper"), ("bb_lower", "BB Lower"),
                     ("stddev_channel_upper", "SDC Upper"), ("stddev_channel_lower", "SDC Lower"),
                     ("vwap", "VWAP")]:
        v = latest.get(key)
        if v is not None:
            out.append(f"{lbl}: {float(v):.6g}")
    return out


def _brief_signals(ind: dict) -> list[str]:
    out: list[str] = []
    latest = ind.get("latest", {})
    rsi = latest.get("rsi_14")
    if rsi is not None:
        if rsi >= 70: out.append(f"RSI 14 {rsi:.1f} - overbought")
        elif rsi <= 30: out.append(f"RSI 14 {rsi:.1f} - oversold")
        else: out.append(f"RSI 14 {rsi:.1f} - neutral range")
    k, d = latest.get("stoch_k"), latest.get("stoch_d")
    if k is not None and d is not None:
        if k > 80 and d > 80: out.append(f"Stochastic {k:.0f}/{d:.0f} - overbought")
        elif k < 20 and d < 20: out.append(f"Stochastic {k:.0f}/{d:.0f} - oversold")
        elif k > d: out.append(f"Stochastic %K {k:.0f} > %D {d:.0f} - bullish cross")
        else: out.append(f"Stochastic %K {k:.0f} ≤ %D {d:.0f} - bearish cross")
    hist = latest.get("macd_hist")
    if hist is not None:
        direction = "expanding bullish" if hist > 0 else "expanding bearish"
        out.append(f"MACD histogram {hist:+.4f} ({direction})")
    vwap = latest.get("vwap")
    close = ind.get("last_close")
    if vwap and close:
        diff_pct = (close - vwap) / vwap * 100
        side = "above" if diff_pct > 0 else "below"
        out.append(f"Price {abs(diff_pct):.2f}% {side} VWAP")
    return out


def _brief_macro(brief: dict) -> list[str]:
    out: list[str] = []
    gate = (brief or {}).get("macro_gate") or {}
    if gate.get("is_restricted"):
        out.append(f"Macro gate RESTRICTED - {gate.get('active_event', 'event pending')}")
    else:
        out.append("Macro gate OPEN - no restrictive events")
    cap = gate.get("leverage_cap")
    if cap is not None:
        out.append(f"Recommended leverage cap: {cap}x")
    funding = (brief or {}).get("funding") or {}
    rate = funding.get("weighted_rate_pct")
    if rate is not None:
        cls = funding.get("classification") or ""
        out.append(f"Weighted funding rate {rate:+.4f}% ({cls})")
    regime = (brief or {}).get("regime") or {}
    reg = regime.get("regime")
    if reg:
        conf = regime.get("confidence")
        conf_pct = f"{(float(conf) * 100):.0f}%" if conf is not None else "?"
        out.append(f"Regime: {str(reg).replace('_', ' ')} (confidence {conf_pct})")
    return out


def _brief_risk(ind: dict, brief: dict) -> list[str]:
    out: list[str] = []
    latest = ind.get("latest", {})
    atr = latest.get("atr_14")
    close = ind.get("last_close")
    if atr and close:
        stop_mult = 1.5
        out.append(f"Suggested ATR stop: ±{atr * stop_mult:.4f} ({stop_mult}× ATR)")
        out.append(f"Projected R 1% risk position size ≈ {close / (atr * stop_mult) * 0.01:.4f} units")
    squeeze = (brief or {}).get("squeeze_risk") or {}
    if squeeze:
        ls = squeeze.get("long_squeeze_risk_pct")
        ss = squeeze.get("short_squeeze_risk_pct")
        lvl = (squeeze.get("alert_level") or "normal").upper()
        if ls is not None and ss is not None:
            out.append(f"Squeeze risk - long {ls:.0f}% / short {ss:.0f}% ({lvl})")
    adx = latest.get("adx_14")
    if adx is not None and adx < 20:
        out.append("ADX < 20 → avoid trend-following entries; prefer mean-reversion")
    elif adx is not None and adx >= 40:
        out.append("ADX ≥ 40 → strong trend; avoid counter-trend fades")
    return out


@app.get("/api/research/brief/{symbol}")
async def get_research_brief(
    symbol: str,
    interval: str = Query("1h"),
):
    """Structured narrative brief for the Research tab. Combines indicator
    snapshot + order-book/derivatives brief into five short sections the
    UI renders as collapsible cards.

    Response shape:
      {
        "symbol", "interval", "generated_at",
        "bias":    { "headline": "BULLISH" | "BEARISH" | "NEUTRAL", "bullets": [...] },
        "levels":  { "bullets": [...] },
        "signals": { "bullets": [...] },
        "macro":   { "bullets": [...] },
        "risk":    { "bullets": [...] },
      }
    """
    # Pull indicators (from our own endpoint helper) and brief concurrently.
    try:
        ind_payload = await get_indicators(symbol, interval=interval, limit=500)
    except HTTPException:
        raise
    try:
        brief_payload = await get_brief(symbol)
    except Exception:
        brief_payload = {}

    bias_head, bias_bullets = _brief_bias(ind_payload)
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "generated_at": int(time.time()),
        "bias":    {"headline": bias_head, "bullets": bias_bullets},
        "levels":  {"bullets": _brief_levels(ind_payload)},
        "signals": {"bullets": _brief_signals(ind_payload)},
        "macro":   {"bullets": _brief_macro(brief_payload)},
        "risk":    {"bullets": _brief_risk(ind_payload, brief_payload)},
    }


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8001, reload=True)
