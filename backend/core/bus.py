"""Bounded, non-blocking pub/sub for the process.

Replaces ``monitoring/event_bus.py``, whose docstring promised bounded
per-subscriber queues with drop-oldest but whose ``publish()`` awaited every
handler inline - a slow subscriber stalled whichever producer loop called it.

Contract
--------
- ``subscribe(topic, handler, maxsize=256, policy="drop_oldest")`` registers
  a handler with its own bounded queue and one consumer task.
- ``publish(topic, payload)`` is **synchronous** and never blocks: it enqueues
  with ``put_nowait``; on a full queue it drops the oldest pending item (or,
  for ``coalesce``, replaces the single pending one) and counts the drop.
- Topic patterns may use ``*`` wildcards (``market.trade.*``).
- A handler that raises is logged and isolated; the consumer task lives on.
- ``recent(n)`` and ``stats()`` expose what happened for ``/api/health`` and
  ``/metrics``.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Literal

logger = logging.getLogger("nexus.bus")

Handler = Callable[[str, Any], Awaitable[None]]
Policy = Literal["drop_oldest", "coalesce"]


class Subscription:
    """One handler, one bounded queue, one consumer task."""

    __slots__ = (
        "delivered",
        "dropped",
        "errors",
        "handler",
        "maxsize",
        "name",
        "pattern",
        "policy",
        "queue",
        "task",
    )

    def __init__(self, pattern: str, handler: Handler, policy: Policy, maxsize: int, name: str) -> None:
        self.pattern = pattern
        self.handler = handler
        self.policy = policy
        self.maxsize = maxsize
        self.name = name
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.delivered = 0
        self.dropped = 0
        self.errors = 0
        self.task: asyncio.Task[None] | None = None

    def matches(self, topic: str) -> bool:
        if topic == self.pattern:
            return True
        return "*" in self.pattern and fnmatch.fnmatchcase(topic, self.pattern)

    @property
    def alive(self) -> bool:
        return self.task is not None and not self.task.done()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pattern": self.pattern,
            "policy": self.policy,
            "maxsize": self.maxsize,
            "queued": self.queue.qsize(),
            "delivered": self.delivered,
            "dropped": self.dropped,
            "errors": self.errors,
            "alive": self.alive,
        }


class EventBus:
    def __init__(self, *, default_maxsize: int = 256, recent_size: int = 128) -> None:
        if default_maxsize <= 0:
            raise ValueError("default_maxsize must be positive")
        self._subs: list[Subscription] = []
        self._default_maxsize = default_maxsize
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_size)
        self._started = False
        self._published = 0

    # -- registration --------------------------------------------------------

    def subscribe(
        self,
        topic: str,
        handler: Handler,
        *,
        maxsize: int | None = None,
        policy: Policy = "drop_oldest",
        name: str | None = None,
    ) -> Subscription:
        """Register ``handler`` for ``topic`` (exact or ``*``-wildcard pattern).

        ``coalesce`` keeps only the newest pending payload (queue depth 1) -
        right for snapshots such as health or a book, wrong for fills.
        """
        size = 1 if policy == "coalesce" else int(maxsize or self._default_maxsize)
        if size <= 0:
            raise ValueError("maxsize must be positive")
        label = name or str(getattr(handler, "__qualname__", None) or "handler")
        sub = Subscription(topic, handler, policy, size, label)
        self._subs.append(sub)
        if self._started:
            self._spawn(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)
        if sub.task is not None:
            sub.task.cancel()
            sub.task = None

    # -- publishing ----------------------------------------------------------

    def publish(self, topic: str, payload: Any) -> int:
        """Enqueue ``payload`` for every matching subscriber. Never blocks.

        Returns the number of subscribers the event was queued for. A full
        queue drops its oldest item (``drop_oldest``) or its only item
        (``coalesce``) and increments that subscription's ``dropped`` counter.
        """
        self._published += 1
        self._recent.append({"ts": time.time(), "topic": topic, "payload": payload})
        queued = 0
        item = (topic, payload)
        for sub in self._subs:
            if not sub.matches(topic):
                continue
            try:
                sub.queue.put_nowait(item)
            except asyncio.QueueFull:
                try:
                    sub.queue.get_nowait()
                    sub.queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                sub.dropped += 1
                try:
                    sub.queue.put_nowait(item)
                except asyncio.QueueFull:
                    sub.dropped += 1
                    continue
            queued += 1
        return queued

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Spawn consumer tasks for every subscription. Idempotent."""
        self._started = True
        for sub in self._subs:
            if not sub.alive:
                self._spawn(sub)

    async def stop(self) -> None:
        self._started = False
        tasks = [sub.task for sub in self._subs if sub.task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001  # reason: shutdown reports a consumer's last error, it does not fail on it
                logger.exception("bus consumer raised during shutdown")
        for sub in self._subs:
            sub.task = None

    async def drain(self) -> None:
        """Wait until every queue is empty and every handler has returned (tests)."""
        await asyncio.gather(*(sub.queue.join() for sub in self._subs))

    def _spawn(self, sub: Subscription) -> None:
        sub.task = asyncio.create_task(self._consume(sub), name=f"bus:{sub.name}")

    async def _consume(self, sub: Subscription) -> None:
        while True:
            topic, payload = await sub.queue.get()
            try:
                await sub.handler(topic, payload)
                sub.delivered += 1
            except asyncio.CancelledError:
                sub.queue.task_done()
                raise
            except Exception:  # noqa: BLE001  # reason: one bad handler must not kill delivery to itself or others
                sub.errors += 1
                logger.exception("bus handler %s failed on topic %s", sub.name, topic)
            sub.queue.task_done()

    # -- introspection -------------------------------------------------------

    def recent(self, n: int = 32) -> list[dict[str, Any]]:
        return list(self._recent)[-n:]

    def stats(self) -> dict[str, Any]:
        return {
            "published": self._published,
            "started": self._started,
            "subscriptions": [sub.snapshot() for sub in self._subs],
            "dropped_total": sum(sub.dropped for sub in self._subs),
        }

    @property
    def subscriptions(self) -> list[Subscription]:
        return list(self._subs)
