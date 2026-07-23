"""
journal_router.py  -  Trading Journal backend  (v2 - fixed)
Mounts at: /api/journal/...

ROOT CAUSE FIXES vs v1
-----------------------
1. Env vars loaded once by backend.config from the canonical E:/nexus/.env.
2. HMAC signing rebuilt correctly.
3. Symbol discovery via /fapi/v1/income - finds every symbol actually traded.
4. Pagination fixed - startTime on first page; fromId on subsequent pages.
5. /api/journal/debug endpoint to verify credentials without exposing them.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from backend import config as _config  # noqa: F401  - side-effect: loads .env

log = logging.getLogger("nexus.journal")

# ── constants ─────────────────────────────────────────────────────────────────

JOURNAL_START_MS = int(
    datetime(2026, 4, 18, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
)
# Use the configured journal start directly. Both /fapi/v1/income and
# /fapi/v1/userTrades are walked in 7-day windows, so the start can be far
# back without tripping Binance's 7-day-gap rejection.
_ROLLING_START_MS = lambda: JOURNAL_START_MS

BINANCE_FAPI = "https://fapi.binance.com"
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

router = APIRouter(prefix="/api/journal", tags=["journal"])

_positions_cache: list[dict] = []
_analysis_cache: dict[str, Any] = {}
_notes_store: dict[str, str] = {}
_last_fetch_ts: float = 0.0
_last_error: str = ""
CACHE_TTL = 120  # 2 min - trades auto-stale faster so new fills surface quickly


class NotePayload(BaseModel):
    note: str


# ── HMAC signing ──────────────────────────────────────────────────────────────

def _sign(params: dict[str, Any], secret: str) -> dict[str, Any]:
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 6000
    query = "&".join(f"{k}={v}" for k, v in p.items())
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    p["signature"] = sig
    return p


async def _get(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    api_key: str,
    api_secret: str,
) -> Any:
    signed = _sign(params, api_secret)
    r = await client.get(
        f"{BINANCE_FAPI}{path}",
        params=signed,
        headers={"X-MBX-APIKEY": api_key},
        timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Binance {r.status_code}: {r.text[:300]}")
    return r.json()


# ── Symbol discovery ──────────────────────────────────────────────────────────

async def _discover_symbols(
    client: httpx.AsyncClient, api_key: str, api_secret: str
) -> list[str]:
    """
    Query ALL income types in parallel so every touched symbol is captured -
    including breakeven trades (COMMISSION only, zero REALIZED_PNL) and
    symbols where PnL was $0.00 exactly.
    """
    symbols: set[str] = set()
    now_ms  = int(time.time() * 1000)
    start   = _ROLLING_START_MS()
    window  = 7 * 24 * 3600 * 1000
    # All income types that carry a symbol field
    income_types = ["REALIZED_PNL", "COMMISSION", "FUNDING_FEE"]

    async def _scan_type(income_type: str) -> None:
        cursor = start
        try:
            while cursor < now_ms:
                end  = min(cursor + window, now_ms)
                data = await _get(
                    client,
                    "/fapi/v1/income",
                    {"incomeType": income_type, "startTime": cursor, "endTime": end, "limit": 1000},
                    api_key, api_secret,
                )
                for item in data:
                    if item.get("symbol"):
                        symbols.add(item["symbol"])
                cursor = end + 1
                await asyncio.sleep(0.04)
        except Exception as exc:
            log.warning(f"Journal: income scan [{income_type}] failed: {exc}")

    try:
        await asyncio.gather(*[_scan_type(t) for t in income_types])
    except Exception as exc:
        log.warning(f"Journal: symbol discovery failed ({exc}), using fallback list")

    if not symbols:
        log.warning("Journal: discovery returned 0 symbols - using fallback list")
        return [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
            "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "ADAUSDT",
        ]

    result = sorted(symbols)
    log.info(f"Journal: discovered {len(result)} symbols: {result}")
    return result


# ── Fill fetching ─────────────────────────────────────────────────────────────

async def _fetch_fills(
    client: httpx.AsyncClient, symbol: str, api_key: str, api_secret: str
) -> list[dict]:
    """
    Walk Binance /fapi/v1/userTrades in 7-day windows. Binance rejects /
    truncates requests where the (startTime, endTime) gap exceeds 7 days,
    which is why a single startTime=90d_ago request silently returns nothing.
    Each window is paginated via fromId if it has >1000 fills.
    """
    all_fills: list[dict] = []
    seen_ids: set[int] = set()
    now_ms  = int(time.time() * 1000)
    window  = 7 * 24 * 3600 * 1000  # Binance hard cap
    cursor  = _ROLLING_START_MS()

    while cursor < now_ms:
        end = min(cursor + window, now_ms)
        # First page of this 7-day window
        params: dict[str, Any] = {
            "symbol": symbol,
            "startTime": cursor,
            "endTime": end,
            "limit": 1000,
        }
        try:
            batch: list[dict] = await _get(
                client, "/fapi/v1/userTrades", params, api_key, api_secret
            )
        except Exception as exc:
            log.warning(f"Journal: userTrades {symbol} window [{cursor}..{end}] failed: {exc}")
            cursor = end + 1
            continue

        if batch:
            for f in batch:
                fid = int(f["id"])
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    all_fills.append(f)

            # If we filled the page, paginate within the window via fromId
            # (fromId ignores startTime/endTime - so we cap by checking time).
            page_count = 0
            while len(batch) == 1000 and page_count < 20:
                page_count += 1
                next_from = int(batch[-1]["id"]) + 1
                p2: dict[str, Any] = {"symbol": symbol, "fromId": next_from, "limit": 1000}
                try:
                    batch = await _get(client, "/fapi/v1/userTrades", p2, api_key, api_secret)
                except Exception as exc:
                    log.warning(f"Journal: userTrades {symbol} fromId {next_from} failed: {exc}")
                    break
                if not batch:
                    break
                # Stop once we walk past this window's end
                in_window = [f for f in batch if int(f["time"]) <= end]
                for f in in_window:
                    fid = int(f["id"])
                    if fid not in seen_ids:
                        seen_ids.add(fid)
                        all_fills.append(f)
                if len(in_window) < len(batch):
                    break  # crossed window boundary; outer loop will pick up next window
                await asyncio.sleep(0.05)

        cursor = end + 1
        await asyncio.sleep(0.05)

    # Final dedupe + chrono sort (defensive - pagination + windowing can overlap)
    all_fills.sort(key=lambda f: int(f["time"]))
    return all_fills


# ── Position aggregation ──────────────────────────────────────────────────────

def _tid(symbol: str, fill_id: int, order_id: int) -> str:
    return hashlib.md5(f"{symbol}-{fill_id}-{order_id}".encode()).hexdigest()[:16]


def _fills_to_positions(all_fills: list[dict]) -> list[dict]:
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for f in all_fills:
        by_symbol[f["symbol"]].append(f)

    positions: list[dict] = []
    for symbol, fills in by_symbol.items():
        fills.sort(key=lambda x: int(x["time"]))
        hedge = any(f.get("positionSide") in ("LONG", "SHORT") for f in fills)
        if hedge:
            positions.extend(_hedge(symbol, fills))
        else:
            positions.extend(_oneway(symbol, fills))

    positions.sort(key=lambda x: x["exit_time"], reverse=True)

    for p in positions:
        p["entry_date"] = datetime.fromtimestamp(p["entry_time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        p["exit_date"]  = datetime.fromtimestamp(p["exit_time"]  / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        p["note"]       = _notes_store.get(p["id"], "")

    return positions


def _record(f: dict, symbol: str, direction: str, entry_p: float, net_qty: float, entry_t: int) -> dict:
    price    = float(f["price"])
    realized = float(f.get("realizedPnl", 0))
    return {
        "id":           _tid(symbol, int(f["id"]), int(f["orderId"])),
        "symbol":       symbol,
        "direction":    direction,
        "entry_price":  round(entry_p, 8),
        "exit_price":   round(price, 8),
        "qty":          round(abs(net_qty), 8),
        "realized_pnl": round(realized, 6),
        "entry_time":   entry_t,
        "exit_time":    int(f["time"]),
        "duration_min": round((int(f["time"]) - entry_t) / 60000, 1),
        "commission":   round(float(f.get("commission", 0)), 8),
        "winner":       realized > 0,
    }


def _hedge(symbol: str, fills: list[dict]) -> list[dict]:
    positions: list[dict] = []
    for side_label in ("LONG", "SHORT"):
        net = 0.0
        ep = 0.0
        et = 0
        for f in fills:
            if f.get("positionSide") != side_label:
                continue
            qty   = float(f["qty"])
            price = float(f["price"])
            opening = (side_label == "LONG" and f["side"] == "BUY") or \
                      (side_label == "SHORT" and f["side"] == "SELL")
            if opening:
                ep = (ep * net + price * qty) / (net + qty) if net > 0 else price
                if net == 0:
                    et = int(f["time"])
                net += qty
            else:
                if net > 0:
                    positions.append(_record(f, symbol, side_label, ep, min(qty, net), et))
                    net = max(0.0, net - qty)
                    if net == 0:
                        ep = 0.0
    return positions


def _oneway(symbol: str, fills: list[dict]) -> list[dict]:
    positions: list[dict] = []
    net = 0.0
    ep  = 0.0
    et  = 0

    for f in fills:
        qty   = float(f["qty"])
        price = float(f["price"])
        side  = f["side"]

        if side == "BUY":
            if net < 0:
                close = min(qty, abs(net))
                positions.append(_record(f, symbol, "SHORT", ep, close, et))
                net += qty
                if net > 0:
                    ep = price
                    et = int(f["time"])
                elif net == 0:
                    ep = 0.0
            else:
                ep = (ep * net + price * qty) / (net + qty) if net > 0 else price
                if net == 0:
                    et = int(f["time"])
                net += qty
        else:
            if net > 0:
                close = min(qty, net)
                positions.append(_record(f, symbol, "LONG", ep, close, et))
                net -= qty
                if net < 0:
                    ep = price
                    et = int(f["time"])
                elif net == 0:
                    ep = 0.0
            else:
                ep = (ep * abs(net) + price * qty) / (abs(net) + qty) if net < 0 else price
                if net == 0:
                    et = int(f["time"])
                net -= qty

    return positions


# ── Stats ─────────────────────────────────────────────────────────────────────

def _stats(positions: list[dict]) -> dict:
    if not positions:
        return {"total": 0}

    total  = len(positions)
    wins   = [p for p in positions if p["winner"]]
    losses = [p for p in positions if not p["winner"]]

    total_pnl  = sum(p["realized_pnl"] for p in positions)
    total_comm = sum(p["commission"]    for p in positions)
    avg_win    = sum(p["realized_pnl"] for p in wins)   / max(len(wins), 1)
    avg_loss   = sum(p["realized_pnl"] for p in losses) / max(len(losses), 1)
    rr         = abs(avg_win / avg_loss) if avg_loss else 0.0

    sym_pnl: dict[str, float] = {}
    sym_cnt: dict[str, int]   = {}
    for p in positions:
        sym_pnl[p["symbol"]] = sym_pnl.get(p["symbol"], 0.0) + p["realized_pnl"]
        sym_cnt[p["symbol"]] = sym_cnt.get(p["symbol"], 0) + 1

    longs  = [p for p in positions if p["direction"] == "LONG"]
    shorts = [p for p in positions if p["direction"] == "SHORT"]

    streak = 0
    stype  = "none"
    for p in positions:
        t = "win" if p["winner"] else "loss"
        if streak == 0:
            streak = 1; stype = t
        elif t == stype:
            streak += 1
        else:
            break

    equity = peak = max_dd = 0.0
    for p in sorted(positions, key=lambda x: x["exit_time"]):
        equity += p["realized_pnl"]
        peak    = max(peak, equity)
        max_dd  = max(max_dd, peak - equity)

    return {
        "total":               total,
        "wins":                len(wins),
        "losses":              len(losses),
        "win_rate":            round(len(wins) / total * 100, 1),
        "total_pnl":           round(total_pnl, 4),
        "total_commission":    round(total_comm, 4),
        "net_pnl":             round(total_pnl - total_comm, 4),
        "avg_win":             round(avg_win, 4),
        "avg_loss":            round(avg_loss, 4),
        "rr_ratio":            round(rr, 2),
        "best_pair":           max(sym_pnl, key=lambda k: sym_pnl[k]) if sym_pnl else "-",
        "worst_pair":          min(sym_pnl, key=lambda k: sym_pnl[k]) if sym_pnl else "-",
        "current_streak":      streak,
        "current_streak_type": stype,
        "max_drawdown":        round(max_dd, 4),
        "avg_duration_min":    round(sum(p["duration_min"] for p in positions) / total, 1),
        "long_count":          len(longs),
        "short_count":         len(shorts),
        "long_win_rate":       round(sum(1 for p in longs  if p["winner"]) / max(len(longs),  1) * 100, 1),
        "short_win_rate":      round(sum(1 for p in shorts if p["winner"]) / max(len(shorts), 1) * 100, 1),
        "by_symbol":           {k: round(v, 4) for k, v in sorted(sym_pnl.items(), key=lambda x: -abs(x[1]))},
        "trade_count_by_symbol": sym_cnt,
    }


# ── Gemma ─────────────────────────────────────────────────────────────────────

async def _get_available_model() -> str:
    """
    Query Ollama for installed models and return the best available one.
    Priority: gemma4:e4b > gemma4 > gemma3 > first available.
    Mirrors the approach used by brief_generator.py.
    """
    preferred = ["gemma4:e4b", "gemma4", "gemma3:4b", "gemma3"]
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                log.info(f"Journal: Ollama models available: {models}")
                for pref in preferred:
                    for m in models:
                        if pref in m:
                            return m
                if models:
                    return models[0]
    except Exception as e:
        log.warning(f"Journal: could not list Ollama models: {e}")
    return OLLAMA_MODEL  # fall back to env/default


async def _gemma(prompt: str) -> str:
    """
    Call Ollama. Auto-detects the correct model name by querying /api/tags first,
    matching the pattern used by brief_generator.py so it always uses an installed model.
    """
    model = await _get_available_model()
    log.info(f"Journal: calling Ollama model={model}")
    try:
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(OLLAMA_URL, json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 1400},
            })
            if r.status_code != 200:
                body = r.text[:300]
                log.error(f"Journal: Ollama {r.status_code}: {body}")
                return f"[Ollama error {r.status_code}: {body}]"
            return r.json().get("response", "").strip()
    except Exception as e:
        log.error(f"Journal: Ollama call failed: {e}")
        return f"[Gemma error: {e}]"


def _prompt(positions: list[dict], s: dict) -> str:
    lines = "\n".join(
        f"  {p['exit_date']} | {p['symbol']:<12} | {p['direction']:<5} | "
        f"Entry {p['entry_price']} → Exit {p['exit_price']} | "
        f"PnL {p['realized_pnl']:+.4f} | {p['duration_min']}min | "
        f"{'WIN' if p['winner'] else 'LOSS'}"
        for p in positions[:60]
    )
    return f"""You are a senior quantitative trading analyst reviewing a crypto derivatives futures journal.

