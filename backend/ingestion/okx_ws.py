"""
Nexus - OKX V5 WebSocket Feed
Secondary source: order book, trades, liquidations.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional

from backend.config import WS_OKX, DEFAULT_SYMBOLS
from backend.ingestion.ws_manager import WSConnection

logger = logging.getLogger("nexus.okx_ws")

# OKX uses different symbol format: BTC-USDT-SWAP
_SYMBOL_MAP = {
    "BTCUSDT": "BTC-USDT-SWAP",
    "ETHUSDT": "ETH-USDT-SWAP",
    "SOLUSDT": "SOL-USDT-SWAP",
    "BNBUSDT": "BNB-USDT-SWAP",
    "XRPUSDT": "XRP-USDT-SWAP",
}


def _to_okx_inst(symbol: str) -> str:
    return _SYMBOL_MAP.get(symbol, symbol.replace("USDT", "-USDT-SWAP"))


def _from_okx_inst(inst_id: str) -> str:
    return inst_id.replace("-USDT-SWAP", "USDT").replace("-", "")


class OKXData:
    def __init__(self):
        self.order_books: Dict[str, dict] = {}
        self.trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5000))
        self.liquidations: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        self.last_update: Dict[str, float] = {}

    def update_order_book(self, symbol: str, data: dict):
        self.order_books[symbol] = {
            "bids": [[float(p), float(q)] for p, q, *_ in data.get("bids", [])],
            "asks": [[float(p), float(q)] for p, q, *_ in data.get("asks", [])],
        }
        self.last_update[f"{symbol}_ob"] = time.time()

    def update_trade(self, symbol: str, data: dict):
        self.trades[symbol].append({
            "price": float(data.get("px", 0)),
            "qty": float(data.get("sz", 0)),
            "side": data.get("side", ""),
            "time": int(data.get("ts", time.time() * 1000)),
        })
        self.last_update[f"{symbol}_trades"] = time.time()

    def update_liquidation(self, symbol: str, data: dict):
        details = data.get("details", [{}])[0] if data.get("details") else {}
        self.liquidations[symbol].append({
            "symbol": symbol,
            "side": details.get("side", ""),
            "price": float(details.get("bkPx", 0)),
            "qty": float(details.get("sz", 0)),
            "time": int(details.get("ts", time.time() * 1000)),
        })
        self.last_update[f"{symbol}_liq"] = time.time()


okx_data = OKXData()


async def _handle_okx_message(name: str, data: dict):
    arg = data.get("arg", {})
    channel = arg.get("channel", "")
    inst_id = arg.get("instId", "")
    symbol = _from_okx_inst(inst_id)
    payload_list = data.get("data", [])

    for payload in payload_list:
        if channel == "books5":
            okx_data.update_order_book(symbol, payload)
        elif channel == "trades":
            okx_data.update_trade(symbol, payload)
        elif channel == "liquidation-orders":
            okx_data.update_liquidation(symbol, payload)


def create_okx_connection(
    symbols: Optional[List[str]] = None,
) -> WSConnection:
    symbols = symbols or DEFAULT_SYMBOLS
    args = []
    for sym in symbols:
        inst = _to_okx_inst(sym)
        args.extend([
            {"channel": "books5", "instId": inst},
            {"channel": "trades", "instId": inst},
            {"channel": "liquidation-orders", "instType": "SWAP"},
        ])
    subscribe_msg = {"op": "subscribe", "args": args}
    return WSConnection(
        name="okx",
        url=WS_OKX,
        subscribe_msg=subscribe_msg,
        on_message=_handle_okx_message,
    )
