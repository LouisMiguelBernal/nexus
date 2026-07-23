"""
Nexus - Deribit Options + Historical Trades Feed
Free public API: options chain, max pain, put/call ratio, historical trades.
Reference: https://github.com/BarendPotijk/deribit_historical_trades
"""

import logging
import time
from typing import Dict, List, Optional

import httpx

from backend.config import DERIBIT_BASE

logger = logging.getLogger("nexus.deribit")


class DeribitFeed:
    """Fetch options data and historical trades from Deribit public API."""

    async def get_instruments(self, currency: str = "BTC", kind: str = "option") -> List[Dict]:
        """Get all active option instruments."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{DERIBIT_BASE}/get_instruments", params={
                    "currency": currency,
                    "kind": kind,
                    "expired": "false",
                })
                data = resp.json()
                return data.get("result", [])
        except Exception as e:
            logger.error(f"Deribit instruments error: {e}")
            return []

    async def get_book_summary(self, currency: str = "BTC") -> List[Dict]:
        """Get book summary for all options."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{DERIBIT_BASE}/get_book_summary_by_currency", params={
                    "currency": currency,
                    "kind": "option",
                })
                data = resp.json()
                return data.get("result", [])
        except Exception as e:
            logger.error(f"Deribit book summary error: {e}")
            return []

    async def get_last_trades(
        self,
        instrument_name: str = "BTC-PERPETUAL",
        count: int = 100,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> List[Dict]:
        """
        Fetch historical trades from Deribit.
        Uses get_last_trades_by_instrument_and_time for time-ranged queries,
        or get_last_trades_by_instrument for latest trades.
        Reference: github.com/BarendPotijk/deribit_historical_trades
        """
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if start_timestamp and end_timestamp:
                    resp = await client.get(
                        f"{DERIBIT_BASE}/get_last_trades_by_instrument_and_time",
                        params={
                            "instrument_name": instrument_name,
                            "start_timestamp": start_timestamp,
                            "end_timestamp": end_timestamp,
                            "count": count,
                            "sorting": "desc",
                        },
                    )
                else:
                    resp = await client.get(
                        f"{DERIBIT_BASE}/get_last_trades_by_instrument",
                        params={
                            "instrument_name": instrument_name,
                            "count": count,
                            "sorting": "desc",
                        },
                    )
                data = resp.json()
                trades = data.get("result", {}).get("trades", [])
                return [{
                    "trade_id": t.get("trade_id"),
                    "instrument": t.get("instrument_name"),
                    "price": t.get("price"),
                    "amount": t.get("amount"),
                    "direction": t.get("direction"),
                    "timestamp": t.get("timestamp"),
                    "index_price": t.get("index_price"),
                    "mark_price": t.get("mark_price"),
                    "iv": t.get("iv"),  # Implied volatility (options)
                    "tick_direction": t.get("tick_direction"),
                } for t in trades]
        except Exception as e:
            logger.error(f"Deribit trades error: {e}")
            return []

    async def get_historical_trades_paginated(
        self,
        instrument_name: str = "BTC-PERPETUAL",
        start_timestamp: int = 0,
        end_timestamp: int = 0,
        batch_size: int = 1000,
        max_batches: int = 10,
    ) -> List[Dict]:
        """
        Paginated historical trade fetch (inspired by BarendPotijk approach).
        Walks backward from end_timestamp collecting trades in batches.
        """
        if not end_timestamp:
            end_timestamp = int(time.time() * 1000)
        if not start_timestamp:
            start_timestamp = end_timestamp - 3600_000  # Default 1 hour back

        all_trades = []
        current_end = end_timestamp

        for batch in range(max_batches):
            trades = await self.get_last_trades(
                instrument_name=instrument_name,
                count=batch_size,
                start_timestamp=start_timestamp,
                end_timestamp=current_end,
            )
            if not trades:
                break

            all_trades.extend(trades)
            # Move window back
            oldest_ts = min(t.get("timestamp", current_end) for t in trades)
            if oldest_ts <= start_timestamp:
                break
            current_end = oldest_ts - 1

        logger.info(f"Deribit historical: {len(all_trades)} trades for {instrument_name}")
        return all_trades

    async def get_order_book(self, instrument_name: str = "BTC-PERPETUAL", depth: int = 20) -> Optional[Dict]:
        """Get order book for any Deribit instrument."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{DERIBIT_BASE}/get_order_book", params={
                    "instrument_name": instrument_name,
                    "depth": depth,
                })
                data = resp.json()
                result = data.get("result", {})
                return {
                    "bids": result.get("bids", []),
                    "asks": result.get("asks", []),
                    "mark_price": result.get("mark_price"),
                    "index_price": result.get("index_price"),
                    "funding_8h": result.get("funding_8h"),
                    "open_interest": result.get("open_interest"),
                    "timestamp": result.get("timestamp"),
                }
        except Exception as e:
            logger.error(f"Deribit order book error: {e}")
            return None

    async def compute_put_call_ratio(self, currency: str = "BTC") -> Optional[Dict]:
        """Compute aggregate put/call ratio from open interest."""
        instruments = await self.get_instruments(currency)
        if not instruments:
            return None

        call_oi = sum(i.get("open_interest", 0) for i in instruments if i.get("option_type") == "call")
        put_oi = sum(i.get("open_interest", 0) for i in instruments if i.get("option_type") == "put")

        if call_oi == 0:
            return {"put_call_ratio": 0, "error": "No call OI"}

        ratio = put_oi / call_oi
        return {
            "put_call_ratio": round(ratio, 4),
            "call_oi": call_oi,
            "put_oi": put_oi,
            "total_options_oi": call_oi + put_oi,
            "sentiment": "bearish" if ratio > 1.2 else "bullish" if ratio < 0.7 else "neutral",
        }

    async def compute_max_pain(self, currency: str = "BTC") -> Optional[Dict]:
        """Compute max pain price (strike where total option value is minimized)."""
        instruments = await self.get_instruments(currency)
        if not instruments:
            return None

        strike_oi: Dict[float, float] = {}
        for inst in instruments:
            strike = inst.get("strike")
            oi = inst.get("open_interest", 0)
            if strike:
                strike_oi[strike] = strike_oi.get(strike, 0) + oi

        if not strike_oi:
            return None

        max_pain_strike = max(strike_oi, key=strike_oi.get)
        return {
            "max_pain": max_pain_strike,
            "total_oi_at_strike": strike_oi[max_pain_strike],
            "total_strikes": len(strike_oi),
        }

    async def get_dvol(self, currency: str = "BTC", hours: int = 24) -> Optional[Dict]:
        """Fetch Deribit volatility index (DVOL) - Deribit's BVIV/EVIV equivalent.
        Returns latest index value plus trailing series over ``hours`` hours."""
        try:
            end = int(time.time() * 1000)
            start = end - hours * 3600 * 1000
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{DERIBIT_BASE}/get_volatility_index_data", params={
                    "currency": currency,
                    "start_timestamp": start,
                    "end_timestamp": end,
                    "resolution": "3600",
                })
                data = resp.json()
                rows = data.get("result", {}).get("data", []) or []
                # Each row: [ts, open, high, low, close]
                if not rows:
                    return None
                latest = rows[-1]
                series = [{"time": r[0], "value": float(r[4])} for r in rows if len(r) >= 5]
                return {
                    "currency": currency,
                    "latest": float(latest[4]),
                    "series": series,
                }
        except Exception as e:
            logger.error(f"Deribit DVOL error: {e}")
            return None

    async def get_funding_rate(self, instrument: str = "BTC-PERPETUAL") -> Optional[Dict]:
        """Get current funding rate for perpetual."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{DERIBIT_BASE}/get_funding_rate_value", params={
                    "instrument_name": instrument,
                    "start_timestamp": int((time.time() - 28800) * 1000),  # 8h ago
                    "end_timestamp": int(time.time() * 1000),
                })
                data = resp.json()
                return {"funding_rate": data.get("result"), "instrument": instrument}
        except Exception as e:
            logger.error(f"Deribit funding error: {e}")
            return None
