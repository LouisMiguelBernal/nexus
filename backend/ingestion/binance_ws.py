"""
Nexus - Binance Futures USDT-M WebSocket Feed
Primary data source: order book, aggTrades, liquidations, klines, mark price.
"""

import asyncio
import logging
import time
import ssl
from collections import defaultdict, deque
from typing import Dict, List, Optional

from backend.config import (
    WS_BINANCE_FUTURES, DEFAULT_SYMBOLS, DEFAULT_INTERVAL,
    BINANCE_FUTURES_BASE, BINANCE_FUTURES_ENDPOINTS,
)
from backend.ingestion.ws_manager import WSConnection, WSManager

logger = logging.getLogger("nexus.binance_ws")


class BinanceFuturesData:
    """Holds real-time Binance Futures data in memory."""

    def __init__(self):
        # Order book snapshots per symbol: {symbol: {"bids": [...], "asks": [...]}}
        self.order_books: Dict[str, dict] = {}
        # Aggregated trades for CVD: {symbol: deque(maxlen=10000)}
        self.agg_trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        # Liquidation events: {symbol: deque(maxlen=500)}
        self.liquidations: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        # Latest klines per symbol+interval: {symbol: {interval: [ohlcv]}}
        self.klines: Dict[str, Dict[str, list]] = defaultdict(dict)
        # Historical closed klines per symbol: {symbol: deque(maxlen=200)}
        self.kline_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        # Mark price + funding: {symbol: {"mark_price": float, "funding_rate": float, "next_funding": int}}
        self.mark_prices: Dict[str, dict] = {}
        # Last update timestamps
        self.last_update: Dict[str, float] = {}

    def update_order_book(self, symbol: str, data: dict):
        self.order_books[symbol] = {
            "bids": [[float(p), float(q)] for p, q in data.get("b", [])],
            "asks": [[float(p), float(q)] for p, q in data.get("a", [])],
            "timestamp": data.get("E", time.time() * 1000),
        }
        self.last_update[f"{symbol}_ob"] = time.time()

    def update_agg_trade(self, symbol: str, data: dict):
        trade = {
            "price": float(data["p"]),
            "qty": float(data["q"]),
            "time": data["T"],
            "is_buyer_maker": data["m"],  # True = sell pressure, False = buy pressure
        }
        self.agg_trades[symbol].append(trade)
        self.last_update[f"{symbol}_trades"] = time.time()

    def update_liquidation(self, symbol: str, data: dict):
        order = data.get("o", {})
        liq = {
            "symbol": order.get("s", symbol),
            "side": order.get("S", ""),  # BUY = short liq, SELL = long liq
            "price": float(order.get("p", 0)),
            "qty": float(order.get("q", 0)),
            "usd_value": float(order.get("p", 0)) * float(order.get("q", 0)),
            "time": order.get("T", int(time.time() * 1000)),
        }
        self.liquidations[symbol].append(liq)
        self.last_update[f"{symbol}_liq"] = time.time()

    def update_kline(self, symbol: str, data: dict):
        k = data.get("k", {})
        interval = k.get("i", "15m")
        candle = {
            "open_time": k.get("t"),
            "open": float(k.get("o", 0)),
            "high": float(k.get("h", 0)),
            "low": float(k.get("l", 0)),
            "close": float(k.get("c", 0)),
            "volume": float(k.get("v", 0)),
            "close_time": k.get("T"),
            "quote_volume": float(k.get("q", 0)),
            "trades": k.get("n", 0),
            "is_closed": k.get("x", False),
        }
        self.klines[symbol][interval] = candle
        self.last_update[f"{symbol}_kline_{interval}"] = time.time()

        # Accumulate closed candles into history for regime classifier
        if candle["is_closed"]:
            history = self.kline_history[symbol]
            # Avoid duplicates (same open_time)
            if not history or history[-1]["open_time"] != candle["open_time"]:
                history.append(candle)

    def update_mark_price(self, symbol: str, data: dict):
        self.mark_prices[symbol] = {
            "mark_price": float(data.get("p", 0)),
            "index_price": float(data.get("i", 0)),
            "funding_rate": float(data.get("r", 0)),
            "next_funding_time": data.get("T", 0),
            "timestamp": data.get("E", int(time.time() * 1000)),
        }
        self.last_update[f"{symbol}_mark"] = time.time()


    async def fetch_historical_klines(self, symbol: str, interval: str = "15m", limit: int = 100):
        """Fetch historical klines from Binance REST API to seed kline_history.
        Uses urllib (sync, in thread) because aiohttp DNS resolver is blocked by PLDT ISP."""
        import json
        import urllib.error
        import urllib.request
        import concurrent.futures
        from backend.ingestion.rate_guard import (
            BINANCE_FUTURES_HOST, note_http_error, record_success, should_skip,
        )

        # Don't seed klines during an active ban - it would extend it.
        if should_skip(BINANCE_FUTURES_HOST):
            logger.warning("Skipping kline seed for %s - Binance rate-limit cooldown active", symbol)
            return

        url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['klines']}?symbol={symbol}&interval={interval}&limit={limit}"

        def _fetch():
            """Sync fetch in thread - uses system DNS resolver which works with VPN."""
            # Try strict SSL first
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Nexus/0.3"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    record_success(BINANCE_FUTURES_HOST)
                    return json.loads(resp.read())
            except urllib.error.HTTPError as http_err:
                try:
                    body = http_err.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                if note_http_error(BINANCE_FUTURES_HOST, http_err.code, body):
                    return None  # rate-limited - skip the permissive retry
            except Exception:
                pass
            # Permissive SSL fallback
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(url, headers={"User-Agent": "Nexus/0.3"})
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    record_success(BINANCE_FUTURES_HOST)
                    return json.loads(resp.read())
            except urllib.error.HTTPError as http_err:
                try:
                    body = http_err.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                note_http_error(BINANCE_FUTURES_HOST, http_err.code, body)
                return None
            except Exception:
                return None

        try:
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                data = await loop.run_in_executor(pool, _fetch)
        except Exception as e:
            logger.warning(f"Kline fetch executor error for {symbol}: {e}")
            data = None

        if data and isinstance(data, list):
            history = self.kline_history[symbol]
            for k in data:
                if not isinstance(k, list) or len(k) < 6:
                    continue
                candle = {
                    "open_time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": k[6] if len(k) > 6 else k[0],
                    "quote_volume": float(k[7]) if len(k) > 7 else 0,
                    "trades": k[8] if len(k) > 8 else 0,
                    "is_closed": True,
                }
                history.append(candle)
            logger.info(f"Loaded {len(data)} historical klines for {symbol}")
        else:
            logger.warning(f"Could not fetch historical klines for {symbol} (ISP block or network issue)")


