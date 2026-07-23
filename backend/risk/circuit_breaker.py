"""
Nexus - Drawdown + Event Circuit Breaker

Two trigger classes:

1. **Threshold triggers** (original): daily / weekly loss %, drawdown
   from peak. Driven by `update(current_equity)`.
2. **Event triggers** (P2): structural regime breaks that should halt
   sizing even without an equity drawdown. Driven by
   `register_event(kind, payload)`:

   * `var_breach`      - realized PnL outside 99% VaR envelope
   * `correlation_shock` - max|Δρ| > 0.3 within 1h window
   * `ws_outage`       - any stream down > 60s (consumes `ws_manager.gap_report`)
   * `funding_spike`   - |funding z-score| > 3σ
   * `vpin_toxic`      - running VPIN > 0.85 (Easley/López de Prado)

NO MANUAL OVERRIDE. override_allowed = False.
"""

import logging
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

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


class CircuitBreakerState:
    """Current circuit breaker state."""

    def __init__(self):
        self.triggered = False
        self.trigger_reason: str = ""
        self.daily_loss_pct: float = 0.0
        self.weekly_loss_pct: float = 0.0
        self.drawdown_from_peak_pct: float = 0.0
        self.leverage_reduced: bool = False
        self.signals_suppressed: bool = False
        self.reset_time: str = CIRCUIT_BREAKER["reset_time"]

    def to_dict(self) -> dict:
        return {
            "triggered": self.triggered,
            "trigger_reason": self.trigger_reason,
            "daily_loss_pct": round(self.daily_loss_pct, 4),
            "weekly_loss_pct": round(self.weekly_loss_pct, 4),
            "drawdown_from_peak_pct": round(self.drawdown_from_peak_pct, 4),
            "leverage_reduced": self.leverage_reduced,
            "signals_suppressed": self.signals_suppressed,
            "reset_time": self.reset_time,
        }


