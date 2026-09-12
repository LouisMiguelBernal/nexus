"""
Nexus - equity reference data: fundamentals, screens, option chains.

All three ride the crumb-gated Yahoo endpoints, so all three can be refused.
Every function here returns ``{"available": False, "reason": ...}`` instead of
raising when that happens: a gated upstream must degrade one panel, never take
down the poller that calls it.

Scope note - this is research context for the perp book (is COIN/MSTR leading
BTC? is the equity tape risk-on?), not an equity trading surface. Nothing here
produces an order.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import YAHOO_SCREENS
from backend.crossasset.yahoo import fetch_gated

logger = logging.getLogger("nexus.crossasset.equity")

_MODULES = ",".join(
    [
        "assetProfile",
        "summaryDetail",
        "defaultKeyStatistics",
        "financialData",
        "price",
        "calendarEvents",
        "incomeStatementHistory",
        "topHoldings",
    ]
)


def _val(v: Any) -> float | None:
    """Yahoo wraps numerics as {raw, fmt}; some modules return bare floats."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict) and isinstance(v.get("raw"), (int, float)):
        return float(v["raw"])
    return None


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------


async def fetch_fundamentals(symbol: str) -> dict:
    try:
        data = await fetch_gated(f"/v10/finance/quoteSummary/{symbol}", {"modules": _MODULES})
    except Exception as e:  # noqa: BLE001
        return {"symbol": symbol, "available": False, "reason": str(e)}

    results = ((data or {}).get("quoteSummary") or {}).get("result") or []
    if not results:
        return {"symbol": symbol, "available": False, "reason": "no data"}

    r = results[0]
    profile = r.get("assetProfile") or {}
    detail = r.get("summaryDetail") or {}
    stats = r.get("defaultKeyStatistics") or {}
    fin = r.get("financialData") or {}
    price_mod = r.get("price") or {}

    rows = (r.get("incomeStatementHistory") or {}).get("incomeStatementHistory") or []
    income = []
    for row in rows[:4]:
        revenue = _val(row.get("totalRevenue"))
        net = _val(row.get("netIncome"))
        income.append(
            {
                "end_date": _val(row.get("endDate")),
                "revenue": revenue,
                "net_income": net,
                # Yahoo stopped populating grossProfit / operatingIncome on this
                # module - they come back 0 and null for every issuer. Report the
                # margin the two live fields imply instead of a wall of zeroes.
                "net_margin": (net / revenue * 100.0) if revenue and net is not None else None,
            }
        )

    holdings = [
        {
            "symbol": h.get("symbol") or "",
            "name": h.get("holdingName") or "",
            "weight": _val(h.get("holdingPercent")),
        }
        for h in ((r.get("topHoldings") or {}).get("holdings") or [])[:12]
    ]

    return {
        "symbol": symbol,
        "available": True,
        "name": str(price_mod.get("longName") or price_mod.get("shortName") or symbol),
        "quote_type": str(price_mod.get("quoteType") or ""),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "country": profile.get("country"),
        "employees": _val(profile.get("fullTimeEmployees")),
        "summary": profile.get("longBusinessSummary"),
        "market_cap": _val(price_mod.get("marketCap")) or _val(detail.get("marketCap")),
        "trailing_pe": _val(detail.get("trailingPE")),
        "forward_pe": _val(detail.get("forwardPE")) or _val(stats.get("forwardPE")),
        "price_to_book": _val(stats.get("priceToBook")),
        "price_to_sales": _val(stats.get("priceToSalesTrailing12Months")),
        "beta": _val(detail.get("beta")) or _val(stats.get("beta")),
        "eps": _val(stats.get("trailingEps")),
        "dividend_yield": _val(detail.get("dividendYield")),
        "profit_margin": _val(fin.get("profitMargins")) or _val(stats.get("profitMargins")),
        "operating_margin": _val(fin.get("operatingMargins")),
        "gross_margin": _val(fin.get("grossMargins")),
        "return_on_equity": _val(fin.get("returnOnEquity")),
        "revenue_growth": _val(fin.get("revenueGrowth")),
        "earnings_growth": _val(fin.get("earningsGrowth")),
        "total_cash": _val(fin.get("totalCash")),
        "total_debt": _val(fin.get("totalDebt")),
        "debt_to_equity": _val(fin.get("debtToEquity")),
        "free_cashflow": _val(fin.get("freeCashflow")),
        "recommendation": fin.get("recommendationKey"),
        "target_mean": _val(fin.get("targetMeanPrice")),
        "target_high": _val(fin.get("targetHighPrice")),
        "target_low": _val(fin.get("targetLowPrice")),
        "analysts": _val(fin.get("numberOfAnalystOpinions")),
        "income": income,
        "holdings": holdings,
    }


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------

SCREEN_IDS = {s[0] for s in YAHOO_SCREENS}