# Global data store
binance_data = BinanceFuturesData()


async def _handle_binance_message(name: str, data: dict):
    """Route incoming Binance WS messages to the appropriate handler."""
    # Combined stream format: {"stream": "btcusdt@depth20@100ms", "data": {...}}
    stream = data.get("stream", "")
    payload = data.get("data", data)

    if not stream:
        # Single stream format
        event_type = data.get("e", "")
        symbol = data.get("s", "").upper()
    else:
        parts = stream.split("@")
        symbol = parts[0].upper() if parts else ""
        event_type = ""
        if "depth" in stream:
            event_type = "depthUpdate"
        elif "aggTrade" in stream:
            event_type = "aggTrade"
        elif "forceOrder" in stream:
            event_type = "forceOrder"
        elif "kline" in stream:
            event_type = "kline"
        elif "markPrice" in stream:
            event_type = "markPriceUpdate"

    if event_type == "depthUpdate" or "depth" in stream:
        binance_data.update_order_book(symbol, payload)
    elif event_type == "aggTrade":
        binance_data.update_agg_trade(symbol, payload)
    elif event_type == "forceOrder":
        binance_data.update_liquidation(symbol, payload)
    elif event_type == "kline":
        binance_data.update_kline(symbol, payload)
    elif event_type == "markPriceUpdate":
        binance_data.update_mark_price(symbol, payload)


def build_binance_streams(
    symbols: Optional[List[str]] = None,
    interval: str = DEFAULT_INTERVAL,
) -> str:
    """Build combined stream URL for Binance Futures."""
    symbols = symbols or DEFAULT_SYMBOLS
    streams = []
    for sym in symbols:
        s = sym.lower()
        streams.extend([
            f"{s}@depth20@100ms",
            f"{s}@aggTrade",
            f"{s}@forceOrder",
            f"{s}@kline_{interval}",
            f"{s}@markPrice@1s",
        ])
    stream_str = "/".join(streams)
    return f"{WS_BINANCE_FUTURES}?streams={stream_str}"


def create_binance_connection(
    symbols: Optional[List[str]] = None,
    interval: str = DEFAULT_INTERVAL,
) -> WSConnection:
    """Create a WSConnection for Binance Futures combined stream."""
    url = build_binance_streams(symbols, interval)
    return WSConnection(
        name="binance_futures",
        url=url,
        on_message=_handle_binance_message,
    )
