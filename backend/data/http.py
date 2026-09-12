"""HTTP helpers with an explicit, logged TLS fallback.

Behind the operator's ISP (PLDT) TLS interception makes strict certificate
verification fail against some venues. The previous code retried with
``CERT_NONE`` in three separate places and swallowed the failure, which made
a man-in-the-middle indistinguishable from the proxy case it was written
for. This module is the single place a downgrade can happen: it logs the
first downgrade per host at WARNING and counts every one so ``/metrics``
can expose ``nexus_tls_downgrades_total``.

Blocking ``urllib`` in a worker thread is deliberate - the async resolvers
used by httpx/aiohttp are blocked on the same networks while the system
resolver works. Use :func:`afetch_json` from coroutines.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
import urllib.error
import urllib.request
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger("nexus.http")

USER_AGENT = "Nexus/0.3"

_downgraded_hosts: set[str] = set()
_downgrade_counts: Counter[str] = Counter()
_lock = threading.Lock()


class HttpStatusError(Exception):
    """A completed HTTP exchange with a non-2xx status. Never triggers a TLS downgrade."""

    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.body = body
        self.url = url


def tls_downgrade_counts() -> dict[str, int]:
    """Per-host count of permissive-TLS fallbacks since process start."""
    with _lock:
        return dict(_downgrade_counts)


def _permissive_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _note_downgrade(host: str, err: BaseException) -> None:
    with _lock:
        _downgrade_counts[host] += 1
        first = host not in _downgraded_hosts
        _downgraded_hosts.add(host)
    if first:
        logger.warning(
            "tls_downgrade host=%s reason=%s - certificate verification disabled for this host "
            "for the rest of the process (expected behind an intercepting ISP; a red flag anywhere else)",
            host,
            err,
        )
    else:
        logger.debug("tls_downgrade host=%s repeat reason=%s", host, err)


def _read_body(err: urllib.error.HTTPError) -> str:
    try:
        return err.read().decode("utf-8", "replace")[:1000]
    except Exception:  # noqa: BLE001  # reason: body is diagnostic only
        return ""


def _open(url: str, timeout: float, headers: dict[str, str] | None, ctx: ssl.SSLContext | None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return bytes(resp.read())


def fetch_bytes(
    url: str,
    *,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
    permissive_ok: bool = True,
    strict_timeout: float | None = None,
) -> bytes:
    """Blocking GET.

    Strict TLS first. If that fails at the transport level and ``permissive_ok``
    is set, retry once with verification disabled and record the downgrade.
    HTTP error statuses raise :class:`HttpStatusError` immediately - a 418 ban
    or a 404 is a server answer, not a reason to weaken TLS.
    """
    host = urlsplit(url).hostname or url
    try:
        return _open(url, strict_timeout or timeout, headers, None)
    except urllib.error.HTTPError as err:
        raise HttpStatusError(err.code, _read_body(err), url) from err
    except Exception as err:  # noqa: BLE001  # reason: any transport failure may be TLS interception; retried permissively below
        if not permissive_ok:
            raise
        transport_error = err
    _note_downgrade(host, transport_error)
    try:
        return _open(url, timeout, headers, _permissive_context())
    except urllib.error.HTTPError as err:
        raise HttpStatusError(err.code, _read_body(err), url) from err


def fetch_json(url: str, **kwargs: Any) -> Any:
    """Blocking GET + JSON decode. See :func:`fetch_bytes` for the TLS policy."""
    return json.loads(fetch_bytes(url, **kwargs))


async def afetch_json(url: str, **kwargs: Any) -> Any:
    """Async wrapper: runs :func:`fetch_json` in a worker thread."""
    return await asyncio.to_thread(fetch_json, url, **kwargs)
