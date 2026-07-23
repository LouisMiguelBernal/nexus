"""
Nexus - BloFin Exchange Client via CCXT
Paper trading integration. DEMO mode ALWAYS until Phase 6.
API Key: nexus | Permissions: READ, TRADE | App: CCXT
"""

import logging
from typing import Dict, List, Optional

import ccxt

from backend.config import (
    BLOFIN_API_KEY,
    BLOFIN_SECRET,
    BLOFIN_PASSPHRASE,
    BLOFIN_DEMO,
)

logger = logging.getLogger("nexus.blofin")


class BloFinClient:
    """BloFin exchange client via CCXT for paper trading."""

    def __init__(self):
        self._exchange: Optional[ccxt.blofin] = None
        self._init_exchange()

    def _init_exchange(self):
        """Initialize CCXT BloFin client."""
        if not BLOFIN_API_KEY or not BLOFIN_SECRET:
            logger.warning("BloFin API keys not configured")
            return

        try:
            self._exchange = ccxt.blofin({
                "apiKey": BLOFIN_API_KEY,
                "secret": BLOFIN_SECRET,
                "password": BLOFIN_PASSPHRASE,  # passphrase = "nexus"
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",  # Perpetual futures
                    "sandboxMode": BLOFIN_DEMO,  # ALWAYS True until Phase 6
                },
            })
            if BLOFIN_DEMO:
                self._exchange.set_sandbox_mode(True)
            logger.info(f"BloFin initialized (demo={BLOFIN_DEMO})")
        except Exception as e:
            logger.error(f"BloFin init error: {e}")
            self._exchange = None

    @property
    def connected(self) -> bool:
        return self._exchange is not None

    async def get_balance(self) -> Optional[Dict]:
        """Get account balance."""
        if not self._exchange:
            return None
        try:
            balance = self._exchange.fetch_balance()
            return {
                "total": balance.get("total", {}),
                "free": balance.get("free", {}),
                "used": balance.get("used", {}),
                "timestamp": balance.get("timestamp"),
            }
        except Exception as e:
            logger.error(f"BloFin balance error: {e}")
            return None

    async def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        if not self._exchange:
            return []
        try:
            positions = self._exchange.fetch_positions()
            return [{
                "symbol": p.get("symbol"),
                "side": p.get("side"),
                "contracts": p.get("contracts"),
                "notional": p.get("notional"),
                "entry_price": p.get("entryPrice"),
                "mark_price": p.get("markPrice"),
                "unrealized_pnl": p.get("unrealizedPnl"),
                "leverage": p.get("leverage"),
                "liquidation_price": p.get("liquidationPrice"),
                "margin_mode": p.get("marginMode"),
            } for p in positions if float(p.get("contracts", 0)) != 0]
        except Exception as e:
            logger.error(f"BloFin positions error: {e}")
            return []

    async def get_ticker(self, symbol: str = "BTC/USDT:USDT") -> Optional[Dict]:
        """Get ticker for a symbol."""
        if not self._exchange:
            return None
        try:
            ticker = self._exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "last": ticker.get("last"),
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "volume": ticker.get("baseVolume"),
                "change_pct": ticker.get("percentage"),
            }
        except Exception as e:
            logger.error(f"BloFin ticker error: {e}")
            return None

    async def place_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        amount: float,
        price: Optional[float] = None,
        order_type: str = "limit",
        leverage: int = 5,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Place an order on BloFin (paper mode).
        DEMO ONLY until Phase 6 validation.
        """
        if not self._exchange:
            return None
        if not BLOFIN_DEMO:
            logger.critical("SAFETY: Live trading attempted but BLOFIN_DEMO should be True")
            return None

        try:
            # Set leverage
            self._exchange.set_leverage(leverage, symbol)

            params = {}
            if stop_loss:
                params["stopLoss"] = {"triggerPrice": stop_loss}
            if take_profit:
                params["takeProfit"] = {"triggerPrice": take_profit}

            order = self._exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                params=params,
            )
            logger.info(f"BloFin order: {side} {amount} {symbol} @ {price or 'market'} ({leverage}x)")
            return {
                "order_id": order.get("id"),
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "amount": amount,
                "price": price,
                "leverage": leverage,
                "status": order.get("status"),
                "demo_mode": BLOFIN_DEMO,
            }
        except Exception as e:
            logger.error(f"BloFin order error: {e}")
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get open orders."""
        if not self._exchange:
            return []
        try:
            orders = self._exchange.fetch_open_orders(symbol)
            return [{
                "order_id": o.get("id"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "type": o.get("type"),
                "amount": o.get("amount"),
                "price": o.get("price"),
                "status": o.get("status"),
            } for o in orders]
        except Exception as e:
            logger.error(f"BloFin open orders error: {e}")
            return []

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order."""
        if not self._exchange:
            return False
        try:
            self._exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"BloFin cancel error: {e}")
            return False

    async def get_trades_history(self, symbol: str, limit: int = 50) -> List[Dict]:
        """Get recent trade history."""
        if not self._exchange:
            return []
        try:
            trades = self._exchange.fetch_my_trades(symbol, limit=limit)
            return [{
                "trade_id": t.get("id"),
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "price": t.get("price"),
                "amount": t.get("amount"),
                "cost": t.get("cost"),
                "fee": t.get("fee"),
                "timestamp": t.get("timestamp"),
            } for t in trades]
        except Exception as e:
            logger.error(f"BloFin trades history error: {e}")
            return []
