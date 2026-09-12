"""Closed-candle buffer keyed by open_time.

Replaces the ``deque(maxlen=200)`` that held kline history. That deque
de-duplicated only against its last element, so the REST backfill after a
WebSocket gap appended up to 100 bars that were already present - one gap
could fill half the regime / correlation / VaR window with duplicates.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, overload

Candle = dict[str, Any]

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


class KlineBuffer:
    """Ordered, de-duplicated store of closed candles for one symbol at one interval.

    - :meth:`append` upserts by ``open_time``: a re-fetched bar replaces its
      earlier copy, it never duplicates it.
    - Iteration and indexing see candles sorted by ``open_time``.
    - Bounded to the newest ``maxlen`` bars.
    - :meth:`resample` aggregates base-interval bars into a higher interval and
      drops incomplete groups, so a consumer that assumes hourly bars gets
      hourly bars.
    """

    def __init__(self, maxlen: int = 1000, interval: str = "15m") -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self.maxlen = int(maxlen)
        self.interval = interval
        self._by_time: dict[int, Candle] = {}
        self._sorted: list[Candle] | None = None

    # -- mutation ------------------------------------------------------------

    def append(self, candle: Candle) -> bool:
        """Insert or replace by ``open_time``. Returns True when the bar was new."""
        open_time = candle.get("open_time")
        if open_time is None:
            return False
        key = int(open_time)
        is_new = key not in self._by_time
        self._by_time[key] = candle
        self._sorted = None
        overflow = len(self._by_time) - self.maxlen
        if overflow > 0:
            for old in sorted(self._by_time)[:overflow]:
                del self._by_time[old]
        return is_new

    def extend(self, candles: Iterable[Candle]) -> int:
        """Upsert many. Returns how many were new."""
        return sum(1 for c in candles if self.append(c))

    def clear(self) -> None:
        self._by_time.clear()
        self._sorted = None

    # -- read ----------------------------------------------------------------

    def _ordered(self) -> list[Candle]:
        if self._sorted is None:
            self._sorted = [self._by_time[k] for k in sorted(self._by_time)]
        return self._sorted

    def __len__(self) -> int:
        return len(self._by_time)

    def __bool__(self) -> bool:
        return bool(self._by_time)

    def __iter__(self) -> Iterator[Candle]:
        return iter(self._ordered())

    @overload
    def __getitem__(self, idx: int) -> Candle: ...

    @overload
    def __getitem__(self, idx: slice) -> list[Candle]: ...

    def __getitem__(self, idx: int | slice) -> Candle | list[Candle]:
        return self._ordered()[idx]

    def last(self) -> Candle | None:
        ordered = self._ordered()
        return ordered[-1] if ordered else None

    def closes(self, n: int | None = None) -> list[float]:
        ordered = self._ordered() if n is None else self._ordered()[-n:]
        return [float(c["close"]) for c in ordered if c.get("close") is not None]

    def resample(self, interval: str) -> list[Candle]:
        """Aggregate to a coarser interval. Incomplete groups (gaps, the open
        trailing hour) are dropped rather than emitted as partial bars."""
        target = INTERVAL_MS.get(interval)
        base = INTERVAL_MS.get(self.interval)
        if target is None or base is None:
            raise ValueError(f"unknown interval: {self.interval!r} -> {interval!r}")
        if target == base:
            return list(self._ordered())
        if target < base or target % base:
            raise ValueError(f"cannot resample {self.interval} bars to {interval}")
        per_group = target // base

        groups: dict[int, list[Candle]] = {}
        for c in self._ordered():
            start = int(c["open_time"]) // target * target
            groups.setdefault(start, []).append(c)

        out: list[Candle] = []
        for start in sorted(groups):
            bars = groups[start]
            if len(bars) != per_group:
                continue
            out.append(
                {
                    "open_time": start,
                    "open": float(bars[0]["open"]),
                    "high": max(float(b["high"]) for b in bars),
                    "low": min(float(b["low"]) for b in bars),
                    "close": float(bars[-1]["close"]),
                    "volume": sum(float(b.get("volume") or 0.0) for b in bars),
                    "quote_volume": sum(float(b.get("quote_volume") or 0.0) for b in bars),
                    "trades": sum(int(b.get("trades") or 0) for b in bars),
                    "close_time": start + target - 1,
                    "is_closed": True,
                }
            )
        return out
