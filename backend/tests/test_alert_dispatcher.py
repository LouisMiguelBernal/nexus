"""alerts.dispatcher - dedupe, cooldown, and what gets stored."""

import pytest

from backend.alerts.dispatcher import AlertDispatcher, cooldown_for, dedupe_key
from backend.data.store import Store


class FakeClock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeTelegram:
    def __init__(self, configured: bool = True, fail: bool = False) -> None:
        self.configured = configured
        self.fail = fail
        self.sent: list[tuple[str, dict]] = []

    async def send_alert(self, alert_type: str, data: dict) -> bool:
        if self.fail:
            raise RuntimeError("telegram unreachable")
        self.sent.append((alert_type, data))
        return True


@pytest.fixture
async def setup(tmp_path):
    store = Store(tmp_path / "alerts.db")
    await store.connect()
    await store.migrate()
    clock = FakeClock()
    telegram = FakeTelegram()
    yield AlertDispatcher(store, telegram, clock=clock), store, telegram, clock
    await store.close()


def zone_alert(price: float = 80_000.0, symbol: str = "BTCUSDT") -> dict:
    return {
        "type": "zone_approach",
        "symbol": symbol,
        "message": f"{symbol} approaching golden zone",
        "tier": "golden",
        "zone_price": price,
    }


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------


def test_same_zone_shares_a_key_and_a_different_one_does_not():
    a = dedupe_key("zone_approach", zone_alert(80_000.0))
    b = dedupe_key("zone_approach", zone_alert(80_010.0))  # within 0.1% -> same bucket
    c = dedupe_key("zone_approach", zone_alert(76_000.0))  # a different level
    d = dedupe_key("zone_approach", zone_alert(80_000.0, symbol="ETHUSDT"))
    assert a == b
    assert a != c and a != d


def test_bucket_policies_differ_by_type():
    assert dedupe_key("squeeze_alert", {"symbol": "BTCUSDT", "direction": "long"}) != dedupe_key(
        "squeeze_alert", {"symbol": "BTCUSDT", "direction": "short"}
    )
    assert dedupe_key("circuit_breaker", {"trip_kind": "ws_outage", "action": "tripped"}) != dedupe_key(
        "circuit_breaker", {"trip_kind": "ws_outage", "action": "cleared"}
    )
    # "none" collapses to the symbol
    assert dedupe_key("leverage_warning", {"symbol": "BTCUSDT", "leverage": 9}) == dedupe_key(
        "leverage_warning", {"symbol": "BTCUSDT", "leverage": 11}
    )


def test_registry_supplies_cooldowns():
    assert cooldown_for("zone_approach") == 1800
    assert cooldown_for("morning_brief") == 0
    assert cooldown_for("never_heard_of_it") == 900  # DEFAULT_COOLDOWN_S


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


async def test_repeat_inside_cooldown_is_neither_sent_nor_stored(setup):
    """The zone loop re-emits every 60s; only the first one is an event."""
    dispatcher, store, telegram, clock = setup

    first = await dispatcher.dispatch(zone_alert())
    assert first.sent and first.reason == "sent"

    # 29 x 60s = 1740s, just inside the 1800s cooldown.
    for tick in range(29):
        clock.advance(60)
        result = await dispatcher.dispatch(zone_alert())
        assert result.sent is False and result.reason == "cooldown", f"tick {tick}"

    assert len(telegram.sent) == 1
    assert await store.fetch_value("SELECT COUNT(*) FROM alerts") == 1
    assert dispatcher.stats() == {"sent": 1, "suppressed": 29, "unknown_type": 0}

    clock.advance(60)  # exactly at the boundary - the window has elapsed
    assert (await dispatcher.dispatch(zone_alert())).sent


async def test_alert_fires_again_once_the_cooldown_expires(setup):
    dispatcher, store, telegram, clock = setup
    await dispatcher.dispatch(zone_alert())
    clock.advance(cooldown_for("zone_approach") + 1)
    again = await dispatcher.dispatch(zone_alert())
    assert again.sent
    assert len(telegram.sent) == 2
    assert await store.fetch_value("SELECT send_count FROM alert_state") == 2


async def test_a_different_zone_is_not_suppressed(setup):
    dispatcher, _store, telegram, _clock = setup
    await dispatcher.dispatch(zone_alert(80_000.0))
    other = await dispatcher.dispatch(zone_alert(76_000.0))
    assert other.sent, "a different level is a different alert"
    assert len(telegram.sent) == 2


async def test_zero_cooldown_type_always_sends(setup):
    dispatcher, _store, telegram, _clock = setup
    for _ in range(3):
        result = await dispatcher.dispatch({"type": "morning_brief", "message": "brief", "brief": "..."})
        assert result.sent
    assert len(telegram.sent) == 3


async def test_alert_is_stored_even_when_telegram_fails(setup, tmp_path):
    """Delivery and the record are independent: an outage must not lose history."""
    dispatcher, store, _telegram, _clock = setup
    dispatcher.telegram = FakeTelegram(fail=True)

    result = await dispatcher.dispatch(zone_alert())
    assert result.sent is False and result.reason == "telegram_failed"
    row = await store.fetch_one("SELECT * FROM alerts ORDER BY id DESC LIMIT 1")
    assert row is not None and row["alert_type"] == "zone_approach" and row["sent_telegram"] == 0


async def test_telegram_outage_does_not_cause_a_burst_on_recovery(setup):
    """The cooldown starts when the alert is accepted, not when it is delivered."""
    dispatcher, _store, _telegram, clock = setup
    dispatcher.telegram = FakeTelegram(fail=True)
    await dispatcher.dispatch(zone_alert())

    working = FakeTelegram()
    dispatcher.telegram = working
    clock.advance(120)
    result = await dispatcher.dispatch(zone_alert())
    assert result.reason == "cooldown"
    assert working.sent == []


async def test_unconfigured_telegram_still_records(setup):
    dispatcher, store, _telegram, _clock = setup
    dispatcher.telegram = FakeTelegram(configured=False)
    result = await dispatcher.dispatch(zone_alert())
    assert result.sent is False and result.reason == "telegram_disabled"
    assert await store.fetch_value("SELECT COUNT(*) FROM alerts") == 1


async def test_unknown_type_is_delivered_but_counted(setup, caplog):
    dispatcher, store, telegram, _clock = setup
    result = await dispatcher.dispatch({"type": "zone_aproach", "symbol": "BTCUSDT", "message": "typo"})
    assert result.sent, "an unregistered type must not be silently dropped"
    assert dispatcher.stats()["unknown_type"] == 1
    assert any("not in the registry" in r.getMessage() for r in caplog.records)
    assert await store.fetch_value("SELECT COUNT(*) FROM alerts") == 1


async def test_recent_and_prune(setup):
    dispatcher, store, _telegram, clock = setup
    await dispatcher.dispatch(zone_alert(80_000.0))
    await dispatcher.dispatch(zone_alert(70_000.0))
    assert len(await dispatcher.recent()) == 2
    assert len(await dispatcher.recent(alert_type="zone_approach")) == 2
    assert len(await dispatcher.recent(alert_type="morning_brief")) == 0

    clock.advance(8 * 24 * 3600)
    assert await dispatcher.prune_state() == 2
    assert await store.fetch_value("SELECT COUNT(*) FROM alert_state") == 0
    assert await store.fetch_value("SELECT COUNT(*) FROM alerts") == 2, "history is kept"
