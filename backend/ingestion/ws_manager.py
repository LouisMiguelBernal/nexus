"""
Nexus - Async WebSocket Manager

Manages concurrent WS connections to all exchanges, with:
- Auto-reconnect (exponential backoff, SSL-interception fallback)
- **Gap-fill tracking** (P0-4): each connection records `last_event_time` on
  every message. On reconnect, consumers can query `gap_report(name)` to
  learn the outage window and trigger a REST backfill into the same
  in-memory buffers before trusting live tape again.

The gap-fill backfill itself is per-exchange (each *_ws.py wires its own REST
client) - this module exposes the hook, not the implementation, because the
backfill endpoint differs per venue (Binance klines vs Bybit trades vs OKX etc.).
"""

import asyncio
import json
import logging
import ssl
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

# Build SSL contexts
# Strict: uses certifi CA bundle for trusted connections
# Permissive: for networks with SSL interception (corporate firewalls, antivirus)
try:
    import certifi
    _ssl_strict = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_strict = ssl.create_default_context()

_ssl_permissive = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_ssl_permissive.check_hostname = False
_ssl_permissive.verify_mode = ssl.CERT_NONE

logger = logging.getLogger("nexus.ws_manager")


class WSConnection:
    """Single WebSocket connection with auto-reconnect."""

    def __init__(
        self,
        name: str,
        url: str,
        subscribe_msg: Optional[dict | list] = None,
        on_message: Optional[Callable] = None,
        max_retries: int = 50,
        retry_delay: float = 2.0,
        on_gap: Optional[Callable[[str, float, float], Awaitable[Any]]] = None,
        app_ping_msg: Optional[dict] = None,
        app_ping_interval: float = 25.0,
    ):
        self.name = name
        self.url = url
        self.subscribe_msg = subscribe_msg
        self.on_message = on_message
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._ws = None
        self._running = False
        self._retries = 0
        self._use_permissive_ssl = False  # auto-detected on SSL failures

        # Application-layer keepalive (e.g. MEXC requires `{"method":"ping"}`
        # every ~60s on top of WS-level pings, otherwise the server drops).
        self.app_ping_msg = app_ping_msg
        self.app_ping_interval = app_ping_interval
        self._ping_task: Optional[asyncio.Task] = None

        # --- Gap-fill tracking (P0-4) ---------------------------------
        # Monotonic wall-clock of the last message we successfully processed
        # for this stream. Used by consumers to size a REST backfill window
        # on reconnect.
        self._last_event_time: Optional[float] = None
        # Wall-clock at the moment the current connection went down (set in
        # the disconnect branches, cleared on successful reconnect).
        self._disconnect_started_at: Optional[float] = None
        # Gap-fill callback: await on_gap(name, gap_start_ts, gap_end_ts)
        # *after* a successful reconnect so the caller can REST-backfill and
        # emit a `gap_filled` event downstream.
        self.on_gap = on_gap
        # Rolling log of gap events (bounded) for /api/health exposure.
        self._gap_log: List[Dict[str, float]] = []
        self._gap_log_cap = 64

    def _get_ssl(self):
        """Get SSL context - strict first, permissive if network intercepts SSL."""
        if not self.url.startswith("wss://"):
            return None
        if self._use_permissive_ssl:
            return _ssl_permissive
        return _ssl_strict

    async def connect(self):
        self._running = True
        while self._running and self._retries < self.max_retries:
            try:
                async with websockets.connect(
                    self.url,
                    ssl=self._get_ssl(),
                    ping_interval=20,
                    ping_timeout=10,
                    open_timeout=30,  # OKX needs longer handshake
                    close_timeout=10,
                    max_size=10 * 1024 * 1024,  # 10MB max message
                ) as ws:
                    self._ws = ws
                    self._retries = 0
                    logger.info(f"[{self.name}] Connected to {self.url}")

                    # --- Gap-fill handoff (P0-4) -------------------------
                    # If we have a known last_event_time AND we went down,
                    # fire the on_gap callback with (name, start, end) so
                    # the consumer can REST-backfill before trusting tape.
                    gap_end = time.time()
                    if (
                        self._disconnect_started_at is not None
                        and self._last_event_time is not None
                        and gap_end - self._last_event_time > 1.0
                    ):
                        gap_start = self._last_event_time
                        entry = {
                            "start": gap_start,
                            "end": gap_end,
                            "duration_s": round(gap_end - gap_start, 3),
                        }
                        self._gap_log.append(entry)
                        if len(self._gap_log) > self._gap_log_cap:
                            self._gap_log = self._gap_log[-self._gap_log_cap :]
                        logger.warning(
                            f"[{self.name}] Reconnected after {entry['duration_s']:.2f}s outage - "
                            f"firing gap-fill hook"
                        )
                        if self.on_gap is not None:
                            try:
                                await self.on_gap(self.name, gap_start, gap_end)
                            except Exception:
                                logger.exception(
                                    f"[{self.name}] on_gap callback raised - tape may have holes"
                                )
                    self._disconnect_started_at = None

                    if self.subscribe_msg:
                        msg = self.subscribe_msg
                        if isinstance(msg, dict):
                            await ws.send(json.dumps(msg))
                        elif isinstance(msg, list):
                            for m in msg:
                                await ws.send(json.dumps(m))
                        logger.info(f"[{self.name}] Subscribed")

                    # Application-layer keepalive (MEXC etc.)
                    if self.app_ping_msg:
                        async def _app_ping():
                            try:
                                while self._running and self._ws is not None:
                                    await asyncio.sleep(self.app_ping_interval)
                                    if self._ws is None:
                                        return
                                    try:
                                        await ws.send(json.dumps(self.app_ping_msg))
                                    except Exception:
                                        return
                            except asyncio.CancelledError:
                                pass
                        self._ping_task = asyncio.create_task(_app_ping())

                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(raw)
                            # Stamp *before* handing off so consumers crashing
                            # inside on_message don't desync our gap accounting.
                            self._last_event_time = time.time()
                            if self.on_message:
                                await self.on_message(self.name, data)
                        except json.JSONDecodeError:
                            logger.warning(f"[{self.name}] Non-JSON message")

            except ConnectionClosed as e:
                logger.warning(f"[{self.name}] Disconnected: {e}")
                if self._disconnect_started_at is None:
                    self._disconnect_started_at = time.time()
                if self._ping_task is not None:
                    self._ping_task.cancel()
                    self._ping_task = None
            except ssl.SSLCertVerificationError as e:
                if self._disconnect_started_at is None:
                    self._disconnect_started_at = time.time()
                if not self._use_permissive_ssl:
                    logger.warning(
                        f"[{self.name}] SSL interception detected (firewall/antivirus). "
                        f"Switching to permissive SSL for market data feeds."
                    )
                    self._use_permissive_ssl = True
                    self._retries = 0  # reset retries since we're trying a new approach
                    continue
                logger.error(f"[{self.name}] SSL error even in permissive mode: {e}")
            except Exception as e:
                if self._disconnect_started_at is None:
                    self._disconnect_started_at = time.time()
                err_msg = str(e)
                if ("CERTIFICATE_VERIFY_FAILED" in err_msg or "untrusted" in err_msg.lower()
                        or "blocking-page" in err_msg.lower()):
                    if not self._use_permissive_ssl:
                        logger.warning(
                            f"[{self.name}] SSL interception detected. "
                            f"Switching to permissive SSL for market data feeds."
                        )
                        self._use_permissive_ssl = True
                        self._retries = 0
                        continue
                if "prohibitedaccess" in err_msg.lower() or "isn't a valid URI" in err_msg:
                    logger.error(
                        f"[{self.name}] ISP is blocking this exchange domain. "
                        f"Use a VPN to bypass ISP restrictions."
                    )
                    # Don't spam retries if ISP is blocking
                    self._retries = self.max_retries - 5
                else:
                    logger.error(f"[{self.name}] Error: {e}")

            if self._running:
                self._retries += 1
                wait = min(self.retry_delay * (2 ** min(self._retries, 6)), 120)
                logger.info(f"[{self.name}] Reconnecting in {wait:.1f}s (attempt {self._retries})")
                await asyncio.sleep(wait)

        if self._retries >= self.max_retries:
            logger.error(f"[{self.name}] Max retries reached, giving up")

    async def disconnect(self):
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info(f"[{self.name}] Disconnected")

    # ------------------------------------------------------------------
    # Gap-fill introspection (P0-4)
    # ------------------------------------------------------------------

    @property
    def last_event_time(self) -> Optional[float]:
        """Wall-clock of the last successfully processed message, or None."""
        return self._last_event_time

    @property
    def seconds_since_last_event(self) -> Optional[float]:
        if self._last_event_time is None:
            return None
        return time.time() - self._last_event_time

    @property
    def gap_log(self) -> List[Dict[str, float]]:
        """Bounded log of recent (start, end, duration_s) gap events."""
        return list(self._gap_log)


