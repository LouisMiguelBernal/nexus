"""
Nexus - REST rate-limit guard (Binance ban-aware backoff)

Binance Futures answers HTTP 418 (code -1003) with a message like
``"Way too many requests; IP(x.x.x.x) banned until 1783962718662."`` when a
client exceeds the request-weight budget. The trap: if the 30s OI/funding
pollers and the 2s aggTrade fallback keep hammering ``fapi.binance.com``
*during* an active ban, Binance **extends** the ban - a self-inflicted outage
that never clears. That is exactly what took the backend down.

This module is a shared, framework-agnostic cooldown registry. Fetchers:

  1. call ``should_skip(host)`` and bail early while a cooldown is active, and
  2. report each completed response via ``record_response(host, status, body)``
     (or ``note_http_error(...)`` for urllib), plus ``record_success(host)``.

On a 418/429 (or any body carrying ``-1003``) it parses the explicit
"banned until <epoch-ms>" deadline and suspends *all* calls to that host until
then; when no deadline is present it falls back to exponential backoff
(60s → 600s cap). Only Binance hosts ever register a cooldown - OKX/MEXC
callers simply never trip the guard, so their polling is unaffected.

Thread-safe: the aggTrade poller runs fetches in a ThreadPoolExecutor, so the
registry is guarded by a lock.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

logger = logging.getLogger("nexus.rate_guard")

# Canonical host keys - callers import these so a typo can't silently create a
# second, never-checked cooldown bucket.
BINANCE_FUTURES_HOST = "fapi.binance.com"
BINANCE_SPOT_HOST = "api.binance.com"

# host → epoch seconds until which every request must be suppressed.
_cooldown_until: dict[str, float] = {}
# host → consecutive rate-limit count without an explicit deadline (drives the
# exponential backoff schedule).
_backoff_step: dict[str, int] = {}
_lock = threading.Lock()

# Backoff for rate-limit responses that carry no explicit ban deadline.
_BACKOFF_BASE_S = 60.0
_BACKOFF_MAX_S = 600.0  # 10 min cap

# "banned until 1783962718662" - Binance reports epoch MILLISECONDS (13 digits),
# but accept 10-16 to be defensive against seconds/micros.
_BANNED_UNTIL_RE = re.compile(r"banned until\s*(\d{10,16})")


def _now() -> float:
    return time.time()


def should_skip(host: str) -> bool:
    """True while ``host`` is inside an active cooldown window.

    Side effect: when a cooldown has just expired it is cleared and a single
    "resuming" line is logged, so callers see exactly one recovery message.
    """
    with _lock:
        until = _cooldown_until.get(host)
        if until is None:
            return False
        if until <= _now():
            _cooldown_until.pop(host, None)
            logger.warning("rate_guard: %s cooldown lifted - resuming requests", host)
            return False
        return True


def cooldown_remaining(host: str) -> float:
    """Seconds left on ``host``'s cooldown (0.0 if none/expired)."""
    with _lock:
        until = _cooldown_until.get(host, 0.0)
    return max(0.0, until - _now())


def _apply_cooldown(host: str, until_ts: float, reason: str) -> None:
    with _lock:
        prev = _cooldown_until.get(host, 0.0)
        # Never shorten an existing (longer) ban - a later soft-backoff must not
        # undercut a hard deadline that is further out.
        if until_ts <= prev:
            return
        _cooldown_until[host] = until_ts
    logger.warning(
        "rate_guard: %s suspended for %ds (%s)",
        host, int(max(0.0, until_ts - _now())), reason,
    )


def _parse_deadline(body_text: str) -> Optional[float]:
    m = _BANNED_UNTIL_RE.search(body_text or "")
    if not m:
        return None
    ts_ms = int(m.group(1))
    # Heuristic: 13-digit values are ms; shorter are already seconds.
    return ts_ms / 1000.0 if ts_ms > 1e11 else float(ts_ms)


def _is_rate_limited(status_code: int, body_text: str) -> bool:
    return status_code in (418, 429) or "-1003" in (body_text or "")


def record_response(host: str, status_code: int, body_text: str = "") -> bool:
    """Report a completed HTTP response.

    Returns True when the response was a rate-limit signal (and a cooldown was
    set/extended) so the caller can treat it as a failure and skip parsing.
    """
    if not _is_rate_limited(status_code, body_text):
        return False

    deadline = _parse_deadline(body_text)
    if deadline is not None:
        # +1s pad so we don't fire the very instant the ban lifts.
        _apply_cooldown(host, deadline + 1.0, f"HTTP {status_code} ban deadline")
        with _lock:
            _backoff_step[host] = 0
        return True

    # No explicit deadline → exponential backoff.
    with _lock:
        step = _backoff_step.get(host, 0)
        _backoff_step[host] = step + 1
    delay = min(_BACKOFF_BASE_S * (2 ** step), _BACKOFF_MAX_S)
    _apply_cooldown(host, _now() + delay, f"HTTP {status_code} backoff #{step + 1}")
    return True


def note_http_error(host: str, status_code: int, body_text: str = "") -> bool:
    """Alias for urllib callers that only reach the guard from an exception
    handler (``HTTPError.code`` / ``HTTPError.read()``)."""
    return record_response(host, status_code, body_text)


def record_success(host: str) -> None:
    """Clear soft-backoff state after a healthy response so the next transient
    429 starts the schedule from the base delay again."""
    with _lock:
        if _backoff_step.get(host):
            _backoff_step[host] = 0


def reset(host: Optional[str] = None) -> None:
    """Clear cooldown state. ``None`` clears everything (test/ops hook)."""
    with _lock:
        if host is None:
            _cooldown_until.clear()
            _backoff_step.clear()
        else:
            _cooldown_until.pop(host, None)
            _backoff_step.pop(host, None)