ACCOUNT STATISTICS (Binance USDT-M, from 2026-04-18):
Total trades: {s.get('total')}  |  Win rate: {s.get('win_rate')}%  ({s.get('wins')}W/{s.get('losses')}L)
Total PnL: {s.get('total_pnl'):+.4f} USDT  |  Net after fees: {s.get('net_pnl'):+.4f} USDT
Avg win: +{s.get('avg_win'):.4f}  |  Avg loss: {s.get('avg_loss'):.4f}  |  R:R: {s.get('rr_ratio'):.2f}x
Max drawdown: -{s.get('max_drawdown'):.4f}  |  Avg duration: {s.get('avg_duration_min'):.0f}min
LONG: {s.get('long_count')} trades ({s.get('long_win_rate')}% WR)  |  SHORT: {s.get('short_count')} trades ({s.get('short_win_rate')}% WR)
Best pair: {s.get('best_pair')}  |  Worst pair: {s.get('worst_pair')}
Streak: {s.get('current_streak')} {s.get('current_streak_type')}(s)

RECENT TRADES (newest first, max 60):
{lines}

Write a tight analysis in plain prose. No markdown syntax - do NOT use #, ##, **, backticks, or bullet characters. Use these six section labels in ALL CAPS on their own line, followed by a colon and one short paragraph (1-2 sentences with specific numbers):