class WSManager:
    """Manages multiple concurrent WebSocket connections."""

    def __init__(self):
        self._connections: Dict[str, WSConnection] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def add(self, conn: WSConnection):
        self._connections[conn.name] = conn

    async def start_all(self):
        for name, conn in self._connections.items():
            task = asyncio.create_task(conn.connect())
            self._tasks[name] = task
            logger.info(f"Started WS task: {name}")

    async def stop_all(self):
        for name, conn in self._connections.items():
            await conn.disconnect()
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("All WS connections stopped")

    async def restart(self, name: str):
        if name in self._connections:
            conn = self._connections[name]
            await conn.disconnect()
            if name in self._tasks:
                self._tasks[name].cancel()
            self._tasks[name] = asyncio.create_task(conn.connect())
            logger.info(f"Restarted WS: {name}")

    @property
    def status(self) -> Dict[str, bool]:
        return {
            name: conn._ws is not None and conn._running
            for name, conn in self._connections.items()
        }

    # ------------------------------------------------------------------
    # Gap-fill introspection (P0-4)
    # ------------------------------------------------------------------

    def gap_report(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Report last-event staleness + historical gap log per connection.

        Consumers (main.py /api/health, monitoring.staleness, etc.) call this
        to decide whether a REST backfill is needed. Empty `gap_log` with a
        non-None `last_event_time` = clean session.
        """
        def _one(conn: WSConnection) -> Dict[str, Any]:
            return {
                "connected": conn._ws is not None and conn._running,
                "last_event_time": conn.last_event_time,
                "seconds_since_last_event": conn.seconds_since_last_event,
                "gap_log": conn.gap_log,
            }

        if name is not None:
            if name not in self._connections:
                return {"error": f"unknown connection: {name}"}
            return _one(self._connections[name])
        return {name: _one(conn) for name, conn in self._connections.items()}