class CircuitBreaker:
    """
    Drawdown + daily loss circuit breaker.
    Cannot be overridden manually - override_allowed = False.
    """

    def __init__(self):
        self._peak_equity: float = 0.0
        self._day_start_equity: float = 0.0
        self._week_start_equity: float = 0.0
        self._state = CircuitBreakerState()
        self._day_start_time: float = 0.0
        # Event-trigger log (bounded). Each entry:
        #   {"ts": float, "kind": str, "detail": str, "payload": dict}
        self._event_log: Deque[Dict[str, Any]] = deque(maxlen=128)
        # Rolling correlation snapshots for Δρ detection.
        self._rho_history: Deque[tuple] = deque(maxlen=240)

    def initialize(self, current_equity: float):
        """Set starting equity values. Call on startup and daily reset."""
        self._peak_equity = max(self._peak_equity, current_equity)
        self._day_start_equity = current_equity
        if self._week_start_equity == 0:
            self._week_start_equity = current_equity
        self._day_start_time = time.time()

    def update(self, current_equity: float) -> CircuitBreakerState:
        """
        Update circuit breaker with current equity.
        Returns the current state - check .triggered and .signals_suppressed.
        """
        if self._day_start_equity == 0:
            self.initialize(current_equity)
            return self._state

        self._peak_equity = max(self._peak_equity, current_equity)
        self._state = CircuitBreakerState()

        # Daily loss check
        if self._day_start_equity > 0:
            daily_loss = (self._day_start_equity - current_equity) / self._day_start_equity
            self._state.daily_loss_pct = daily_loss * 100

        # Weekly loss check
        if self._week_start_equity > 0:
            weekly_loss = (self._week_start_equity - current_equity) / self._week_start_equity
            self._state.weekly_loss_pct = weekly_loss * 100

        # Drawdown from peak
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - current_equity) / self._peak_equity
            self._state.drawdown_from_peak_pct = drawdown * 100

        # Check triggers
        daily_pct = self._state.daily_loss_pct / 100
        weekly_pct = self._state.weekly_loss_pct / 100
        dd_pct = self._state.drawdown_from_peak_pct / 100

        # Leverage reduction threshold (3% daily)
        if daily_pct >= CIRCUIT_BREAKER["leverage_reduction_threshold"]:
            self._state.leverage_reduced = True

        # Daily loss limit (5%)
        if daily_pct >= CIRCUIT_BREAKER["daily_loss_limit_pct"]:
            self._state.triggered = True
            self._state.signals_suppressed = True
            self._state.trigger_reason = f"Daily loss {self._state.daily_loss_pct:.2f}% >= {CIRCUIT_BREAKER['daily_loss_limit_pct']*100}%"
            logger.critical(f"CIRCUIT BREAKER: {self._state.trigger_reason}")

        # Weekly loss limit (10%)
        if weekly_pct >= CIRCUIT_BREAKER["weekly_loss_limit_pct"]:
            self._state.triggered = True
            self._state.signals_suppressed = True
            self._state.trigger_reason = f"Weekly loss {self._state.weekly_loss_pct:.2f}% >= {CIRCUIT_BREAKER['weekly_loss_limit_pct']*100}%"
            logger.critical(f"CIRCUIT BREAKER: {self._state.trigger_reason}")

        # Max drawdown from peak (15%)
        if dd_pct >= CIRCUIT_BREAKER["max_drawdown_from_peak_pct"]:
            self._state.triggered = True
            self._state.signals_suppressed = True
            self._state.trigger_reason = f"Drawdown {self._state.drawdown_from_peak_pct:.2f}% >= {CIRCUIT_BREAKER['max_drawdown_from_peak_pct']*100}%"
            logger.critical(f"CIRCUIT BREAKER: {self._state.trigger_reason}")

        return self._state

    def can_trade(self) -> bool:
        """Check if trading is allowed. No override."""
        return not self._state.signals_suppressed

    def get_leverage_cap(self, requested_leverage: int) -> int:
        """If leverage is reduced, halve the requested leverage."""
        if self._state.leverage_reduced:
            return max(1, requested_leverage // 2)
        return requested_leverage

    def daily_reset(self, current_equity: float):
        """Reset daily counters. Called at 00:00 UTC."""
        self._day_start_equity = current_equity
        self._day_start_time = time.time()
        if self._state.triggered and "Daily" in self._state.trigger_reason:
            self._state.triggered = False
            self._state.signals_suppressed = False
            self._state.trigger_reason = ""
            logger.info("Circuit breaker daily reset - trading re-enabled")

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    # ------------------------------------------------------------------
    # Event triggers (P2)
    # ------------------------------------------------------------------

    def _trip(self, reason: str) -> None:
        self._state.triggered = True
        self._state.signals_suppressed = True
        self._state.trigger_reason = reason
        logger.critical(f"CIRCUIT BREAKER [event]: {reason}")

    def _log_event(self, kind: str, detail: str, payload: Optional[Dict] = None) -> None:
        self._event_log.append({
            "ts": time.time(),
            "kind": kind,
            "detail": detail,
            "payload": payload or {},
        })

    def on_var_breach(self, realized_pnl: float, var_99: float) -> bool:
        """Fire when a realized loss exceeds the 99% VaR envelope."""
        if var_99 <= 0 or realized_pnl >= 0:
            return False
        if abs(realized_pnl) > var_99:
            msg = f"Realized loss {realized_pnl:.2f} exceeds VaR99 {var_99:.2f}"
            self._log_event("var_breach", msg,
                            {"realized_pnl": realized_pnl, "var_99": var_99})
            self._trip(msg)
            return True
        return False

    def on_correlation_snapshot(self, avg_rho: float, ts: Optional[float] = None) -> bool:
        """Detect a |Δρ| > threshold spike vs any sample within the rolling window."""
        t = time.time() if ts is None else ts
        cutoff = t - EVENT_THRESHOLDS["correlation_shock_window_s"]
        # Purge stale samples.
        while self._rho_history and self._rho_history[0][0] < cutoff:
            self._rho_history.popleft()
        shocked = False
        if self._rho_history:
            prev_max = max(abs(avg_rho - old_rho) for _, old_rho in self._rho_history)
            if prev_max >= EVENT_THRESHOLDS["correlation_shock_delta"]:
                msg = f"Correlation shock |Δρ|={prev_max:.3f} within 1h window"
                self._log_event("correlation_shock", msg,
                                {"current_rho": avg_rho, "max_delta": prev_max})
                self._trip(msg)
                shocked = True
        self._rho_history.append((t, avg_rho))
        return shocked

    def on_ws_gap_report(self, gap_report: Dict[str, Any]) -> bool:
        """Consume `WSManager.gap_report()` and trip on any outage > threshold."""
        tripped = False
        for stream, bundle in gap_report.items():
            if not isinstance(bundle, dict):
                continue
            secs = bundle.get("seconds_since_last_event")
            connected = bundle.get("connected", True)
            if secs is None:
                continue
            if not connected or secs > EVENT_THRESHOLDS["ws_outage_seconds"]:
                msg = f"WS stream {stream} idle {secs:.1f}s"
                self._log_event("ws_outage", msg, {"stream": stream, "seconds": secs})
                self._trip(msg)
                tripped = True
        return tripped

    def on_funding_zscore(self, stream: str, zscore: float) -> bool:
        if abs(zscore) >= EVENT_THRESHOLDS["funding_zscore"]:
            msg = f"Funding z-score {zscore:.2f} on {stream} (|z|≥3)"
            self._log_event("funding_spike", msg, {"stream": stream, "zscore": zscore})
            self._trip(msg)
            return True
        return False

    def on_vpin(self, stream: str, vpin: float) -> bool:
        if vpin >= EVENT_THRESHOLDS["vpin_toxic"]:
            msg = f"VPIN {vpin:.3f} on {stream} - toxic flow"
            self._log_event("vpin_toxic", msg, {"stream": stream, "vpin": vpin})
            self._trip(msg)
            return True
        return False

    def recent_events(self, n: int = 32) -> list:
        return list(self._event_log)[-n:]