async def fetch_screen(screen_id: str, count: int = 40) -> dict:
    if screen_id not in SCREEN_IDS:
        return {
            "id": screen_id,
            "available": False,
            "reason": "unknown screen",
            "screens": [{"id": i, "label": l} for i, l in YAHOO_SCREENS],  # noqa: E741
            "rows": [],
        }

    try:
        data = await fetch_gated(
            "/v1/finance/screener/predefined/saved",
            {"scrIds": screen_id, "count": str(min(count, 100)), "start": "0"},
        )
    except Exception as e:  # noqa: BLE001
        return {
            "id": screen_id,
            "available": False,
            "reason": str(e),
            "screens": [{"id": i, "label": l} for i, l in YAHOO_SCREENS],  # noqa: E741
            "rows": [],
        }

    results = ((data or {}).get("finance") or {}).get("result") or []
    quotes = (results[0].get("quotes") if results else []) or []

    return {
        "id": screen_id,
        "available": True,
        "screens": [{"id": i, "label": l} for i, l in YAHOO_SCREENS],  # noqa: E741
        "rows": [
            {
                "symbol": q.get("symbol") or "",
                "name": q.get("shortName") or q.get("longName") or q.get("symbol") or "",
                "price": _val(q.get("regularMarketPrice")),
                "change": _val(q.get("regularMarketChange")),
                # Yahoo already returns this as a percent - do not rescale.
                "change_pct": _val(q.get("regularMarketChangePercent")),
                "volume": _val(q.get("regularMarketVolume")),
                "market_cap": _val(q.get("marketCap")),
                "pe": _val(q.get("trailingPE")),
                "week52_change_pct": _val(q.get("fiftyTwoWeekChangePercent")),
                "exchange": q.get("fullExchangeName") or q.get("exchange") or "",
                "asset_class": "cross_asset",
            }
            for q in quotes
        ],
    }


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def _leg(rows: list[dict]) -> list[dict]:
    return [
        {
            "strike": _val(c.get("strike")) or 0.0,
            "last": _val(c.get("lastPrice")),
            "bid": _val(c.get("bid")),
            "ask": _val(c.get("ask")),
            "volume": _val(c.get("volume")),
            "open_interest": _val(c.get("openInterest")),
            "iv": _val(c.get("impliedVolatility")),
            "in_the_money": bool(c.get("inTheMoney")),
        }
        for c in rows
    ]


def _open_interest_is_credible(total_oi: float, total_volume: float) -> bool:
    """
    Is Yahoo's open-interest field usable for this chain?

    It is currently unreliable: near expiries come back with OI 0 against
    hundreds of thousands of contracts of same-day volume, and longer tenors
    return implausible two-digit totals. On an established chain OI is
    accumulated over the life of the contract and so is normally at least as
    large as one day's volume - when it is not, the field is not being
    populated and anything derived from it would be fiction.
    """
    if total_oi <= 0:
        return False
    if total_volume <= 0:
        return True  # nothing to contradict it
    return total_oi >= total_volume


def max_pain(calls: list[dict], puts: list[dict]) -> float | None:
    """
    The strike where the total intrinsic value of all open contracts is
    smallest - i.e. where the most option premium expires worthless.

    Undefined when nothing is open. Without open interest every strike scores a
    pain of zero and the first one wins by tie-break, which reports a newly
    listed expiry's lowest strike as "max pain" - a number that looks
    authoritative and means nothing.
    """
    strikes = sorted({c["strike"] for c in calls} | {p["strike"] for p in puts})
    if not strikes:
        return None

    total_oi = sum(c.get("open_interest") or 0.0 for c in calls)
    total_oi += sum(p.get("open_interest") or 0.0 for p in puts)
    if total_oi <= 0:
        return None

    best_strike, best_pain = None, float("inf")
    for settle in strikes:
        pain = 0.0
        for c in calls:
            if settle > c["strike"]:
                pain += (settle - c["strike"]) * (c["open_interest"] or 0.0)
        for p in puts:
            if settle < p["strike"]:
                pain += (p["strike"] - settle) * (p["open_interest"] or 0.0)
        if pain < best_pain:
            best_pain, best_strike = pain, settle
    return best_strike


async def fetch_chain(symbol: str, expiry: int | None = None) -> dict:
    params = {"date": str(expiry)} if expiry else {}
    try:
        data = await fetch_gated(f"/v7/finance/options/{symbol}", params)
    except Exception as e:  # noqa: BLE001
        return {"symbol": symbol, "available": False, "reason": str(e)}

    results = ((data or {}).get("optionChain") or {}).get("result") or []
    if not results:
        return {"symbol": symbol, "available": False, "reason": "no chain"}

    r = results[0]
    chain = (r.get("options") or [{}])[0]
    calls = _leg(chain.get("calls") or [])
    puts = _leg(chain.get("puts") or [])

    call_oi = sum(c["open_interest"] or 0.0 for c in calls)
    put_oi = sum(p["open_interest"] or 0.0 for p in puts)
    call_vol = sum(c["volume"] or 0.0 for c in calls)
    put_vol = sum(p["volume"] or 0.0 for p in puts)

    credible = _open_interest_is_credible(call_oi + put_oi, call_vol + put_vol)

    # Prefer open interest when it is usable, otherwise fall back to volume and
    # say which basis was used - a put/call ratio means different things on the
    # two bases and an unlabelled number invites the wrong read.
    if credible and call_oi:
        ratio, basis = put_oi / call_oi, "open_interest"
    elif call_vol:
        ratio, basis = put_vol / call_vol, "volume"
    else:
        ratio, basis = None, None

    return {
        "symbol": r.get("underlyingSymbol") or symbol,
        "available": True,
        "underlying_price": _val((r.get("quote") or {}).get("regularMarketPrice")),
        "expirations": r.get("expirationDates") or [],
        "expiry": chain.get("expirationDate"),
        "calls": calls,
        "puts": puts,
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "call_volume": call_vol,
        "put_volume": put_vol,
        "open_interest_credible": credible,
        "put_call_ratio": ratio,
        "put_call_basis": basis,
        # Max pain is an open-interest construct; without credible OI there is
        # no honest answer, so it stays None rather than guessing from volume.
        "max_pain": max_pain(calls, puts) if credible else None,
    }
