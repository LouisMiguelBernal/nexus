"""
Nexus - Binance Futures USDT-M WebSocket Feed
Primary data source: order book, aggTrades, liquidations, klines, mark price.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque

from backend.config import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_ENDPOINTS,
    DEFAULT_INTERVAL,
    DEFAULT_SYMBOLS,
    WS_BINANCE_FUTURES,
)
from backend.data.http import HttpStatusError, fetch_json
from backend.data.klines import KlineBuffer
from backend.ingestion.ws_manager import WSConnection

logger = logging.getLogger("nexus.binance_ws")


class BinanceFuturesData:
    """Holds real-time Binance Futures data in memory."""

    def __init__(self):
        # Order book snapshots per symbol: {symbol: {"bids": [...], "asks": [...]}}
        self.order_books: dict[str, dict] = {}
        # Aggregated trades for CVD: {symbol: deque(maxlen=10000)}
        self.agg_trades: dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        # Liquidation events: {symbol: deque(maxlen=500)}
        self.liquidations: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        # Latest klines per symbol+interval: {symbol: {interval: [ohlcv]}}
        self.klines: dict[str, dict[str, list]] = defaultdict(dict)
        # Closed klines per symbol at DEFAULT_INTERVAL, upserted by open_time so a
        # REST backfill after a WS gap cannot duplicate bars (1000 x 15m ~ 10 days).
        self.kline_history: dict[str, KlineBuffer] = defaultdict(
            lambda: KlineBuffer(maxlen=1000, interval=DEFAULT_INTERVAL)
        )
        # Mark price + funding: {symbol: {"mark_price": float, "funding_rate": float, "next_funding": int}}
        self.mark_prices: dict[str, dict] = {}
        # Last update timestamps
        self.last_update: dict[str, float] = {}

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

        # Closed candles go to the history buffer, which upserts by open_time.
        if candle["is_closed"]:
            self.kline_history[symbol].append(candle)

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
        import concurrent.futures

        from backend.ingestion.rate_guard import (
            BINANCE_FUTURES_HOST,
            note_http_error,
            record_success,
            should_skip,
        )

        # Don't seed klines during an active ban - it would extend it.
        if should_skip(BINANCE_FUTURES_HOST):
            logger.warning("Skipping kline seed for %s - Binance rate-limit cooldown active", symbol)
            return

        url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['klines']}?symbol={symbol}&interval={interval}&limit={limit}"

        def _fetch():
            """Sync fetch in a thread - the system resolver works where the async
            resolvers are blocked. TLS fallback is centralised and logged in
            backend.data.http; a 418/429 ban is reported to rate_guard."""
            try:
                data = fetch_json(url, timeout=15.0)
            except HttpStatusError as http_err:
                note_http_error(BINANCE_FUTURES_HOST, http_err.status, http_err.body)
                return None
            except Exception as exc:  # noqa: BLE001  # reason: network failure; caller logs and the WS feed keeps accumulating bars
                logger.warning("kline seed fetch failed for %s: %s", symbol, exc)
                return None
            record_success(BINANCE_FUTURES_HOST)
            return data

        try:
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                data = await loop.run_in_executor(pool, _fetch)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Kline fetch executor error for {symbol}: {e}")
            data = None

        if data and isinstance(data, list):
            history = self.kline_history[symbol]
            candles: list[dict] = []
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
                candles.append(candle)
            added = history.extend(candles)
            logger.info("Loaded %d historical klines for %s (%d new)", len(candles), symbol, added)
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
    symbols: list[str] | None = None,
    interval: str = DEFAULT_INTERVAL,
) -> str:
    """Build combined stream URL for Binance Futures."""
    symbols = symbols or DEFAULT_SYMBOLS
    streams = []
    for sym in symbols:
        s = sym.lower()
        streams.extend(
            [
                f"{s}@depth20@100ms",
                f"{s}@aggTrade",
                f"{s}@forceOrder",
                f"{s}@kline_{interval}",
                f"{s}@markPrice@1s",
            ]
        )
    stream_str = "/".join(streams)
    return f"{WS_BINANCE_FUTURES}?streams={stream_str}"


def create_binance_connection(
    symbols: list[str] | None = None,
    interval: str = DEFAULT_INTERVAL,
) -> WSConnection:
    """Create a WSConnection for Binance Futures combined stream."""
    url = build_binance_streams(symbols, interval)
    return WSConnection(
        name="binance_futures",
        url=url,
        on_message=_handle_binance_message,
    )
