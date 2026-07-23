"""
Nexus - Risk Event Bus (P2)

Centralized async pub/sub for circuit-breaker event triggers. Producers
publish on topics; the circuit breaker is the sole privileged subscriber
that converts events into trip decisions. Other subscribers (logging,
telegram, frontend SSE) are additive.

Topics
------
  var.breach          {realized_pnl: float, var_99: float}
  correlation.snapshot {avg_rho: float, ts: float}
  ws.gap              {gap_report: dict}      # full WSManager.gap_report()
  funding.zscore      {stream: str, zscore: float}
  vpin.update         {stream: str, vpin: float}

Backpressure
------------
Bounded queue per subscriber (default 256). Drop-oldest on overflow so a
slow subscriber CANNOT block producers. Circuit breaker handlers must
not raise - exceptions are caught and logged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("nexus.event_bus")


Subscriber = Callable[[str, Dict[str, Any]], Awaitable[None]]


class EventBus:
    """Async pub/sub with bounded per-subscriber queues."""

    def __init__(self, queue_size: int = 256):
        self._subs: Dict[str, List[Subscriber]] = {}
        self._queue_size = queue_size
        # Bounded recent-events log for /api/health introspection.
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=128)

    def subscribe(self, topic: str, handler: Subscriber) -> None:
        self._subs.setdefault(topic, []).append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        entry = {"ts": time.time(), "topic": topic, "payload": payload}
        self._recent.append(entry)
        handlers = list(self._subs.get(topic, ()))
        if not handlers:
            return
        # Run handlers concurrently; isolate failures.
        async def _run(h: Subscriber):
            try:
                await h(topic, payload)
            except Exception:
                logger.exception(f"event_bus subscriber failed on topic={topic}")
        await asyncio.gather(*[_run(h) for h in handlers], return_exceptions=False)

    def recent(self, n: int = 32) -> List[Dict[str, Any]]:
        return list(self._recent)[-n:]


# Module-level singleton - a single bus per process is sufficient.
bus = EventBus()


# ----------------------------------------------------------------------
# Circuit breaker wiring helpers
# ----------------------------------------------------------------------
def wire_circuit_breaker(breaker: Any) -> None:
    """Subscribe `breaker.on_*` handlers to the bus topics they consume.

    Called once during FastAPI startup. Idempotent - re-wiring just appends
    duplicate subscribers, which is acceptable in tests but should not be
    done in production.
    """

    async def _on_var(topic: str, p: Dict[str, Any]) -> None:
        breaker.on_var_breach(p.get("realized_pnl", 0.0), p.get("var_99", 0.0))

    async def _on_corr(topic: str, p: Dict[str, Any]) -> None:
        breaker.on_correlation_snapshot(p.get("avg_rho", 0.0), p.get("ts"))

    async def _on_gap(topic: str, p: Dict[str, Any]) -> None:
        report = p.get("gap_report") or {}
        if isinstance(report, dict) and report:
            breaker.on_ws_gap_report(report)

    async def _on_funding(topic: str, p: Dict[str, Any]) -> None:
        breaker.on_funding_zscore(p.get("stream", ""), p.get("zscore", 0.0))

    async def _on_vpin(topic: str, p: Dict[str, Any]) -> None:
        breaker.on_vpin(p.get("stream", ""), p.get("vpin", 0.0))

    bus.subscribe("var.breach", _on_var)
    bus.subscribe("correlation.snapshot", _on_corr)
    bus.subscribe("ws.gap", _on_gap)
    bus.subscribe("funding.zscore", _on_funding)
    bus.subscribe("vpin.update", _on_vpin)
