"""Binance USDⓈ-M REST for the request path, with the rate guard honoured.

Why a dedicated executor: ``/api/crypto/strip`` fires ten concurrent calls, so
a fresh ``ThreadPoolExecutor`` per call was measurable. Why threads at all:
the async resolvers are blocked on this operator's network while the system
resolver works, so the blocking ``urllib`` path in ``backend.data.http`` is
the one that survives.

Why the guard matters here. ``ingestion/rate_guard.py`` was written to parse
Binance's ``banned until <epoch-ms>`` out of a 418 and suspend calls to that
host until it expires - and the request path never consulted it. Only the WS
kline seed and the OI/funding pollers did. So during a ban every chart request
kept calling a host that answers 418, which is how a short ban becomes a long
one. Observed live: ``/fapi/v1/ping`` answering 418 while
``/api/klines``, ``/api/ticker``, ``/api/symbols/search`` and
``/api/indicators`` all returned 502.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from backend.data.http import HttpStatusError, fetch_json
from backend.ingestion.rate_guard import (
    BINANCE_FUTURES_HOST,
    BINANCE_SPOT_HOST,
    cooldown_remaining,
    note_http_error,
    record_success,
    should_skip,
)
from backend.ops.logutil import warn_throttled

logger = logging.getLogger("nexus.binance_rest")

FUTURES_BASE = "https://fapi.binance.com"
SPOT_BASE = "https://api.binance.com"

# Sized for the widest fan-out on the request path (the ten-symbol strip).
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="binance-rest")

_skipped = 0
_failed = 0
_ok = 0


def _get(base: str, host: str, path: str, timeout: float) -> Any:
    """Blocking GET that respects, and feeds, the rate guard. None on failure."""
    global _skipped, _failed, _ok
    if should_skip(host):
        _skipped += 1
        warn_throttled(
            logger,
            f"ratelimit:{host}",
            "%s REST suspended for %.0fs more (rate-limit cooldown) - skipping %s",
            host,
            cooldown_remaining(host),
            path,
            every_s=60.0,
        )
        return None
    try:
        data = fetch_json(f"{base}{path}", timeout=timeout)
    except HttpStatusError as exc:
        # 418/429 carry the ban deadline; recording it is what stops the next
        # request from extending the ban.
        banned = note_http_error(host, exc.status, exc.body)
        _failed += 1
        warn_throttled(
            logger,
            f"fut_get:{path.split('?')[0]}",
            "Binance REST %s -> HTTP %s%s",
            path,
            exc.status,
            " (rate-limited; backing off)" if banned else "",
        )
        return None
    except Exception as exc:  # noqa: BLE001  # reason: callers treat None as "venue unavailable" and serve cached data
        _failed += 1
        warn_throttled(logger, f"fut_get:{path.split('?')[0]}", "Binance REST %s failed: %s", path, exc)
        return None
    record_success(host)
    _ok += 1
    return data


def futures_get(path: str, timeout: float = 10.0) -> Any:
    """Blocking USDⓈ-M futures call. Run it in a thread; prefer :func:`afetch`."""
    return _get(FUTURES_BASE, BINANCE_FUTURES_HOST, path, timeout)


def spot_get(path: str, timeout: float = 10.0) -> Any:
    """Blocking spot call (the derivatives strip compares perp against spot)."""
    return _get(SPOT_BASE, BINANCE_SPOT_HOST, path, timeout)


async def afetch(path: str, timeout: float = 10.0) -> Any:
    """Futures call off the event loop, on the shared executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, lambda: futures_get(path, timeout))


async def aspot(path: str, timeout: float = 10.0) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, lambda: spot_get(path, timeout))


def stats() -> dict[str, Any]:
    return {
        "ok": _ok,
        "failed": _failed,
        "skipped_by_rate_guard": _skipped,
        "futures_cooldown_s": round(cooldown_remaining(BINANCE_FUTURES_HOST), 1),
        "spot_cooldown_s": round(cooldown_remaining(BINANCE_SPOT_HOST), 1),
    }


def shutdown(wait: bool = False) -> None:
    """Release the executor. ``wait=False`` so teardown is not held by an
    in-flight 20s fetch."""
    _pool.shutdown(wait=wait, cancel_futures=True)
