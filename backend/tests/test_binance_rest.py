"""data.binance_rest - the request path must honour the rate guard.

Observed live: Binance answered 418 on /fapi/v1/ping while /api/klines,
/api/ticker, /api/symbols/search and /api/indicators all returned 502. The
guard that exists to parse that ban and back off was never consulted by the
request path, so every chart request kept calling a host that was banning it.
"""

import time

import pytest

from backend.data import binance_rest
from backend.data.http import HttpStatusError
from backend.ingestion import rate_guard


@pytest.fixture(autouse=True)
def clean_guard():
    rate_guard.reset()
    yield
    rate_guard.reset()


def test_successful_call_returns_data_and_clears_the_guard(monkeypatch):
    calls: list[str] = []

    def fake(url: str, **kwargs: object) -> list[int]:
        calls.append(url)
        return [1, 2, 3]

    monkeypatch.setattr(binance_rest, "fetch_json", fake)
    assert binance_rest.futures_get("/fapi/v1/klines?symbol=BTCUSDT") == [1, 2, 3]
    assert calls == ["https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT"]
    assert rate_guard.should_skip(rate_guard.BINANCE_FUTURES_HOST) is False


def test_a_418_ban_is_recorded_and_the_next_call_does_not_hit_the_venue(monkeypatch):
    """The whole point: one ban response must stop the next request, or the
    app extends its own ban."""
    deadline_ms = int((time.time() + 120) * 1000)
    attempts: list[str] = []

    def banned(url: str, **kwargs: object) -> object:
        attempts.append(url)
        raise HttpStatusError(418, f'{{"code":-1003,"msg":"banned until {deadline_ms}"}}', url)

    monkeypatch.setattr(binance_rest, "fetch_json", banned)
    assert binance_rest.futures_get("/fapi/v1/klines") is None
    assert len(attempts) == 1

    assert rate_guard.should_skip(rate_guard.BINANCE_FUTURES_HOST) is True
    assert rate_guard.cooldown_remaining(rate_guard.BINANCE_FUTURES_HOST) > 60

    # Second call must be refused locally, without touching the venue.
    assert binance_rest.futures_get("/fapi/v1/ticker/24hr") is None
    assert len(attempts) == 1, "a banned host must not be called again"


def test_a_plain_http_error_does_not_trip_the_cooldown(monkeypatch):
    def not_found(url: str, **kwargs: object) -> object:
        raise HttpStatusError(404, "no such symbol", url)

    monkeypatch.setattr(binance_rest, "fetch_json", not_found)
    assert binance_rest.futures_get("/fapi/v1/klines?symbol=NOPE") is None
    assert rate_guard.should_skip(rate_guard.BINANCE_FUTURES_HOST) is False, "404 is not a rate limit"


def test_transport_failure_returns_none_without_raising(monkeypatch):
    def boom(url: str, **kwargs: object) -> object:
        raise OSError("connection reset")

    monkeypatch.setattr(binance_rest, "fetch_json", boom)
    assert binance_rest.futures_get("/fapi/v1/klines") is None
    assert rate_guard.should_skip(rate_guard.BINANCE_FUTURES_HOST) is False


def test_spot_and_futures_cooldowns_are_independent(monkeypatch):
    deadline_ms = int((time.time() + 120) * 1000)

    def banned(url: str, **kwargs: object) -> object:
        raise HttpStatusError(429, f"banned until {deadline_ms}", url)

    monkeypatch.setattr(binance_rest, "fetch_json", banned)
    assert binance_rest.futures_get("/fapi/v1/klines") is None
    assert rate_guard.should_skip(rate_guard.BINANCE_FUTURES_HOST) is True
    assert rate_guard.should_skip(rate_guard.BINANCE_SPOT_HOST) is False, "spot is a separate host budget"


async def test_afetch_runs_off_the_event_loop(monkeypatch):
    import threading

    loop_thread = threading.get_ident()
    seen: list[int] = []

    def fake(url: str, **kwargs: object) -> dict:
        seen.append(threading.get_ident())
        return {"ok": True}

    monkeypatch.setattr(binance_rest, "fetch_json", fake)
    assert await binance_rest.afetch("/fapi/v1/ping") == {"ok": True}
    assert seen and seen[0] != loop_thread, "blocking fetch must not run on the event loop"


def test_stats_expose_the_cooldown(monkeypatch):
    def fake(url: str, **kwargs: object) -> dict:
        return {}

    monkeypatch.setattr(binance_rest, "fetch_json", fake)
    binance_rest.futures_get("/fapi/v1/ping")
    stats = binance_rest.stats()
    assert stats["ok"] >= 1 and stats["futures_cooldown_s"] == 0.0
    assert "skipped_by_rate_guard" in stats
