"""KlineBuffer: upsert by open_time, ordering, bounded size, resampling."""

import pytest

from backend.data.klines import KlineBuffer


def _bar(
    open_time_ms: int,
    close: float,
    *,
    o: float | None = None,
    h: float | None = None,
    low: float | None = None,
):
    return {
        "open_time": open_time_ms,
        "open": o if o is not None else close,
        "high": h if h is not None else close,
        "low": low if low is not None else close,
        "close": close,
        "volume": 1.0,
        "quote_volume": close,
        "trades": 1,
        "close_time": open_time_ms + 900_000 - 1,
        "is_closed": True,
    }


M15 = 900_000


def test_refetched_bars_replace_instead_of_duplicating():
    buf = KlineBuffer(maxlen=100, interval="15m")
    bars = [_bar(i * M15, 100 + i) for i in range(10)]
    assert buf.extend(bars) == 10
    # A backfill after a WS gap re-delivers the same 10 bars.
    assert buf.extend(bars) == 0
    assert len(buf) == 10
    # A corrected bar for an existing open_time replaces the old one.
    buf.append(_bar(3 * M15, 999.0))
    assert len(buf) == 10
    assert buf[3]["close"] == 999.0


def test_iteration_is_sorted_regardless_of_insert_order():
    buf = KlineBuffer(maxlen=100, interval="15m")
    for i in (5, 1, 4, 2, 3, 0):
        buf.append(_bar(i * M15, float(i)))
    assert [c["open_time"] for c in buf] == [i * M15 for i in range(6)]
    assert [c["open_time"] for c in list(buf)[-2:]] == [4 * M15, 5 * M15]
    assert buf.last() is not None and buf.last()["close"] == 5.0
    assert buf.closes(3) == [3.0, 4.0, 5.0]


def test_maxlen_drops_oldest():
    buf = KlineBuffer(maxlen=5, interval="15m")
    buf.extend(_bar(i * M15, float(i)) for i in range(8))
    assert len(buf) == 5
    assert buf[0]["open_time"] == 3 * M15


def test_resample_15m_to_1h_aggregates_ohlcv_and_drops_partial_groups():
    buf = KlineBuffer(maxlen=100, interval="15m")
    # Two complete hours (8 bars) plus a partial third hour (2 bars).
    prices = [10, 12, 9, 11, 11, 15, 13, 14, 14, 16]
    for i, p in enumerate(prices):
        buf.append(_bar(i * M15, float(p), o=float(p) - 0.5, h=float(p) + 1, low=float(p) - 1))
    hourly = buf.resample("1h")
    assert len(hourly) == 2, "partial trailing hour must be dropped"
    first = hourly[0]
    assert first["open_time"] == 0
    assert first["open"] == 9.5  # first bar's open
    assert first["high"] == 13.0  # max high over 10,12,9,11 (+1)
    assert first["low"] == 8.0  # min low over the group (-1)
    assert first["close"] == 11.0  # last bar's close
    assert first["volume"] == 4.0
    assert first["trades"] == 4
    assert first["close_time"] == 3_600_000 - 1
    assert hourly[1]["close"] == 14.0


def test_resample_skips_groups_with_gaps():
    buf = KlineBuffer(maxlen=100, interval="15m")
    for i in range(8):
        if i == 2:
            continue  # gap inside hour 0
        buf.append(_bar(i * M15, float(i)))
    hourly = buf.resample("1h")
    assert [h["open_time"] for h in hourly] == [3_600_000]


def test_resample_rejects_finer_or_unaligned_targets():
    buf = KlineBuffer(maxlen=10, interval="15m")
    with pytest.raises(ValueError):
        buf.resample("5m")
    with pytest.raises(ValueError):
        KlineBuffer(maxlen=10, interval="1h").resample("90m")


def test_list_conversion_matches_legacy_deque_usage():
    """Consumers do `list(binance_data.kline_history.get(sym, []))`; keep that shape."""
    buf = KlineBuffer(maxlen=10, interval="15m")
    buf.append(_bar(0, 1.0))
    hist = list(buf)
    assert isinstance(hist, list) and hist[-1]["close"] == 1.0
    assert hist[-96:] == hist
