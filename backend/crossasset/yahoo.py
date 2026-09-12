"""
Nexus - Yahoo Finance access layer (async, keyless).

Two tiers of endpoint, and the difference matters operationally:

  * v8 ``/chart/<symbol>`` - open. One call returns last price, the session
    window and a full OHLCV series. Everything the regime classifier and the
    cross-asset board *need* comes from here.
  * v10 quoteSummary / v7 options / v1 screener - gated behind a cookie+crumb
    pair since 2023. We mint one, cache it for an hour, rotate on refusal, and
    degrade cleanly when Yahoo says no.

No API key on either path. Calls are registered with the shared rate guard so a
Yahoo 429 suspends this host the same way a Binance 418 suspends fapi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from backend.config import YAHOO_CHART_BASE, YAHOO_GATED_BASE, YAHOO_UA
from backend.ingestion import rate_guard
from backend.ops.logutil import warn_throttled

logger = logging.getLogger("nexus.crossasset.yahoo")

YAHOO_QUERY1_HOST = "query1.finance.yahoo.com"
YAHOO_QUERY2_HOST = "query2.finance.yahoo.com"

_CRUMB: dict[str, Any] = {"cookie": "", "crumb": "", "ts": 0.0}
_CRUMB_TTL = 3600.0


def _headers(cookie: str = "") -> dict[str, str]:
    h = {"User-Agent": YAHOO_UA, "Accept": "application/json,text/plain,*/*"}
    if cookie:
        h["Cookie"] = cookie
    return h


async def _mint_credentials(client: httpx.AsyncClient) -> tuple[str, str]:
    """
    Yahoo hands an A1/A3 cookie to anyone who asks fc.yahoo.com (it answers 404
    - the cookie is the payload), then trades that cookie for a crumb.
    """
    cookie = ""
    try:
        seed = await client.get(
            "https://fc.yahoo.com/", headers=_headers(), follow_redirects=False, timeout=8
        )
        parts = [v.split(";")[0] for k, v in seed.headers.multi_items() if k.lower() == "set-cookie"]
        cookie = "; ".join(p for p in parts if p)
    except Exception as e:  # network, TLS, DNS - all non-fatal  # noqa: BLE001
        warn_throttled(logger, "yahoo_cookie", "yahoo cookie seed failed: %s", e)

    if not cookie:
        raise RuntimeError("yahoo: no session cookie issued")

    resp = await client.get(f"{YAHOO_GATED_BASE}/v1/test/getcrumb", headers=_headers(cookie), timeout=8)
    crumb = (resp.text or "").strip()
    if resp.status_code != 200 or not crumb or "<" in crumb:
        raise RuntimeError("yahoo: crumb refused")
    return cookie, crumb


async def _credentials(client: httpx.AsyncClient, force: bool = False) -> tuple[str, str]:
    now = time.time()
    if not force and _CRUMB["crumb"] and (now - float(_CRUMB["ts"])) < _CRUMB_TTL:
        return str(_CRUMB["cookie"]), str(_CRUMB["crumb"])
    cookie, crumb = await _mint_credentials(client)
    _CRUMB.update({"cookie": cookie, "crumb": crumb, "ts": now})
    return cookie, crumb


async def fetch_gated(path: str, params: dict[str, str] | None = None) -> dict:
    """
    GET a crumb-gated endpoint. Retries once with a freshly minted crumb on a
    401/403/404, which is how Yahoo signals a rotated or never-valid crumb.
    """
    if rate_guard.should_skip(YAHOO_QUERY2_HOST):
        raise RuntimeError("yahoo: host in cooldown")

    params = dict(params or {})
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in (0, 1):
            cookie, crumb = await _credentials(client, force=(attempt == 1))
            resp = await client.get(
                f"{YAHOO_GATED_BASE}{path}",
                params={**params, "crumb": crumb},
                headers=_headers(cookie),
            )
            rate_guard.record_response(YAHOO_QUERY2_HOST, resp.status_code, resp.text[:200])
            if resp.status_code == 200:
                rate_guard.record_success(YAHOO_QUERY2_HOST)
                return resp.json()
            if resp.status_code not in (401, 403, 404) or attempt == 1:
                raise RuntimeError(f"yahoo {path}: HTTP {resp.status_code}")
    raise RuntimeError(f"yahoo {path}: unreachable")


# ---------------------------------------------------------------------------
# v8 chart - quotes and candles
# ---------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if v == v else None  # NaN check


async def _raw_chart(client: httpx.AsyncClient, symbol: str, rng: str, interval: str) -> dict | None:
    if rate_guard.should_skip(YAHOO_QUERY1_HOST):
        return None
    resp = await client.get(
        f"{YAHOO_CHART_BASE}/{symbol}",
        params={"interval": interval, "range": rng, "includePrePost": "false"},
        headers=_headers(),
    )
    rate_guard.record_response(YAHOO_QUERY1_HOST, resp.status_code, resp.text[:200])
    if resp.status_code != 200:
        return None
    rate_guard.record_success(YAHOO_QUERY1_HOST)
    chart = (resp.json() or {}).get("chart") or {}
    if chart.get("error"):
        return None
    results = chart.get("result") or []
    return results[0] if results else None


async def fetch_quote(
    client: httpx.AsyncClient, symbol: str, name: str = "", rng: str = "3mo"
) -> dict | None:
    """
    One instrument: last, change, session state, and a closes series long
    enough for the regime classifier to fit a trend on.
    """
    r = await _raw_chart(client, symbol, rng, "1d")
    if not r:
        return None

    meta = r.get("meta") or {}
    quote = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    closes = [c for c in (quote.get("close") or []) if isinstance(c, (int, float))]
    if not closes:
        return None

    price = _num(meta.get("regularMarketPrice")) or closes[-1]
    prev = _num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose"))
    if prev is None:
        prev = closes[-2] if len(closes) > 1 else price
    change = price - prev
    last_trade = _num(meta.get("regularMarketTime")) or 0.0

    return {
        "symbol": symbol,
        "name": name or str(meta.get("shortName") or symbol),
        "price": price,
        "previous_close": prev,
        "change": change,
        "change_pct": (change / prev * 100.0) if prev else 0.0,
        "currency": str(meta.get("currency") or "USD"),
        "exchange": str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
        # Inside 15 minutes of the last print the tape is live.
        "market_open": last_trade > (time.time() - 900),
        "day_high": _num(meta.get("regularMarketDayHigh")),
        "day_low": _num(meta.get("regularMarketDayLow")),
        "week52_high": _num(meta.get("fiftyTwoWeekHigh")),
        "week52_low": _num(meta.get("fiftyTwoWeekLow")),
        "volume": _num(meta.get("regularMarketVolume")),
        "closes": closes[-90:],
        "spark": closes[-30:],
    }


async def fetch_quotes(pairs: list[tuple[str, str]], rng: str = "3mo") -> list[dict]:
    """
    Batch of (symbol, display name). A failure drops that row rather than the
    batch - one delisted ticker must never blank the board.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        settled = await asyncio.gather(
            *(fetch_quote(client, sym, name, rng) for sym, name in pairs),
            return_exceptions=True,
        )

    out: list[dict] = []
    for row in settled:
        if isinstance(row, dict):
            out.append(row)
        elif isinstance(row, BaseException):
            logger.debug("cross-asset quote failed: %s", row)
    return out


