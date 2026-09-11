"""
Nexus - Binance Futures aggTrade REST fallback poller

The combined-stream WebSocket subscribes to `@aggTrade` per symbol, but on some
networks (notably PLDT/PH and some corporate proxies) Binance throttles or
silently drops the aggTrade frames while leaving `@depth20` and
`@markPrice@1s` flowing. The visible symptom: order book updates fine,
funding/L-S ratio fine (REST), but TAPE SPEED is 0.0 tps and CVD/Smart Money
stay at $0 indefinitely.

This poller monitors WS trade staleness and, when the gap exceeds 10 s for a
DEFAULT_SYMBOLS pair, polls the public REST `/fapi/v1/aggTrades` endpoint at
~2 s cadence and dedupes/inserts new trades into `binance_data.agg_trades`.
The downstream pipeline (trade_router → CVD/SmartMoney/VPIN/etc.) is unchanged.

REST quota math: 5 default symbols × 0.5 Hz × 1 weight = 2.5 weight/s ≈ 150
weight/min. Binance Futures REST limit is 2400 weight/min - well below.

When WS recovers (trade arrives < 5 s old) the poller automatically pauses
that symbol until the WS goes silent again. No double-counting because we
filter by `last_seen_id` per symbol.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

from backend.config import BINANCE_FUTURES_BASE, BINANCE_FUTURES_ENDPOINTS
from backend.ingestion.binance_ws import binance_data
from backend.ingestion.rate_guard import (
    BINANCE_FUTURES_HOST,
    note_http_error,
    record_success,
    should_skip,
)

logger = logging.getLogger("nexus.agg_trade_rest_poller")

# Per-symbol last seen aggTrade ID - Binance returns monotonic int IDs.
_last_seen_id: dict[str, int] = {}

# Activation threshold: WS staleness in seconds before REST kicks in.
WS_STALE_THRESHOLD_S = 10.0
# REST poll cadence per symbol (per-tick).
POLL_INTERVAL_S = 2.0
# How many trades to pull per request (Binance max 1000; 100 keeps it cheap).
TRADES_PER_REQUEST = 100


def _fetch_sync(url: str) -> Optional[list]:
    """REST GET with strict→permissive SSL fallback (matches kline pattern).

    On an HTTP 418/429 the ban deadline is registered with the shared rate
    guard so the loop suspends instead of extending the ban.
    """
    def _attempt(ctx=None) -> Optional[list]:
        req = urllib.request.Request(url, headers={"User-Agent": "Nexus/0.3"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            return json.loads(resp.read())

    try:
        return _attempt()
    except urllib.error.HTTPError as http_err:
        # Read the body so the guard can parse "banned until <epoch>".
        try:
            body = http_err.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        if note_http_error(BINANCE_FUTURES_HOST, http_err.code, body):
            return None  # rate-limited - do not retry, let the loop back off
    except Exception:
        pass
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return _attempt(ctx)
    except urllib.error.HTTPError as http_err:
        try:
            body = http_err.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        note_http_error(BINANCE_FUTURES_HOST, http_err.code, body)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("aggTrades REST fetch failed: %s", exc)
        return None


async def _fetch_async(url: str, executor: ThreadPoolExecutor) -> Optional[list]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _fetch_sync, url)


def _ws_is_stale(symbol: str) -> bool:
    last = binance_data.last_update.get(f"{symbol}_trades")
    if last is None:
        return True
    return (time.time() - last) > WS_STALE_THRESHOLD_S


async def _poll_one(symbol: str, executor: ThreadPoolExecutor) -> int:
    """Poll one symbol once. Returns count of new trades inserted."""
    # Build URL with `fromId` if we've seen any, else just the latest N.
    last_id = _last_seen_id.get(symbol)
    if last_id is not None:
        url = (
            f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['agg_trades']}"
            f"?symbol={symbol}&fromId={last_id + 1}&limit={TRADES_PER_REQUEST}"
        )
    else:
        url = (
            f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['agg_trades']}"
            f"?symbol={symbol}&limit={TRADES_PER_REQUEST}"
        )

    data = await _fetch_async(url, executor)
    if not isinstance(data, list) or not data:
        return 0

    inserted = 0
    deque_ref = binance_data.agg_trades[symbol]
    for rec in data:
        # Binance aggTrades schema:
        #   { "a": aggId, "p": "price", "q": "qty", "f": firstId, "l": lastId,
        #     "T": ts_ms, "m": isBuyerMaker }
        try:
            agg_id = int(rec.get("a", 0))
        except (TypeError, ValueError):
            continue
        if last_id is not None and agg_id <= last_id:
            continue
        try:
            trade = {
                "price": float(rec["p"]),
                "qty": float(rec["q"]),
                "time": int(rec["T"]),
                "is_buyer_maker": bool(rec["m"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        deque_ref.append(trade)
        _last_seen_id[symbol] = agg_id
        inserted += 1

    if inserted > 0:
        # A successful fetch clears any soft-backoff so the next transient 429
        # restarts the schedule from the base delay.
        record_success(BINANCE_FUTURES_HOST)
        # Mark the trades feed fresh so trade_router sees a healthy "binance"
        # source again (degradation factor reads `last_update[*_trades]` via
        # _volume_factor and ws_manager gap_report).
        binance_data.last_update[f"{symbol}_trades"] = time.time()

    return inserted


async def agg_trade_rest_loop(symbols: Iterable[str]) -> None:
    """Forever loop. Polls REST aggTrades only when WS is silent for a symbol."""
    syms = list(symbols)
    executor = ThreadPoolExecutor(max_workers=min(8, max(2, len(syms))))
    logger.info("aggTrade REST fallback armed for %s symbols", len(syms))
    consecutive_failures: dict[str, int] = {}
    while True:
        try:
            # Binance has us rate-limit banned - sit out entirely until it lifts.
            if should_skip(BINANCE_FUTURES_HOST):
                await asyncio.sleep(POLL_INTERVAL_S)
                continue
            tasks = []
            polled: list[str] = []
            for sym in syms:
                if not _ws_is_stale(sym):
                    consecutive_failures.pop(sym, None)
                    continue
                polled.append(sym)
                tasks.append(_poll_one(sym, executor))
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for sym, res in zip(polled, results):
                    if isinstance(res, Exception):
                        consecutive_failures[sym] = consecutive_failures.get(sym, 0) + 1
                        if consecutive_failures[sym] in (1, 5, 25):
                            logger.warning(
                                "aggTrade REST %s err (#%d): %s",
                                sym, consecutive_failures[sym], res,
                            )
                    elif isinstance(res, int) and res > 0:
                        logger.debug("aggTrade REST %s: +%d trades", sym, res)
        except Exception as exc:  # noqa: BLE001
            logger.error("agg_trade_rest_loop tick: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_S)
