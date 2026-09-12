"""core.supervisor - services are retained, restarted, cancelled and reported."""

import asyncio

from backend.core.supervisor import FunctionService, Service, Supervisor


class Ticker(Service):
    def __init__(self) -> None:
        super().__init__("ticker", interval_s=0.01)
        self.n = 0

    async def run_once(self) -> None:
        self.n += 1


class Flaky(Service):
    def __init__(self) -> None:
        super().__init__("flaky", interval_s=0.005)
        self.n = 0

    async def run_once(self) -> None:
        self.n += 1
        if self.n % 2 == 0:
            raise RuntimeError("tick failed")


class Crasher(Service):
    def __init__(self) -> None:
        super().__init__("crasher")
        self.starts = 0

    async def run(self) -> None:
        self.starts += 1
        raise RuntimeError("boom")


class Finisher(Service):
    def __init__(self) -> None:
        super().__init__("finisher")

    async def run(self) -> None:
        return None


async def test_interval_service_runs_and_stops():
    sup = Supervisor()
    ticker = Ticker()
    sup.add(ticker)
    await sup.start_all()
    await asyncio.sleep(0.1)
    assert ticker.n >= 3
    await sup.stop_all()
    n = ticker.n
    await asyncio.sleep(0.05)
    assert ticker.n == n, "stopped service must not keep running"
    assert sup.status()["ticker"]["state"] == "stopped"


async def test_run_once_failure_is_counted_not_fatal():
    sup = Supervisor()
    flaky = Flaky()
    sup.add(flaky)
    await sup.start_all()
    await asyncio.sleep(0.1)
    await sup.stop_all()
    st = sup.status()["flaky"]
    assert flaky.n >= 6
    assert st["errors"] >= 2 and st["crash_count"] == 0 and st["restarts"] == 0
    assert "tick failed" in (st["last_error"] or "")


async def test_crashing_service_is_restarted_with_backoff():
    sup = Supervisor(backoff_min_s=0.01, backoff_max_s=0.02, jitter=0.0)
    crasher = Crasher()
    sup.add(crasher)
    await sup.start_all()
    await asyncio.sleep(0.15)
    await sup.stop_all()
    st = sup.status()["crasher"]
    assert crasher.starts >= 3
    assert st["crash_count"] >= 3 and st["restarts"] >= 2
    assert "boom" in (st["last_error"] or "")


async def test_max_restarts_marks_service_crashed():
    sup = Supervisor(backoff_min_s=0.001, backoff_max_s=0.002, jitter=0.0, max_restarts=2)
    crasher = Crasher()
    sup.add(crasher)
    await sup.start_all()
    await asyncio.sleep(0.1)
    assert sup.status()["crasher"]["state"] == "crashed"
    assert not sup.healthy() and sup.crashed() == ["crasher"]
    assert crasher.starts == 3  # initial + 2 restarts
    await sup.stop_all()


async def test_finished_service_is_not_restarted():
    sup = Supervisor()
    sup.add(Finisher())
    await sup.start_all()
    await asyncio.sleep(0.02)
    assert sup.status()["finisher"]["state"] == "finished"
    assert sup.healthy()
    await sup.stop_all()


async def test_stop_all_cancels_a_hung_service():
    sup = Supervisor()
    stuck = asyncio.Event()
    stopped: list[str] = []

    class Hung(Service):
        async def run(self) -> None:
            await stuck.wait()

        async def on_stop(self) -> None:
            stopped.append("yes")

    sup.add(Hung("hung"))
    await sup.start_all()
    await asyncio.sleep(0.01)
    await sup.stop_all(timeout_s=0.2)
    assert sup.status()["hung"]["state"] == "stopped"
    assert stopped == ["yes"]


async def test_function_service_wraps_a_legacy_loop():
    calls: list[int] = []

    async def legacy_loop() -> None:
        while True:
            calls.append(1)
            await asyncio.sleep(0.005)

    sup = Supervisor()
    sup.add(FunctionService("legacy", legacy_loop))
    await sup.start_all()
    await asyncio.sleep(0.05)
    await sup.stop_all()
    assert len(calls) >= 3
    assert sup.status()["legacy"]["state"] == "stopped"


async def test_duplicate_name_rejected():
    sup = Supervisor()
    sup.add(Ticker())
    try:
        sup.add(Ticker())
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate service name must be rejected")
