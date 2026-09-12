"""core.bus - bounded, non-blocking pub/sub."""

import asyncio
import time

from backend.core.bus import EventBus


async def test_delivery_and_wildcards():
    bus = EventBus()
    got: list[tuple[str, object]] = []

    async def handler(topic: str, payload: object) -> None:
        got.append((topic, payload))

    bus.subscribe("a.*", handler)
    await bus.start()
    assert bus.publish("a.b", {"x": 1}) == 1
    assert bus.publish("zzz", {}) == 0
    await bus.drain()
    assert got == [("a.b", {"x": 1})]
    assert bus.recent(1)[0]["topic"] == "zzz"
    await bus.stop()


async def test_slow_subscriber_drops_oldest_and_never_blocks_the_publisher():
    bus = EventBus(default_maxsize=4)
    gate = asyncio.Event()
    seen: list[object] = []

    async def slow(topic: str, payload: object) -> None:
        await gate.wait()
        seen.append(payload)

    sub = bus.subscribe("t", slow)
    await bus.start()

    started = time.perf_counter()
    for i in range(20):
        bus.publish("t", i)
    assert time.perf_counter() - started < 0.05, "publish must not wait on the consumer"
    # 20 publishes without yielding: queue holds the 4 newest, 16 dropped.
    assert sub.dropped == 16
    assert sub.queue.qsize() == 4

    gate.set()
    await bus.drain()
    assert seen == [16, 17, 18, 19]
    assert sub.delivered == 4
    await bus.stop()


async def test_coalesce_keeps_only_the_newest_pending_payload():
    bus = EventBus()
    seen: list[object] = []

    async def handler(topic: str, payload: object) -> None:
        seen.append(payload)

    sub = bus.subscribe("snap", handler, policy="coalesce")
    await bus.start()
    for i in range(5):
        bus.publish("snap", i)
    await bus.drain()
    assert seen == [4]
    assert sub.dropped == 4
    await bus.stop()


async def test_handler_exception_is_isolated_and_counted():
    bus = EventBus()
    seen: list[object] = []

    async def flaky(topic: str, payload: object) -> None:
        if payload == "bad":
            raise RuntimeError("boom")
        seen.append(payload)

    sub = bus.subscribe("t", flaky)
    await bus.start()
    bus.publish("t", "bad")
    bus.publish("t", "good")
    await bus.drain()
    assert seen == ["good"]
    assert sub.errors == 1 and sub.delivered == 1 and sub.alive
    await bus.stop()


async def test_publish_before_start_is_queued_then_delivered():
    bus = EventBus()
    seen: list[object] = []

    async def handler(topic: str, payload: object) -> None:
        seen.append(payload)

    bus.subscribe("t", handler)
    bus.publish("t", 1)
    await bus.start()
    await bus.drain()
    assert seen == [1]
    await bus.stop()


async def test_stats_and_unsubscribe():
    bus = EventBus()

    async def handler(topic: str, payload: object) -> None:
        pass

    sub = bus.subscribe("t", handler, name="probe")
    await bus.start()
    bus.publish("t", 1)
    await bus.drain()
    stats = bus.stats()
    assert stats["published"] == 1 and stats["dropped_total"] == 0
    assert stats["subscriptions"][0]["name"] == "probe"
    bus.unsubscribe(sub)
    assert bus.publish("t", 2) == 0
    await bus.stop()


async def test_publishing_to_a_topic_with_no_subscriber_is_reported():
    """Moving producers into services one commit at a time makes it easy to
    leave a topic unwired; publish() returning 0 is otherwise silent."""
    import logging

    bus = EventBus()
    await bus.start()
    logger = logging.getLogger("nexus.bus")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    try:
        assert bus.publish("alert", {"a": 1}) == 0
        assert bus.publish("alert", {"a": 2}) == 0
        assert bus.publish("other", {}) == 0
    finally:
        logger.removeHandler(handler)

    assert bus.stats()["unconsumed_topics"] == {"alert": 2, "other": 1}
    warned = [r for r in records if r.levelno == logging.WARNING and "no subscriber" in r.getMessage()]
    assert len(warned) == 2, "warn once per topic, not once per event"
    await bus.stop()


async def test_a_subscribed_topic_is_never_reported_unconsumed():
    bus = EventBus()

    async def handler(topic: str, payload: object) -> None:
        pass

    bus.subscribe("market.*", handler)
    await bus.start()
    assert bus.publish("market.trade", {}) == 1
    await bus.drain()
    assert bus.stats()["unconsumed_topics"] == {}
    await bus.stop()
