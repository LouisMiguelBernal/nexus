"""core.clock, core.symbols, core.cache, core.events."""

import asyncio
import time

import pytest

from backend.core.cache import SingleFlight, TTLCache, cached
from backend.core.clock import Clock, LiveClock, SimClock
from backend.core.events import Alert, Fill, Topic, Trade, to_dict
from backend.core.symbols import SymbolRegistry

# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------


async def test_sim_clock_advances_without_waiting():
    clock = SimClock(start=1_000.0)
    assert isinstance(clock, Clock)
    started = time.perf_counter()
    await clock.sleep(3600)
    assert time.perf_counter() - started < 0.05
    assert clock.now() == 4_600.0 and clock.now_ms() == 4_600_000
    clock.advance(0.5)
    assert clock.now() == 4_600.5
    with pytest.raises(ValueError):
        clock.set(1.0)


async def test_live_clock_is_wall_time():
    clock = LiveClock()
    assert isinstance(clock, Clock)
    assert abs(clock.now() - time.time()) < 1.0


# ---------------------------------------------------------------------------
# symbols
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_symbol_registry_pins_defaults_and_evicts_extras_lru():
    clock = _FakeClock()
    built: list[str] = []
    reg: SymbolRegistry[dict] = SymbolRegistry(
        lambda s: (built.append(s), {"sym": s})[1],
        pinned=["BTCUSDT"],
        max_extra=2,
        idle_ttl_s=100,
        clock=clock,
    )
    reg.get("btcusdt")
    reg.get("AAAUSDT")
    clock.t = 1
    reg.get("BBBUSDT")
    clock.t = 2
    reg.get("CCCUSDT")  # third extra -> least recently used extra (AAA) evicted
    assert set(reg.active()) == {"BTCUSDT", "BBBUSDT", "CCCUSDT"}
    assert reg.evictions == 1
    clock.t = 200
    assert reg.evict_idle() == ["BBBUSDT", "CCCUSDT"]
    assert reg.active() == ["BTCUSDT"], "pinned symbols are never evicted"
    reg.get("BBBUSDT")
    assert built.count("BBBUSDT") == 2, "evicted symbols are rebuilt on demand"
    assert "btcusdt" in reg and reg.peek("ZZZ") is None and len(reg) == 2


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


def test_ttl_cache_expires_and_bounds():
    clock = _FakeClock()
    cache: TTLCache[str, int] = TTLCache(ttl_s=10, maxsize=2, clock=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)  # evicts least recently used: "b"
    assert cache.get("b") is None and cache.get("c") == 3
    clock.t = 11
    assert cache.get("a") is None, "expired"
    assert cache.stats()["misses"] == 2


async def test_single_flight_shares_one_execution():
    flight: SingleFlight[str, int] = SingleFlight()
    calls = 0

    async def slow() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return 42

    results = await asyncio.gather(*(flight.do("k", slow) for _ in range(5)))
    assert results == [42] * 5 and calls == 1 and flight.inflight() == 0


async def test_cached_helper_uses_cache_then_flight():
    clock = _FakeClock()
    cache: TTLCache[str, int] = TTLCache(ttl_s=10, clock=clock)
    flight: SingleFlight[str, int] = SingleFlight()
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        return 7

    assert await cached(cache, flight, "k", factory) == 7
    assert await cached(cache, flight, "k", factory) == 7
    assert calls == 1
    clock.t = 11
    assert await cached(cache, flight, "k", factory) == 7
    assert calls == 2


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def test_events_are_frozen_and_serialisable():
    trade = Trade(symbol="BTCUSDT", price=1.0, qty=2.0, side="buy", ts=3.0)
    with pytest.raises(AttributeError):
        trade.price = 5.0  # type: ignore[misc]
    assert to_dict(trade)["venue"] == "binance"
    fill = Fill("f1", "nx1", "BTCUSDT", "sell", 1.0, 1.0, 0.01, "USDT", "taker", 0.0)
    assert to_dict(fill)["liquidity"] == "taker"
    alert = Alert(kind="zone", symbol="BTCUSDT", message="m", ts=0.0)
    assert alert.payload == {}
    assert Topic.VPIN_UPDATE == "vpin.update"
