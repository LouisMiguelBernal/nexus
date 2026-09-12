"""Supervised background services.

``lifespan()`` used to fire eight ``asyncio.create_task`` calls and forget
the handles: a loop that raised outside its own try/except died silently for
the life of the process, and shutdown could not cancel anything. Here every
service is a task the supervisor retains, restarts with exponential backoff
if it crashes, cancels on shutdown, and reports on.

Two kinds of service:

- Interval services override ``run_once()``; the base ``run()`` loop calls it
  every ``interval_s`` and treats an exception there as an *error* (logged,
  counted, loop continues) rather than a crash.
- Long-running services override ``run()`` entirely (WebSocket pumps, pollers
  with their own cadence). If ``run()`` raises, that is a *crash*: the
  supervisor restarts it after a backoff. If ``run()`` returns, the service is
  *finished* and is not restarted.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

logger = logging.getLogger("nexus.supervisor")

State = Literal["idle", "running", "restarting", "stopped", "finished", "crashed"]


class Service:
    """Base class. Subclass and override ``run_once`` (interval) or ``run``."""

    def __init__(self, name: str, interval_s: float | None = None) -> None:
        self.name = name
        self.interval_s = interval_s
        self.errors = 0
        self.last_error: str | None = None
        self.last_error_at: float | None = None
        self.last_run_at: float | None = None
        self.runs = 0

    async def run_once(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} must implement run_once() or run()")

    async def run(self) -> None:
        """Default loop: ``run_once`` every ``interval_s`` (fixed rate, drift-corrected)."""
        if self.interval_s is None:
            raise ValueError(f"service {self.name}: interval_s required for the default run() loop")
        while True:
            started = time.monotonic()
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001  # reason: an interval tick that fails must not kill the loop; it is counted and logged
                self._record_error(exc)
                if self.errors == 1 or self.errors % 50 == 0:
                    logger.exception("service %s run_once failed (error #%d)", self.name, self.errors)
                else:
                    logger.warning("service %s run_once failed (error #%d): %s", self.name, self.errors, exc)
            self.runs += 1
            self.last_run_at = time.time()
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.0, self.interval_s - elapsed))

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass

    def _record_error(self, exc: BaseException) -> None:
        self.errors += 1
        self.last_error = f"{type(exc).__name__}: {exc}"[:500]
        self.last_error_at = time.time()


class FunctionService(Service):
    """Wrap an existing long-running coroutine function as a service.

    Transition aid: the five hand-rolled loops become supervised without
    being rewritten first.
    """

    def __init__(self, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        super().__init__(name)
        self._factory = factory

    async def run(self) -> None:
        await self._factory()


class _Entry:
    __slots__ = ("crash_count", "restarts", "service", "started_at", "state", "task")

    def __init__(self, service: Service) -> None:
        self.service = service
        self.state: State = "idle"
        self.task: asyncio.Task[None] | None = None
        self.started_at: float | None = None
        self.restarts = 0
        self.crash_count = 0


class Supervisor:
    def __init__(
        self,
        *,
        backoff_min_s: float = 1.0,
        backoff_max_s: float = 60.0,
        jitter: float = 0.2,
        max_restarts: int | None = None,
    ) -> None:
        self._entries: dict[str, _Entry] = {}
        self.backoff_min_s = backoff_min_s
        self.backoff_max_s = backoff_max_s
        self.jitter = jitter
        self.max_restarts = max_restarts
        self._started = False

    # -- registration --------------------------------------------------------

    def add(self, service: Service) -> Service:
        if service.name in self._entries:
            raise ValueError(f"service already registered: {service.name}")
        entry = _Entry(service)
        self._entries[service.name] = entry
        if self._started:
            self._launch(entry)
        return service

    def get(self, name: str) -> Service | None:
        entry = self._entries.get(name)
        return entry.service if entry else None

    # -- lifecycle -----------------------------------------------------------

    async def start_all(self) -> None:
        self._started = True
        for entry in self._entries.values():
            if entry.task is None:
                self._launch(entry)

    async def stop_all(self, timeout_s: float = 5.0) -> None:
        """Cancel every service and wait up to ``timeout_s`` for them to unwind."""
        self._started = False
        tasks = [e.task for e in self._entries.values() if e.task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=timeout_s)
            for task in pending:
                logger.warning("service task %s did not stop within %.1fs", task.get_name(), timeout_s)
        for entry in self._entries.values():
            if entry.state in ("running", "restarting", "idle"):
                entry.state = "stopped"
            entry.task = None

    def _launch(self, entry: _Entry) -> None:
        entry.task = asyncio.create_task(self._supervise(entry), name=f"svc:{entry.service.name}")

    async def _supervise(self, entry: _Entry) -> None:
        service = entry.service
        while True:
            entry.state = "running"
            entry.started_at = time.time()
            try:
                await service.on_start()
                await service.run()
            except asyncio.CancelledError:
                entry.state = "stopped"
                await self._safe_on_stop(service)
                raise
            except Exception as exc:  # noqa: BLE001  # reason: this is the supervisor; a crash is recorded and the service restarted
                entry.crash_count += 1
                service._record_error(exc)
                await self._safe_on_stop(service)
                if self.max_restarts is not None and entry.restarts >= self.max_restarts:
                    entry.state = "crashed"
                    logger.critical(
                        "service %s crashed %d times; giving up: %s", service.name, entry.crash_count, exc
                    )
                    return
                delay = self._backoff(entry.restarts)
                entry.state = "restarting"
                logger.exception(
                    "service %s crashed (#%d); restarting in %.1fs", service.name, entry.crash_count, delay
                )
                entry.restarts += 1
                await asyncio.sleep(delay)
                continue
            else:
                entry.state = "finished"
                await self._safe_on_stop(service)
                logger.info("service %s finished", service.name)
                return

    async def _safe_on_stop(self, service: Service) -> None:
        try:
            await service.on_stop()
        except Exception:  # noqa: BLE001  # reason: teardown hooks must not mask the primary outcome
            logger.exception("service %s on_stop failed", service.name)

    def _backoff(self, restarts: int) -> float:
        base = min(self.backoff_max_s, self.backoff_min_s * (2.0**restarts))
        return max(0.0, base * (1.0 + random.uniform(-self.jitter, self.jitter)))

    # -- introspection -------------------------------------------------------

    def status(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, entry in self._entries.items():
            svc = entry.service
            out[name] = {
                "state": entry.state,
                "started_at": entry.started_at,
                "restarts": entry.restarts,
                "crash_count": entry.crash_count,
                "errors": svc.errors,
                "runs": svc.runs,
                "interval_s": svc.interval_s,
                "last_run_at": svc.last_run_at,
                "last_error": svc.last_error,
                "last_error_at": svc.last_error_at,
            }
        return out

    def healthy(self) -> bool:
        return all(e.state not in ("crashed",) for e in self._entries.values())

    def crashed(self) -> list[str]:
        return [name for name, e in self._entries.items() if e.state == "crashed"]
