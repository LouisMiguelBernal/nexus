"""The time seam.

Strategies and the execution engine never call ``time.time()`` directly; they
ask a ``Clock``. ``LiveClock`` is wall time. ``SimClock`` is driven by the
backtest engine, whose historical feed advances it bar by bar - so the same
strategy code runs in a backtest and in paper trading (ADR 0004).
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float:
        """Seconds since the epoch."""
        ...

    def now_ms(self) -> int: ...

    async def sleep(self, seconds: float) -> None: ...


class LiveClock:
    def now(self) -> float:
        return time.time()

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class SimClock:
    """Deterministic clock. ``sleep`` advances time instead of waiting."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def now_ms(self) -> int:
        return int(self._now * 1000)

    async def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("cannot sleep a negative duration")
        self._now += seconds

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("cannot advance backwards")
        self._now += seconds

    def set(self, ts: float) -> None:
        if ts < self._now:
            raise ValueError(f"clock cannot move backwards ({ts} < {self._now})")
        self._now = float(ts)
