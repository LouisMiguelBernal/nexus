"""
Nexus - MEXC Futures (Contract) WebSocket Feed
Cross-exchange validation source for Golden Zone overlap and the institutional
Liquidity Map. MEXC carries significant retail-but-real flow on alts and adds
a 5th exchange to the fuzzy-match consensus.

Endpoint: wss://contract.mexc.com/edge
Public channels used:
    sub.depth.full - top-N order book snapshot
    sub.deal       - trade tape

MEXC requires an *application-level* ping every ~60s (`{"method":"ping"}`),
in addition to WS-level pings. Wired through WSConnection.app_ping_msg.

Quantities returned by MEXC futures are in *contracts*. We multiply by the
per-symbol contract size to normalise into base-asset units, so depth
aggregates correctly with Binance / OKX.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional

from backend.config import WS_MEXC, DEFAULT_SYMBOLS, MEXC_CONTRACT_SIZE
from backend.ingestion.ws_manager import WSConnection

logger = logging.getLogger("nexus.mexc_ws")

# MEXC futures uses BTC_USDT (underscore) format.
_MEXC_MAP = {
    "BTCUSDT": "BTC_USDT",
    "ETHUSDT": "ETH_USDT",
    "SOLUSDT": "SOL_USDT",
    "BNBUSDT": "BNB_USDT",
    "XRPUSDT": "XRP_USDT",
}


def _to_mexc(symbol: str) -> str:
    return _MEXC_MAP.get(symbol, symbol[:-4] + "_USDT")


def _from_mexc(contract: str) -> str:
    return contract.replace("_", "")


class MEXCData:
    def __init__(self):
        self.order_books: Dict[str, dict] = {}
        self.trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5000))
        self.liquidations: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        self.last_update: Dict[str, float] = {}

    def _contract_size(self, symbol: str) -> float:
        return MEXC_CONTRACT_SIZE.get(symbol, MEXC_CONTRACT_SIZE.get("DEFAULT", 1.0))

    def update_order_book(self, symbol: str, data: dict):
        cs = self._contract_size(symbol)
        # MEXC level format: [price, vol_contracts, order_count]
        bids = []
        for level in data.get("bids", []):
            if not level or len(level) < 2:
                continue
            try:
                bids.append([float(level[0]), float(level[1]) * cs])
            except (TypeError, ValueError):
                continue
        asks = []
        for level in data.get("asks", []):
            if not level or len(level) < 2:
                continue
            try:
                asks.append([float(level[0]), float(level[1]) * cs])
            except (TypeError, ValueError):
                continue
        if not bids and not asks:
            return
        self.order_books[symbol] = {"bids": bids, "asks": asks}
        self.last_update[f"{symbol}_ob"] = time.time()

    def update_trade(self, symbol: str, data: dict):
        cs = self._contract_size(symbol)
        side_code = data.get("T", 0)  # 1 = buy, 2 = sell
        try:
            price = float(data.get("p", 0))
            vol = float(data.get("v", 0)) * cs
        except (TypeError, ValueError):
            return
        if price <= 0 or vol <= 0:
            return
        self.trades[symbol].append({
            "price": price,
            "qty": vol,
            "side": "buy" if side_code == 1 else "sell",
            "time": int(data.get("t", time.time() * 1000)),
        })
        self.last_update[f"{symbol}_trades"] = time.time()


mexc_data = MEXCData()


async def _handle_mexc_message(name: str, data: dict):
    # Heartbeat / ack frames
    channel = data.get("channel", "")
    if not channel:
        # ping/pong / subscribe ack - ignore
        return
    if channel in ("pong", "rs.sub.depth.full", "rs.sub.deal", "rs.error"):
        return

    contract = data.get("symbol", "")
    symbol = _from_mexc(contract) if contract else ""
    payload = data.get("data", {})

    if channel == "push.depth.full" and symbol:
        if isinstance(payload, dict):
            mexc_data.update_order_book(symbol, payload)
    elif channel == "push.deal" and symbol:
        # `data` may be a single deal object on this channel
        if isinstance(payload, dict):
            mexc_data.update_trade(symbol, payload)
        elif isinstance(payload, list):
            for d in payload:
                if isinstance(d, dict):
                    mexc_data.update_trade(symbol, d)


def create_mexc_connection(
    symbols: Optional[List[str]] = None,
) -> WSConnection:
    symbols = symbols or DEFAULT_SYMBOLS
    messages: list[dict] = []
    for sym in symbols:
        contract = _to_mexc(sym)
        messages.append({
            "method": "sub.depth.full",
            "param": {"symbol": contract, "limit": 20},
        })
        messages.append({
            "method": "sub.deal",
            "param": {"symbol": contract},
        })
    return WSConnection(
        name="mexc",
        url=WS_MEXC,
        subscribe_msg=messages,
        on_message=_handle_mexc_message,
        app_ping_msg={"method": "ping"},
        app_ping_interval=25.0,
    )
