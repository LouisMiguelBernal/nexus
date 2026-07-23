"""
Nexus - Binance Portfolio Margin API Integration
Fetches PM account data: unified balance, positions, margin health.
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Optional
from urllib.parse import urlencode

import httpx

from backend.config import (
    BINANCE_PM_BASE,
    BINANCE_PM_ENDPOINTS,
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_ENDPOINTS,
    BINANCE_API_KEY,
    BINANCE_SECRET,
)

logger = logging.getLogger("nexus.portfolio_margin")


def _sign_request(params: dict) -> dict:
    """Sign Binance API request with HMAC SHA256."""
    if not BINANCE_SECRET:
        return params
    params["timestamp"] = int(time.time() * 1000)
    query_string = urlencode(params)
    signature = hmac.new(
        BINANCE_SECRET.encode(), query_string.encode(), hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params


def _headers() -> dict:
    return {"X-MBX-APIKEY": BINANCE_API_KEY} if BINANCE_API_KEY else {}


class PortfolioMarginClient:
    """Binance Portfolio Margin API client."""

    def __init__(self):
        self._is_pm_account: Optional[bool] = None

    async def get_account(self) -> Optional[Dict]:
        """Get PM account info or standard futures account."""
        try:
            # Try PM endpoint first
            url = f"{BINANCE_PM_BASE}{BINANCE_PM_ENDPOINTS['account']}"
            params = _sign_request({})
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params, headers=_headers())
                if resp.status_code == 200:
                    self._is_pm_account = True
                    return resp.json()
        except Exception:
            pass

        try:
            # Fallback to standard futures account
            url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['account']}"
            params = _sign_request({})
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params, headers=_headers())
                if resp.status_code == 200:
                    self._is_pm_account = False
                    return resp.json()
        except Exception as e:
            logger.error(f"Account fetch error: {e}")

        return None

    async def get_positions(self) -> list:
        """Get all open positions."""
        try:
            if self._is_pm_account:
                url = f"{BINANCE_PM_BASE}{BINANCE_PM_ENDPOINTS['position']}"
            else:
                url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['position_risk']}"

            params = _sign_request({})
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params, headers=_headers())
                if resp.status_code == 200:
                    positions = resp.json()
                    # Filter to positions with non-zero amount
                    return [
                        p for p in positions
                        if float(p.get("positionAmt", 0)) != 0
                    ]
        except Exception as e:
            logger.error(f"Positions fetch error: {e}")
        return []

    async def get_leverage_brackets(self, symbol: str) -> Optional[list]:
        """Get leverage bracket info for a symbol."""
        try:
            url = f"{BINANCE_FUTURES_BASE}{BINANCE_FUTURES_ENDPOINTS['leverage_bracket']}"
            params = _sign_request({"symbol": symbol})
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params, headers=_headers())
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.error(f"Leverage brackets error: {e}")
        return None

    async def get_margin_summary(self) -> Dict:
        """Get a unified margin health summary."""
        account = await self.get_account()
        positions = await self.get_positions()

        if not account:
            return {"error": "Could not fetch account data", "has_api_key": bool(BINANCE_API_KEY)}

        # Extract key fields (handle both PM and standard accounts)
        total_collateral = float(account.get("totalMarginBalance", account.get("totalWalletBalance", 0)))
        total_unrealized = float(account.get("totalUnrealizedProfit", 0))
        available_balance = float(account.get("availableBalance", 0))
        total_maint_margin = float(account.get("totalMaintMargin", 0))

        position_list = []
        total_notional = 0.0
        for p in positions:
            notional = abs(float(p.get("notional", p.get("positionAmt", 0))) * float(p.get("markPrice", p.get("entryPrice", 0))))
            total_notional += notional
            position_list.append({
                "symbol": p.get("symbol"),
                "side": "LONG" if float(p.get("positionAmt", 0)) > 0 else "SHORT",
                "size": float(p.get("positionAmt", 0)),
                "entry_price": float(p.get("entryPrice", 0)),
                "mark_price": float(p.get("markPrice", 0)),
                "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
                "leverage": int(p.get("leverage", 1)),
                "notional": round(notional, 2),
            })

        effective_leverage = total_notional / max(total_collateral, 1)
        margin_ratio = total_maint_margin / max(total_collateral, 1)

        return {
            "is_portfolio_margin": self._is_pm_account,
            "total_collateral": round(total_collateral, 2),
            "available_balance": round(available_balance, 2),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_maint_margin": round(total_maint_margin, 2),
            "total_position_notional": round(total_notional, 2),
            "effective_leverage": round(effective_leverage, 2),
            "margin_ratio_pct": round(margin_ratio * 100, 2),
            "positions": position_list,
            "position_count": len(position_list),
        }
