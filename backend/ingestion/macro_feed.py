"""
Nexus - Macro Data Feed
FRED + yfinance for macro context (SPX, VIX, DXY, Gold, US10Y).
"""

import logging
import time
from typing import Dict, Optional

import httpx

from backend.config import (
    FRED_BASE, FRED_API_KEY, FRED_SERIES,
    FEAR_GREED_URL, YFINANCE_TICKERS,
)

# CoinMarketCap's public crypto F&G chart endpoint. Updates more frequently
# than alternative.me (which snaps daily at 00:00 UTC), so we use it for
# cross-validation when the two diverge.
CMC_FNG_CHART = "https://api.coinmarketcap.com/data-api/v3/fear-greed/chart?start={start}"

logger = logging.getLogger("nexus.macro_feed")

# Module-level cache for Fear & Greed. Both upstreams update at most once an
# hour, so a 5-minute cache is well within freshness and cuts outbound calls
# dramatically under polling-heavy clients (Header re-fetches /api/sentiment
# every 60s × multiple tabs).
_FNG_CACHE: Dict[str, object] = {"data": None, "ts": 0.0}
_FNG_TTL = 300.0


class MacroFeed:
    """Fetch macro market data."""

    async def fetch_fear_greed(self) -> Optional[Dict]:
        """Fetch Bitcoin Fear & Greed Index with cross-validation.

        Pulls from two sources and reconciles:
          - alternative.me (daily, widely cited)
          - CoinMarketCap public chart (hourly, real-time)

        Returns the most-recent reading plus both snapshots so the UI can show
        divergence. Binance Square uses a CMC-derived feed, so the CMC value is
        what matches what the user sees on Binance.
        """
        now = time.time()
        cached = _FNG_CACHE.get("data")
        cached_ts = float(_FNG_CACHE.get("ts") or 0.0)
        if cached and (now - cached_ts) < _FNG_TTL:
            return cached  # type: ignore[return-value]

        alt_data: Optional[Dict] = None
        cmc_data: Optional[Dict] = None

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(FEAR_GREED_URL)
                d = resp.json()
                item = d.get("data", [{}])[0]
                ts_str = item.get("timestamp", "")
                alt_data = {
                    "value": int(item.get("value", 0)),
                    "classification": item.get("value_classification", ""),
                    "timestamp": ts_str,
                    "source": "alternative.me",
                    "age_hours": round((time.time() - int(ts_str)) / 3600, 1) if str(ts_str).isdigit() else None,
                }
            except Exception as e:
                logger.error(f"alternative.me F&G error: {e}")

            try:
                # Last 48h of hourly points - take the most recent.
                start = int(time.time()) - 48 * 3600
                resp = await client.get(CMC_FNG_CHART.format(start=start))
                d = resp.json()
                points = (d.get("data") or {}).get("dataList") or []
                if points:
                    latest = points[-1]
                    val = int(latest.get("score", 0))
                    ts = int(latest.get("timestamp", 0))
                    # Classification bucket (CMC's own labels)
                    if val >= 75: cls = "Extreme Greed"
                    elif val >= 55: cls = "Greed"
                    elif val >= 45: cls = "Neutral"
                    elif val >= 25: cls = "Fear"
                    else: cls = "Extreme Fear"
                    cmc_data = {
                        "value": val,
                        "classification": cls,
                        "timestamp": str(ts),
                        "source": "coinmarketcap",
                        "age_hours": round((time.time() - ts) / 3600, 1) if ts else None,
                    }
            except Exception as e:
                logger.error(f"CMC F&G error: {e}")

        if not alt_data and not cmc_data:
            return None

        # Prefer the fresher reading for the headline value.
        primary = cmc_data or alt_data
        # Detect divergence - Binance/CMC vs alt.me split is the exact bug the
        # user reported. Surface it so the UI can show both.
        diverged = False
        if alt_data and cmc_data and abs(alt_data["value"] - cmc_data["value"]) >= 10:
            diverged = True

        assert primary is not None
        result = {
            **primary,
            "alt_me": alt_data,
            "cmc": cmc_data,
            "diverged": diverged,
        }
        _FNG_CACHE["data"] = result
        _FNG_CACHE["ts"] = now
        return result

    async def fetch_fred_series(self, series_name: str) -> Optional[Dict]:
        """Fetch a single FRED series latest value."""
        series_id = FRED_SERIES.get(series_name)
        if not series_id or not FRED_API_KEY:
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(FRED_BASE, params={
                    "series_id": series_id,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                })
                data = resp.json()
                obs = data.get("observations", [])
                if obs:
                    return {"value": obs[0].get("value"), "date": obs[0].get("date")}
        except Exception as e:
            logger.error(f"FRED {series_name} error: {e}")
        return None

    def fetch_yfinance_snapshot(self) -> Dict:
        """Fetch current prices for macro tickers via yfinance (sync)."""
        try:
            import yfinance as yf
            result = {}
            for name, ticker in YFINANCE_TICKERS.items():
                try:
                    t = yf.Ticker(ticker)
                    info = t.fast_info
                    result[name] = {
                        "price": round(info.last_price, 2) if hasattr(info, "last_price") else 0,
                        "ticker": ticker,
                    }
                except Exception:
                    result[name] = {"price": 0, "ticker": ticker, "error": "fetch_failed"}
            return result
        except ImportError:
            logger.warning("yfinance not installed")
            return {}

    async def fetch_macro_snapshot(self) -> Dict:
        """Get a full macro context snapshot."""
        import asyncio

        fear_greed = await self.fetch_fear_greed()
        fred_data = {}
        for name in ["CPI", "FED_FUNDS_RATE", "US10Y", "DXY"]:
            val = await self.fetch_fred_series(name)
            if val:
                fred_data[name] = val

        return {
            "fear_greed": fear_greed,
            "fred": fred_data,
        }
