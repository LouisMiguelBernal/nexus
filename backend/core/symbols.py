"""Per-symbol engine registry with eviction.

``main.py`` keeps fourteen module-level dicts of per-symbol engines, creates a
full set for any symbol a route is asked about, and never removes any -
every symbol ever typed into the search box is polled forever. This registry
owns the bundle: pinned symbols (the default watchlist) live for the process;
anything else is evicted after ``idle_ttl_s`` without a touch, or when more
than ``max_extra`` extras exist (least recently used first).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator


class SymbolRegistry[T]:
    def __init__(
        self,
        factory: Callable[[str], T],
        *,
        pinned: Iterable[str] = (),
        max_extra: int = 12,
        idle_ttl_s: float = 1800.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._factory = factory
        self._pinned = {s.upper() for s in pinned}
        self._max_extra = int(max_extra)
        self._idle_ttl_s = float(idle_ttl_s)
        self._clock = clock
        self._items: dict[str, T] = {}
        self._last_touch: dict[str, float] = {}
        self.evictions = 0

    # -- access --------------------------------------------------------------

    def get(self, symbol: str) -> T:
        """Return the bundle for ``symbol``, creating it on first use."""
        key = symbol.upper()
        if key not in self._items:
            self._items[key] = self._factory(key)
        self._last_touch[key] = self._clock()
        self._evict_over_capacity()
        return self._items[key]

    def peek(self, symbol: str) -> T | None:
        """Return the bundle without creating or touching it."""
        return self._items.get(symbol.upper())

    def touch(self, symbol: str) -> None:
        key = symbol.upper()
        if key in self._items:
            self._last_touch[key] = self._clock()

    def __contains__(self, symbol: object) -> bool:
        return isinstance(symbol, str) and symbol.upper() in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._items))

    def active(self) -> list[str]:
        return list(self._items)

    def pinned(self) -> set[str]:
        return set(self._pinned)

    def items(self) -> list[tuple[str, T]]:
        return list(self._items.items())

    # -- eviction ------------------------------------------------------------

    def evict_idle(self) -> list[str]:
        """Drop unpinned symbols not touched within ``idle_ttl_s``. Returns them."""
        now = self._clock()
        gone = [
            s
            for s in self._items
            if s not in self._pinned and now - self._last_touch.get(s, now) > self._idle_ttl_s
        ]
        for s in gone:
            self._drop(s)
        return gone

    def _evict_over_capacity(self) -> None:
        extras = [s for s in self._items if s not in self._pinned]
        overflow = len(extras) - self._max_extra
        if overflow <= 0:
            return
        extras.sort(key=lambda s: self._last_touch.get(s, 0.0))
        for s in extras[:overflow]:
            self._drop(s)

    def _drop(self, symbol: str) -> None:
        self._items.pop(symbol, None)
        self._last_touch.pop(symbol, None)
        self.evictions += 1