async def fetch_candles(symbol: str, rng: str = "6mo", interval: str = "1d") -> dict:
    """OHLCV series for charting. Null rows (holidays) are dropped."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await _raw_chart(client, symbol, rng, interval)

    if not r or not r.get("timestamp"):
        return {"symbol": symbol, "candles": []}

    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    stamps = r["timestamp"]
    opens, highs = q.get("open") or [], q.get("high") or []
    lows, vols, closes = q.get("low") or [], q.get("volume") or [], q.get("close") or []

    def at(seq, i, fallback):
        v = seq[i] if i < len(seq) else None
        return v if isinstance(v, (int, float)) else fallback

    candles = []
    for i in range(len(stamps)):
        close = closes[i] if i < len(closes) else None
        if not isinstance(close, (int, float)):
            continue
        candles.append(
            {
                "time": int(stamps[i]),
                "open": at(opens, i, close),
                "high": at(highs, i, close),
                "low": at(lows, i, close),
                "close": close,
                "volume": at(vols, i, 0),
            }
        )
    return {"symbol": symbol, "candles": candles}


async def search(query: str, limit: int = 10) -> list[dict]:
    """Symbol lookup. Explicitly typed so the UI can keep asset classes apart."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{YAHOO_GATED_BASE}/v1/finance/search",
            params={
                "q": query,
                "quotesCount": str(limit),
                "newsCount": "0",
                "listsCount": "0",
            },
            headers=_headers(),
        )
        if resp.status_code != 200:
            return []
        rows = (resp.json() or {}).get("quotes") or []

    return [
        {
            "symbol": r.get("symbol"),
            "name": r.get("longname") or r.get("shortname") or r.get("symbol"),
            "exchange": r.get("exchDisp") or "",
            "type": r.get("typeDisp") or r.get("quoteType") or "",
            # The July regression: a cross-asset hit must never be routed into a
            # perp code path. Every row is tagged at the source.
            "asset_class": "cross_asset",
        }
        for r in rows
        if r.get("symbol")
    ]
