"""TTL cache and single-flight for request paths.

``main.py`` grew eight ad-hoc ``dict`` caches keyed by tuples, none bounded,
each with its own TTL check. ``TTLCache`` is the one shape they share;
``SingleFlight`` makes concurrent callers of the same expensive fetch share
one in-flight result instead of stampeding a venue.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any


class TTLCache[K: Hashable, V]:
    def __init__(self, *, ttl_s: float, maxsize: int = 512, clock: Callable[[], float] = time.time) -> None:
        if ttl_s <= 0 or maxsize <= 0:
            raise ValueError("ttl_s and maxsize must be positive")
        self.ttl_s = float(ttl_s)
        self.maxsize = int(maxsize)
        self._clock = clock
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: K) -> V | None:
        entry = self._data.get(key)
        if entry is None:
            self.misses += 1
            return None
        stored_at, value = entry
        if self._clock() - stored_at >= self.ttl_s:
            del self._data[key]
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: K, value: V) -> None:
        self._data[key] = (self._clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def invalidate(self, key: K) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict[str, Any]:
        return {
            "size": len(self._data),
            "maxsize": self.maxsize,
            "ttl_s": self.ttl_s,
            "hits": self.hits,
            "misses": self.misses,
        }


class SingleFlight[K: Hashable, V]:
    """Coalesce concurrent calls for the same key into one execution."""

    def __init__(self) -> None:
        self._inflight: dict[K, asyncio.Future[V]] = {}

    async def do(self, key: K, factory: Callable[[], Awaitable[V]]) -> V:
        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[V] = loop.create_future()
        self._inflight[key] = future
        try:
            result = await factory()
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        else:
            if not future.done():
                future.set_result(result)
            return result
        finally:
            self._inflight.pop(key, None)

    def inflight(self) -> int:
        return len(self._inflight)


async def cached[K: Hashable, V](
    cache: TTLCache[K, V],
    flight: SingleFlight[K, V],
    key: K,
    factory: Callable[[], Awaitable[V]],
) -> V:
    """TTL-cached, single-flighted fetch: the request-path idiom in one call."""
    hit = cache.get(key)
    if hit is not None:
        return hit

    async def _fetch() -> V:
        value = await factory()
        cache.set(key, value)
        return value

    return await flight.do(key, _fetch)
