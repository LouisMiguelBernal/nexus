"""Subscribe the circuit breaker's event handlers to bus topics.

Moved from ``monitoring/event_bus.py`` so the bus stays generic and the
breaker's topic contract lives next to the breaker.
"""

from __future__ import annotations

from typing import Any

from backend.core.bus import EventBus
from backend.core.events import Topic


def wire_circuit_breaker(bus: EventBus, breaker: Any) -> None:
    """Subscribe ``breaker.on_*`` handlers. Call once at startup.

    Every subscription coalesces: the breaker only cares about the latest
    reading of each feed, and a burst must never queue up stale trips.
    """

    async def _on_var(topic: str, p: dict[str, Any]) -> None:
        breaker.on_var_breach(p.get("realized_pnl", 0.0), p.get("var_99", 0.0))

    async def _on_corr(topic: str, p: dict[str, Any]) -> None:
        breaker.on_correlation_snapshot(p.get("avg_rho", 0.0), p.get("ts"))

    async def _on_gap(topic: str, p: dict[str, Any]) -> None:
        report = p.get("gap_report") or {}
        if isinstance(report, dict) and report:
            breaker.on_ws_gap_report(report)

    async def _on_funding(topic: str, p: dict[str, Any]) -> None:
        breaker.on_funding_zscore(p.get("stream", ""), p.get("zscore", 0.0))

    async def _on_vpin(topic: str, p: dict[str, Any]) -> None:
        breaker.on_vpin(p.get("stream", ""), p.get("vpin", 0.0))

    bus.subscribe(Topic.VAR_BREACH, _on_var, policy="coalesce", name="breaker.var")
    bus.subscribe(Topic.CORRELATION_SNAPSHOT, _on_corr, policy="coalesce", name="breaker.correlation")
    bus.subscribe(Topic.WS_GAP, _on_gap, policy="coalesce", name="breaker.ws_gap")
    bus.subscribe(Topic.FUNDING_ZSCORE, _on_funding, maxsize=32, name="breaker.funding")
    bus.subscribe(Topic.VPIN_UPDATE, _on_vpin, maxsize=32, name="breaker.vpin")
