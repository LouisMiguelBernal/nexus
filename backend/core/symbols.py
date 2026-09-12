"""Per-symbol engine registry with eviction, plus per-field views.

``main.py`` keeps fourteen module-level dicts of per-symbol engines, creates a
full set for any symbol a route is asked about, and never removes any - every
symbol ever typed into the search box is polled forever. This registry owns
the bundle: pinned symbols (the default watchlist) live for the process;
anything else is evicted after ``idle_ttl_s`` without a touch, or when more
than ``max_extra`` extras exist (least recently used first).

Consumers that still expect the old per-engine dicts - ``oi_poll_loop`` and
``absorption_sample_loop`` are handed them and call ``.items()`` / ``.get()``
- get a :class:`RegistryView`, a read-only Mapping projecting one field of
every bundle. Without it, replacing the dicts turns those loops into
exceptions that their own ``except`` blocks swallow, and OI, funding and
absorption silently stop refreshing while every response keeps its keys.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any


def normalise(symbol: str) -> str:
    """``main.py:302`` does ``.strip().upper()`` and refuses a blank symbol.

    Keying on ``.upper()`` alone let ``"  btcusdt  "`` and ``""`` become
    distinct entries that then get their own engines and their own polling.
    """
    key = str(symbol).strip().upper()
    if not key:
        raise ValueError("symbol must not be blank")
    return key


class RegistryView[V](Mapping[str, V]):
    """Read-only projection of one field of every bundle.

    ``get`` never creates a bundle - ``api/matrix.py`` relies on dict ``.get``
    semantics, where a miss is a miss and does not spin up fourteen engines.
    """

    def __init__(self, registry: SymbolRegistry[Any], project: Callable[[Any], V], name: str = "") -> None:
        self._registry = registry
        self._project = project
        self._name = name

    def __getitem__(self, symbol: str) -> V:
        bundle = self._registry.peek(symbol)
        if bundle is None:
            raise KeyError(symbol)
        return self._project(bundle)

    def __contains__(self, symbol: object) -> bool:
        return isinstance(symbol, str) and self._registry.peek(symbol) is not None

    def __iter__(self) -> Iterator[str]:
        return iter(self._registry.active())

    def __len__(self) -> int:
        return len(self._registry)

    def get(self, symbol: str, default: Any = None) -> Any:
        bundle = self._registry.peek(symbol)
        return default if bundle is None else self._project(bundle)

    def __repr__(self) -> str:
        return f"<RegistryView {self._name or '?'} n={len(self)}>"


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
        self._pinned = {normalise(s) for s in pinned}
        self._max_extra = int(max_extra)
        self._idle_ttl_s = float(idle_ttl_s)
        self._clock = clock
        self._items: dict[str, T] = {}
        self._last_touch: dict[str, float] = {}
        self.evictions = 0

    # -- access --------------------------------------------------------------

    def get(self, symbol: str) -> T:
        """Return the bundle for ``symbol``, creating it on first use."""
        key = normalise(symbol)
        if key not in self._items:
            self._items[key] = self._factory(key)
        self._last_touch[key] = self._clock()
        self._evict_over_capacity()
        return self._items[key]

    def __getitem__(self, symbol: str) -> T:
        """Subscript creates, like ``get`` - the dicts it replaces were written
        to with ``engines[sym] = ...`` and read with ``engines[sym]``."""
        return self.get(symbol)

    def peek(self, symbol: str) -> T | None:
        """Return the bundle without creating or touching it."""
        try:
            return self._items.get(normalise(symbol))
        except ValueError:
            return None

    def touch(self, symbol: str) -> None:
        key = normalise(symbol)
        if key in self._items:
            self._last_touch[key] = self._clock()

    def __contains__(self, symbol: object) -> bool:
        return isinstance(symbol, str) and self.peek(symbol) is not None

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

    def view[V](self, project: Callable[[T], V], name: str = "") -> RegistryView[V]:
        """A Mapping over one field of each bundle, for consumers that still
        expect the old per-engine dicts."""
        return RegistryView(self, project, name)

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