TRADING STYLE:
Exact style (scalp <5min / day 5min-4h / swing >4h). Give percentage split.

EDGE:
Which symbols, direction, duration bucket produce positive expectancy. Where it breaks down.

RISK SCORE:
Score 1-10 from avg_win vs avg_loss, RR vs 1.5x, drawdown vs gross wins, commission drag. Include sub-scores inline.

BEHAVIOR:
Revenge trades, overtrading, pair concentration, or directional bias. Cite one trade.

IMPROVEMENTS:
Three fixes as a numbered sentence list - each: problem with number, exact fix, expected PnL impact.

VERDICT:
Two sentences max: trader level, primary strength, single most critical fix this week.

Rules: Under 260 words total. Direct. Numbers. No disclaimers, no preamble, no closing note."""


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/trades")
async def get_journal_trades(force_refresh: bool = False):
    global _positions_cache, _last_fetch_ts, _last_error

    api_key    = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "").strip()

    if not api_key or not api_secret:
        return {
            "trades": [], "source": "no_keys", "count": 0, "error": None,
            "message": "Add BINANCE_API_KEY and BINANCE_API_SECRET to your backend .env file, then click Refresh.",
        }

    cache_age = time.time() - _last_fetch_ts if _last_fetch_ts else 9999
    if _positions_cache and not force_refresh and cache_age < CACHE_TTL:
        return {
            "trades": _positions_cache,
            "source": "cache",
            "count": len(_positions_cache),
            "error": None,
            "cache_age_sec": round(cache_age),
            "fetched_at": datetime.utcfromtimestamp(_last_fetch_ts).isoformat() + "Z" if _last_fetch_ts else None,
        }

    log.info("Journal: fetching from Binance...")
    try:
        async with httpx.AsyncClient() as client:

            # Verify credentials first
            try:
                await _get(client, "/fapi/v2/account", {}, api_key, api_secret)
            except Exception as e:
                err = str(e)
                _last_error = err
                return {
                    "trades": [], "source": "auth_error", "count": 0,
                    "error": f"Authentication failed: {err}. Ensure the API key has Futures Read permission and no IP restriction, or add your server IP to the whitelist.",
                }

            symbols = await _discover_symbols(client, api_key, api_secret)
            if not symbols:
                return {
                    "trades": [], "source": "no_trades", "count": 0, "error": None,
                    "message": "No futures trades found since 2026-04-18.",
                }

            results = await asyncio.gather(
                *[_fetch_fills(client, s, api_key, api_secret) for s in symbols],
                return_exceptions=True,
            )

        all_fills: list[dict] = []
        for sym, res in zip(symbols, results):
            if isinstance(res, list):
                all_fills.extend(res)
            else:
                log.warning(f"Journal: {sym} error: {res}")

        positions = _fills_to_positions(all_fills)
        _positions_cache = positions
        _last_fetch_ts   = time.time()
        _last_error      = ""
        log.info(f"Journal: {len(positions)} closed positions from {len(all_fills)} fills")
        return {
            "trades": positions,
            "source": "binance_live",
            "count": len(positions),
            "error": None,
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "symbols_scanned": symbols,
        }

    except Exception as e:
        _last_error = str(e)
        log.error(f"Journal: error: {e}", exc_info=True)
        return {"trades": _positions_cache, "source": "error", "count": len(_positions_cache), "error": str(e)}


@router.get("/stats")
async def get_journal_stats():
    resp = await get_journal_trades()
    return {"stats": _stats(resp.get("trades", [])), "error": resp.get("error"), "message": resp.get("message")}


@router.post("/analyze")
async def analyze_journal():
    resp = await get_journal_trades()
    positions = resp.get("trades", [])
    if not positions:
        msg = resp.get("error") or resp.get("message") or "No trades available."
        return {"analysis": f"Cannot analyze: {msg}", "trade_count": 0, "generated_at": datetime.utcnow().isoformat(), "model": OLLAMA_MODEL}
    s = _stats(positions)
    text = await _gemma(_prompt(positions, s))
    result = {"analysis": text, "trade_count": len(positions), "stats_snapshot": s, "generated_at": datetime.utcnow().isoformat(), "model": OLLAMA_MODEL}
    _analysis_cache.clear()
    _analysis_cache.update(result)
    return result


@router.get("/last-analysis")
async def get_last_analysis():
    if not _analysis_cache:
        return {"analysis": None, "message": "No analysis generated yet."}
    return _analysis_cache


@router.post("/note/{trade_id}")
async def save_note(trade_id: str, payload: NotePayload):
    _notes_store[trade_id] = payload.note
    for t in _positions_cache:
        if t.get("id") == trade_id:
            t["note"] = payload.note
    return {"saved": True, "trade_id": trade_id}


@router.get("/note/{trade_id}")
async def get_note(trade_id: str):
    return {"trade_id": trade_id, "note": _notes_store.get(trade_id, "")}


@router.get("/portfolio")
async def get_portfolio():
    """
    Fetch combined portfolio: Futures wallet + Spot USDT balance + Funding USDT balance.
    Frontend shows total_balance = futures + spot + funding in the top header strip.
    """
    api_key    = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "").strip()

    if not api_key or not api_secret:
        return {"error": "no_keys", "portfolio": None}

    # Binance SAPI (Spot/Funding) base
    SAPI = "https://api.binance.com"

    async def _sapi_get(client: httpx.AsyncClient, path: str, params: dict) -> Any:
        """Signed GET to Binance SAPI (spot/saving endpoints)."""
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 6000
        query = "&".join(f"{k}={v}" for k, v in p.items())
        sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        p["signature"] = sig
        r = await client.get(f"{SAPI}{path}", params=p, headers={"X-MBX-APIKEY": api_key}, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"Binance SAPI {r.status_code}: {r.text[:200]}")
        return r.json()

    try:
        async with httpx.AsyncClient() as client:
            # Always fetch futures - required
            fut_account = await _get(client, "/fapi/v2/account", {}, api_key, api_secret)

            # Spot wallet - best effort (may fail on futures-only keys)
            spot_usdt = 0.0
            try:
                spot_account = await _sapi_get(client, "/api/v3/account", {})
                for bal in spot_account.get("balances", []):
                    if bal.get("asset") == "USDT":
                        spot_usdt = float(bal.get("free", 0)) + float(bal.get("locked", 0))
                        break
            except Exception as e:
                log.info(f"Journal: spot wallet not available: {e}")

            # Funding wallet - best effort
            funding_usdt = 0.0
            try:
                funding = await _sapi_get(client, "/sapi/v1/asset/get-funding-asset", {"asset": "USDT"})
                for item in (funding if isinstance(funding, list) else []):
                    if item.get("asset") == "USDT":
                        funding_usdt = float(item.get("free", 0)) + float(item.get("freeze", 0))
                        break
            except Exception as e:
                log.info(f"Journal: funding wallet not available: {e}")

        # Futures breakdown
        fut_wallet    = float(fut_account.get("totalWalletBalance", 0))
        fut_unrealized= float(fut_account.get("totalUnrealizedProfit", 0))
        fut_available = float(fut_account.get("availableBalance", 0))
        pos_margin    = float(fut_account.get("totalPositionInitialMargin", 0))

        # Open positions
        open_positions = []
        for p in fut_account.get("positions", []):
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            upnl    = float(p.get("unrealizedProfit", 0))
            entry   = float(p.get("entryPrice", 0))
            notional= float(p.get("notional", 0))
            lev     = int(p.get("leverage", 1))
            open_positions.append({
                "symbol":         p.get("symbol", ""),
                "side":           "LONG" if amt > 0 else "SHORT",
                "qty":            round(abs(amt), 8),
                "entry_price":    round(entry, 6),
                "notional_usd":   round(abs(notional), 2),
                "unrealized_pnl": round(upnl, 4),
                "leverage":       lev,
                "margin_used":    round(abs(notional) / max(lev, 1), 2),
            })
        open_positions.sort(key=lambda x: abs(x["unrealized_pnl"]), reverse=True)

        total_balance   = fut_wallet + spot_usdt + funding_usdt
        total_unrealized= fut_unrealized

        return {
            "error": None,
            "portfolio": {
                # Futures
                "futures_wallet":      round(fut_wallet, 4),
                "futures_unrealized":  round(fut_unrealized, 4),
                "futures_available":   round(fut_available, 4),
                "futures_margin_used": round(pos_margin, 4),
                "futures_margin_pct":  round((pos_margin / max(fut_wallet, 1)) * 100, 1),
                # Other wallets
                "spot_balance":        round(spot_usdt, 4),
                "funding_balance":     round(funding_usdt, 4),
                # Combined
                "total_balance":       round(total_balance, 4),
                "total_unrealized":    round(total_unrealized, 4),
                # Positions
                "open_positions":      open_positions,
                "open_position_count": len(open_positions),
                "fetched_at":          datetime.utcnow().isoformat(),
            },
        }
    except Exception as e:
        log.error(f"Journal portfolio: {e}", exc_info=True)
        return {"error": str(e), "portfolio": None}


@router.get("/diag")
async def diag():
    """Per-symbol fill counts + windows scanned. Use to verify the windowing fix."""
    api_key    = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return {"error": "no_keys"}

    out: dict[str, Any] = {
        "journal_start_utc": datetime.utcfromtimestamp(JOURNAL_START_MS / 1000).isoformat() + "Z",
        "now_utc":           datetime.utcnow().isoformat() + "Z",
        "cache_age_sec":     round(time.time() - _last_fetch_ts) if _last_fetch_ts else None,
        "cached_positions":  len(_positions_cache),
    }
    async with httpx.AsyncClient() as client:
        symbols = await _discover_symbols(client, api_key, api_secret)
        out["symbols_discovered"] = symbols
        per_symbol = {}
        for s in symbols:
            fills = await _fetch_fills(client, s, api_key, api_secret)
            if fills:
                first_t = datetime.utcfromtimestamp(int(fills[0]["time"]) / 1000).isoformat() + "Z"
                last_t  = datetime.utcfromtimestamp(int(fills[-1]["time"]) / 1000).isoformat() + "Z"
                per_symbol[s] = {"fills": len(fills), "first": first_t, "last": last_t}
            else:
                per_symbol[s] = {"fills": 0}
        out["per_symbol"] = per_symbol
    return out


@router.post("/clear-cache")
async def clear_cache():
    """Force-expire the in-memory cache so the next /trades call re-fetches live."""
    global _last_fetch_ts
    _last_fetch_ts = 0.0
    return {"cleared": True, "message": "Cache expired. Next /trades call will fetch live from Binance."}


@router.get("/debug")
async def debug_env():
    """Diagnostic - checks credentials and connectivity without exposing secrets."""
    key = os.getenv("BINANCE_API_KEY", "")
    sec = os.getenv("BINANCE_API_SECRET", "")

    ping_ok = False
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            ping_ok = (await c.get(f"{BINANCE_FAPI}/fapi/v1/ping")).status_code == 200
    except Exception:
        pass

    return {
        "BINANCE_API_KEY_set":    bool(key),
        "BINANCE_API_KEY_prefix": key[:6] + "..." if key else "(not set)",
        "BINANCE_API_SECRET_set": bool(sec),
        "binance_ping_ok":        ping_ok,
        "cached_trades":          len(_positions_cache),
        "cache_age_sec":          round(time.time() - _last_fetch_ts) if _last_fetch_ts else None,
        "last_error":             _last_error or None,
        "ollama_model":           OLLAMA_MODEL,
        "env_file_checked":       str(_config.PROJECT_ROOT / ".env"),
    }