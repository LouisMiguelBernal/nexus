"""Drawdown + event circuit breaker.

Two trigger classes:

1. **Threshold triggers**: daily / weekly loss, drawdown from peak. Driven by
   :meth:`CircuitBreaker.update` with current equity.
2. **Event triggers**: structural breaks that should halt sizing even without a
   drawdown - VaR breach, correlation shock, WebSocket outage, funding spike,
   toxic VPIN. Driven by the ``on_*`` handlers, which ``risk/breaker_bus.py``
   subscribes to the event bus.

NO MANUAL OVERRIDE. ``override_allowed = False``.

What changed in Phase 1, and why
--------------------------------
The previous implementation had one boolean trip and no way back:

- **Any** venue idle for 60s tripped it (``not connected or secs > 60``). With
  reconnect backoff reaching 120s, and OKX/MEXC routinely blocked by the ISP,
  that fired within hours of every start. Now only ``required_venues`` can trip;
  a secondary venue going quiet sets ``degraded`` instead.
- Nothing ever cleared a trip. ``daily_reset`` only cleared reasons containing
  "Daily", and was itself never called, so one outage suppressed every signal
  for the life of the process. Trips now carry a clear policy and expire.
- ``update()`` reassigned ``self._state = CircuitBreakerState()``, which would
  have silently wiped every event trip the moment an equity feed existed. State
  is now *derived* from the active trips rather than stored, so that class of
  bug cannot recur.

Listeners registered with :meth:`add_listener` are called on every trip and
clear. They must be synchronous and must not raise - the app wires them to
``bus.publish`` (synchronous by design) and to Telegram.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.config import CIRCUIT_BREAKER

logger = logging.getLogger("nexus.circuit_breaker")

# Event-trigger thresholds (single place to tune).
EVENT_THRESHOLDS = {
    "correlation_shock_delta": 0.30,
    "correlation_shock_window_s": 3600.0,
    "ws_outage_seconds": 60.0,
    "funding_zscore": 3.0,
    "vpin_toxic": 0.85,
}

# How each kind of trip is allowed to clear.
#   after          - expires this long after the last time it fired
#   feeds_healthy  - expires once every required venue has been healthy this long
#   daily / weekly - expires only at the scheduled reset
TRIP_POLICY: dict[str, dict[str, Any]] = {
    "daily_loss": {"clear": "daily"},
    "weekly_loss": {"clear": "weekly"},
    "drawdown": {"clear": "daily"},
    "ws_outage": {"clear": "feeds_healthy", "healthy_for_s": 300.0},
    "var_breach": {"clear": "after", "after_s": 3600.0},
    "correlation_shock": {"clear": "after", "after_s": 3600.0},
    "funding_spike": {"clear": "after", "after_s": 3600.0},
    "vpin_toxic": {"clear": "after", "after_s": 3600.0},
}

Listener = Callable[[str, "Trip"], None]


@dataclass(frozen=True, slots=True)
class Trip:
    kind: str
    reason: str
    tripped_at: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "tripped_at": self.tripped_at,
            "clears": TRIP_POLICY.get(self.kind, {}).get("clear", "manual"),
        }


class CircuitBreakerState:
    """A read-only view. Built fresh on every access to ``CircuitBreaker.state``."""

    def __init__(
        self,
        *,
        trips: dict[str, Trip] | None = None,
        daily_loss_pct: float = 0.0,
        weekly_loss_pct: float = 0.0,
        drawdown_from_peak_pct: float = 0.0,
        leverage_reduced: bool = False,
        degraded: bool = False,
        degraded_reason: str = "",
        equity: float | None = None,
    ) -> None:
        self._trips = trips or {}
        self.daily_loss_pct = daily_loss_pct
        self.weekly_loss_pct = weekly_loss_pct
        self.drawdown_from_peak_pct = drawdown_from_peak_pct
        self.leverage_reduced = leverage_reduced
        self.degraded = degraded
        self.degraded_reason = degraded_reason
        self.equity = equity
        self.reset_time: str = str(CIRCUIT_BREAKER["reset_time"])

    @property
    def triggered(self) -> bool:
        return bool(self._trips)

    @property
    def signals_suppressed(self) -> bool:
        return bool(self._trips)

    @property
    def trigger_reason(self) -> str:
        if not self._trips:
            return ""
        newest = max(self._trips.values(), key=lambda t: t.tripped_at)
        if len(self._trips) == 1:
            return newest.reason
        return f"{newest.reason} (+{len(self._trips) - 1} more)"

    @property
    def active_trips(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in sorted(self._trips.values(), key=lambda t: t.tripped_at)]

    def to_dict(self) -> dict:
        # Every key the frontend reads today is preserved verbatim; the new
        # ones are additive (RiskTab reads triggered / trigger_reason /
        # *_loss_pct / drawdown_from_peak_pct / leverage_reduced /
        # signals_suppressed / reset_time).
        return {
            "triggered": self.triggered,
            "trigger_reason": self.trigger_reason,
            "daily_loss_pct": round(self.daily_loss_pct, 4),
            "weekly_loss_pct": round(self.weekly_loss_pct, 4),
            "drawdown_from_peak_pct": round(self.drawdown_from_peak_pct, 4),
            "leverage_reduced": self.leverage_reduced,
            "signals_suppressed": self.signals_suppressed,
            "reset_time": self.reset_time,
            "active_trips": self.active_trips,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "equity": self.equity,
        }


class CircuitBreaker:
    """Drawdown + event circuit breaker. Cannot be overridden manually."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._trips: dict[str, Trip] = {}
        self._listeners: list[Listener] = []

        self._peak_equity: float = 0.0
        self._day_start_equity: float = 0.0
        self._week_start_equity: float = 0.0
        self._current_equity: float | None = None
        self._day_start_time: float = 0.0

        self._degraded_reason: str = ""
        self._ws_healthy_since: float | None = None

        self._event_log: list[dict[str, Any]] = []
        self._rho_history: list[tuple[float, float]] = []

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        """Register a synchronous callback invoked as ``listener(action, trip)``
        where action is "tripped" or "cleared"."""
        self._listeners.append(listener)

    def _notify(self, action: str, trip: Trip) -> None:
        for listener in self._listeners:
            try:
                listener(action, trip)
            except Exception:  # noqa: BLE001  # reason: a broken notifier must never stop the breaker itself
                logger.exception("circuit-breaker listener failed on %s %s", action, trip.kind)

    # ------------------------------------------------------------------
    # Trip lifecycle
    # ------------------------------------------------------------------

    def _trip(self, kind: str, reason: str, payload: dict[str, Any] | None = None) -> bool:
        """Record (or refresh) a trip. Returns True if it is active afterwards."""
        now = self._clock()
        trip = Trip(kind=kind, reason=reason, tripped_at=now, payload=payload or {})
        existing = self._trips.get(kind)
        self._trips[kind] = trip
        self._log_event(kind, reason, payload)
        if existing is None:
            logger.critical("CIRCUIT BREAKER [%s]: %s", kind, reason)
            self._notify("tripped", trip)
        else:
            logger.warning("circuit breaker %s re-armed: %s", kind, reason)
        return True

    def _clear(self, kind: str, why: str) -> None:
        trip = self._trips.pop(kind, None)
        if trip is None:
            return
        self._log_event(f"{kind}_cleared", why, {"tripped_at": trip.tripped_at})
        logger.info("circuit breaker %s cleared: %s", kind, why)
        self._notify("cleared", trip)

    def _expire(self) -> None:
        """Drop trips whose clear condition is satisfied.

        Called at the start of every public accessor, so a trip can never be
        reported active past its policy even if nothing ticks the breaker.
        """
        now = self._clock()
        for kind, trip in list(self._trips.items()):
            policy = TRIP_POLICY.get(kind, {})
            mode = policy.get("clear")
            if mode == "after":
                after_s = float(policy.get("after_s", 3600.0))
                if now - trip.tripped_at >= after_s:
                    self._clear(kind, f"no recurrence for {after_s / 60:.0f} min")
            elif mode == "feeds_healthy":
                healthy_for = float(policy.get("healthy_for_s", 300.0))
                since = self._ws_healthy_since
                if since is not None and now - since >= healthy_for:
                    self._clear(kind, f"required feeds healthy for {healthy_for / 60:.0f} min")

    def tick(self) -> CircuitBreakerState:
        """Explicit expiry pass for a scheduled service. Equivalent to reading ``state``."""
        return self.state

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitBreakerState:
        self._expire()
        daily = weekly = drawdown = 0.0
        equity = self._current_equity
        if equity is not None:
            if self._day_start_equity > 0:
                daily = (self._day_start_equity - equity) / self._day_start_equity * 100
            if self._week_start_equity > 0:
                weekly = (self._week_start_equity - equity) / self._week_start_equity * 100
            if self._peak_equity > 0:
                drawdown = (self._peak_equity - equity) / self._peak_equity * 100
        leverage_reduced = daily / 100 >= float(CIRCUIT_BREAKER["leverage_reduction_threshold"])
        return CircuitBreakerState(
            trips=dict(self._trips),
            daily_loss_pct=daily,
            weekly_loss_pct=weekly,
            drawdown_from_peak_pct=drawdown,
            leverage_reduced=leverage_reduced,
            degraded=bool(self._degraded_reason),
            degraded_reason=self._degraded_reason,
            equity=equity,
        )

    def can_trade(self) -> bool:
        """No override."""
        return not self.state.signals_suppressed

    def get_leverage_cap(self, requested_leverage: int) -> int:
        if self.state.leverage_reduced:
            return max(1, requested_leverage // 2)
        return requested_leverage

    # ------------------------------------------------------------------
    # Threshold triggers
    # ------------------------------------------------------------------

    def initialize(self, current_equity: float) -> None:
        self._peak_equity = max(self._peak_equity, current_equity)
        self._day_start_equity = current_equity
        if self._week_start_equity == 0:
            self._week_start_equity = current_equity
        self._current_equity = current_equity
        self._day_start_time = self._clock()

    def update(self, current_equity: float) -> CircuitBreakerState:
        """Feed current equity and evaluate the loss thresholds.

        Event trips are untouched here - they have their own lifecycle.
        """
        if self._day_start_equity == 0:
            self.initialize(current_equity)
            return self.state

        self._current_equity = current_equity
        self._peak_equity = max(self._peak_equity, current_equity)
        state = self.state

        limits = (
            (
                "daily_loss",
                state.daily_loss_pct / 100,
                float(CIRCUIT_BREAKER["daily_loss_limit_pct"]),
                "Daily loss",
            ),
            (
                "weekly_loss",
                state.weekly_loss_pct / 100,
                float(CIRCUIT_BREAKER["weekly_loss_limit_pct"]),
                "Weekly loss",
            ),
            (
                "drawdown",
                state.drawdown_from_peak_pct / 100,
                float(CIRCUIT_BREAKER["max_drawdown_from_peak_pct"]),
                "Drawdown",
            ),
        )
        for kind, actual, limit, label in limits:
            if actual >= limit and kind not in self._trips:
                self._trip(
                    kind,
                    f"{label} {actual * 100:.2f}% >= {limit * 100:.2f}%",
                    {"actual_pct": actual * 100, "limit_pct": limit * 100},
                )
        return self.state

    def daily_reset(self, current_equity: float | None = None) -> None:
        """Called at 00:00 UTC by the scheduler. Clears the daily loss trips."""
        equity = current_equity if current_equity is not None else self._current_equity
        if equity is not None:
            self._day_start_equity = equity
            self._current_equity = equity
            self._peak_equity = max(self._peak_equity, equity)
        self._day_start_time = self._clock()
        for kind in ("daily_loss", "drawdown"):
            self._clear(kind, "daily reset")

    def weekly_reset(self, current_equity: float | None = None) -> None:
        equity = current_equity if current_equity is not None else self._current_equity
        if equity is not None:
            self._week_start_equity = equity
        self._clear("weekly_loss", "weekly reset")

    # ------------------------------------------------------------------
    # Event triggers
    # ------------------------------------------------------------------

    def _log_event(self, kind: str, detail: str, payload: dict[str, Any] | None = None) -> None:
        self._event_log.append(
            {"ts": self._clock(), "kind": kind, "detail": detail, "payload": payload or {}}
        )
        if len(self._event_log) > 128:
            del self._event_log[:-128]

    def on_var_breach(self, realized_pnl: float, var_99: float) -> bool:
        self._expire()
        if var_99 <= 0 or realized_pnl >= 0:
            return False
        if abs(realized_pnl) > var_99:
            return self._trip(
                "var_breach",
                f"Realized loss {realized_pnl:.2f} exceeds VaR99 {var_99:.2f}",
                {"realized_pnl": realized_pnl, "var_99": var_99},
            )
        return False

    def on_correlation_snapshot(self, avg_rho: float, ts: float | None = None) -> bool:
        self._expire()
        t = self._clock() if ts is None else ts
        cutoff = t - float(EVENT_THRESHOLDS["correlation_shock_window_s"])
        self._rho_history = [(s, r) for s, r in self._rho_history if s >= cutoff]
        shocked = False
        if self._rho_history:
            max_delta = max(abs(avg_rho - old) for _, old in self._rho_history)
            if max_delta >= float(EVENT_THRESHOLDS["correlation_shock_delta"]):
                self._trip(
                    "correlation_shock",
                    f"Correlation shock |delta rho|={max_delta:.3f} within 1h window",
                    {"current_rho": avg_rho, "max_delta": max_delta},
                )
                shocked = True
        self._rho_history.append((t, avg_rho))
        return shocked

    def on_ws_gap_report(self, gap_report: dict[str, Any]) -> bool:
        """Consume ``WSManager.gap_report()``.

        Only a required venue can trip the breaker. Secondary venues going idle
        set ``degraded`` - real information, but not a reason to stop trading.
        """
        self._expire()
        required = [str(v).lower() for v in CIRCUIT_BREAKER.get("required_venues", [])]
        threshold = float(EVENT_THRESHOLDS["ws_outage_seconds"])

        required_down: list[str] = []
        secondary_down: list[str] = []
        saw_required = False

        for stream, bundle in gap_report.items():
            if not isinstance(bundle, dict):
                continue
            secs = bundle.get("seconds_since_last_event")
            connected = bundle.get("connected", True)
            is_required = any(token in str(stream).lower() for token in required)
            if is_required:
                saw_required = True
            if secs is None:
                continue
            if not connected or float(secs) > threshold:
                (required_down if is_required else secondary_down).append(f"{stream} idle {float(secs):.0f}s")

        self._degraded_reason = "; ".join(secondary_down) if secondary_down else ""

        if required_down:
            self._ws_healthy_since = None
            return self._trip(
                "ws_outage",
                f"WS stream {required_down[0]}",
                {"required_down": required_down, "secondary_down": secondary_down},
            )

        # Required venues are healthy. Start (or continue) the recovery clock -
        # `_expire` clears the outage trip once it has held long enough.
        if saw_required and self._ws_healthy_since is None:
            self._ws_healthy_since = self._clock()
        self._expire()
        return False

    def on_funding_zscore(self, stream: str, zscore: float) -> bool:
        self._expire()
        if abs(zscore) >= float(EVENT_THRESHOLDS["funding_zscore"]):
            return self._trip(
                "funding_spike",
                f"Funding z-score {zscore:.2f} on {stream} (|z|>=3)",
                {"stream": stream, "zscore": zscore},
            )
        return False

    def on_vpin(self, stream: str, vpin: float) -> bool:
        self._expire()
        if vpin >= float(EVENT_THRESHOLDS["vpin_toxic"]):
            return self._trip(
                "vpin_toxic",
                f"VPIN {vpin:.3f} on {stream} - toxic flow",
                {"stream": stream, "vpin": vpin},
            )
        return False

    def recent_events(self, n: int = 32) -> list:
        return list(self._event_log)[-n:]
