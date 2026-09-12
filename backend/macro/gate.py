"""
Nexus - Macro Danger Window Gate
Automatically suppresses/restricts signals during high-impact macro events.
NO signal bypasses this gate. NO manual override.
"""

import logging
import time

from backend.config import GEO_GATE, MACRO_GATE
from backend.macro.calendar import EconomicCalendar, MacroEvent

logger = logging.getLogger("nexus.macro_gate")


class GateStatus:
    """Current state of the macro gate."""

    def __init__(self):
        self.is_restricted = False
        self.active_tier: str | None = None
        self.active_event: str | None = None
        self.confidence_threshold: float = 0.65
        self.max_position_pct: float = 0.02
        self.leverage_cap: int = 10
        self.new_positions_allowed: bool = True
        self.minutes_until_event: float | None = None
        self.minutes_until_clear: float | None = None
        # Geopolitical overlay (backend/geo). None = no geo source reported,
        # which is "unknown", not "safe" - the gate simply stays calendar-only.
        self.geo_score: float | None = None
        self.geo_band: str = "unknown"
        self.geo_tier: str | None = None
        # Which inputs actually constrained this status.
        self.sources: list = []

    def to_dict(self) -> dict:
        return {
            "is_restricted": self.is_restricted,
            "status": "restricted" if self.is_restricted else "open",
            "active_tier": self.active_tier,
            "active_event": self.active_event,
            "confidence_threshold": self.confidence_threshold,
            "max_position_pct": self.max_position_pct,
            "leverage_cap": self.leverage_cap,
            "new_positions_allowed": self.new_positions_allowed,
            "minutes_until_event": self.minutes_until_event,
            "minutes_until_clear": self.minutes_until_clear,
            "geo_score": self.geo_score,
            "geo_band": self.geo_band,
            "geo_tier": self.geo_tier,
            "sources": self.sources,
        }


class MacroGate:
    """
    The macro gate - what makes the system safe under leverage.
    Without it, a 10x position can be wiped by a surprise CPI print.
    """

    def __init__(self, calendar: EconomicCalendar):
        self.calendar = calendar
        self._status = GateStatus()
        # Geopolitical overlay, published by the geo poller. Kept as plain data
        # so the gate never reaches into backend.geo and never blocks on it.
        self._geo: dict = {"score": None, "band": "unknown", "reason": None}

    def set_geo_risk(self, score: float | None, band: str = "unknown", reason: str | None = None) -> None:
        """
        Publish the current geopolitical risk reading (0-100).

        Called by the geo poller. Passing ``None`` restores calendar-only
        behaviour, which is what must happen when every geo source is down -
        an unknown world is not a safe world, but it is also not evidence of
        danger, and inventing a number either way would be worse.
        """
        self._geo = {"score": score, "band": band, "reason": reason}

    @property
    def geo_risk(self) -> dict:
        return dict(self._geo)

    def evaluate(self) -> GateStatus:
        """
        Most restrictive of the calendar gate and the geopolitical gate.

        Both inputs are advisory-only until Phase 6, but they compose the same
        way they would live: take the tightest constraint on every axis. A CPI
        print during a Hormuz escalation must not be less restrictive than
        either alone.
        """
        self._status = self._evaluate_calendar()
        self._apply_geo_overlay(self._status)
        return self._status

    def _evaluate_calendar(self) -> GateStatus:
        """Danger-window evaluation. Unchanged behaviour, now a component."""
        active_events = self.calendar.get_active_danger_windows()
        status = GateStatus()

        if not active_events:
            return status

        # Find the most restrictive active event
        most_restrictive: MacroEvent | None = None
        most_restrictive_tier_rank = 99

        tier_rank = {
            "Tier1_Critical": 1,
            "Tier2_High": 2,
            "Tier3_Medium": 3,
            "Tier4_Low": 4,
        }

        for event in active_events:
            rank = tier_rank.get(event.tier, 99)
            if rank < most_restrictive_tier_rank:
                most_restrictive = event
                most_restrictive_tier_rank = rank

        if most_restrictive is None:
            return status

        tier_cfg = MACRO_GATE.get(most_restrictive.tier, {})

        status.is_restricted = True
        status.active_tier = most_restrictive.tier
        status.active_event = most_restrictive.name
        status.confidence_threshold = tier_cfg.get("confidence_threshold", 0.65)
        status.max_position_pct = tier_cfg.get("max_position_pct", 0.02)
        status.leverage_cap = tier_cfg.get("leverage_cap", 10)
        status.new_positions_allowed = tier_cfg.get("new_positions_allowed", True)
        status.minutes_until_event = most_restrictive.minutes_until
        status.sources = ["calendar"]

        # Time until danger window clears
        window_sec = most_restrictive.danger_window_hours * 3600
        clear_time = most_restrictive.timestamp + window_sec
        status.minutes_until_clear = max(0, (clear_time - time.time()) / 60)

        logger.warning(
            f"MACRO GATE ACTIVE: {most_restrictive.name} ({most_restrictive.tier}) "
            f"| Threshold: {status.confidence_threshold} "
            f"| Max position: {status.max_position_pct * 100}% "
            f"| Leverage cap: {status.leverage_cap}x"
        )

        return status

    def _apply_geo_overlay(self, status: GateStatus) -> None:
        """
        Fold the geopolitical score into an already-computed calendar status.

        Every axis takes the tighter of the two values, so the overlay can only
        ever restrict. It cannot loosen a calendar restriction, and it cannot
        re-open positions the calendar closed.
        """
        score = self._geo.get("score")
        status.geo_score = score
        status.geo_band = str(self._geo.get("band") or "unknown")

        if not isinstance(score, (int, float)):
            return  # no geo source reported - calendar-only, as before

        band_cfg = None
        for cfg in sorted(GEO_GATE.values(), key=lambda c: -c["min_score"]):
            if score >= cfg["min_score"]:
                band_cfg = cfg
                break
        if band_cfg is None:
            return  # below the watch threshold: geopolitics is not binding

        status.geo_tier = band_cfg["tier"]
        status.is_restricted = True
        status.confidence_threshold = max(status.confidence_threshold, band_cfg["confidence_threshold"])
        status.max_position_pct = min(status.max_position_pct, band_cfg["max_position_pct"])
        status.leverage_cap = min(status.leverage_cap, band_cfg["leverage_cap"])
        status.new_positions_allowed = status.new_positions_allowed and band_cfg["new_positions_allowed"]
        if "geo" not in status.sources:
            status.sources.append("geo")

        # The calendar names the event; when only geopolitics is binding the
        # status still needs to say why it is restricted.
        if not status.active_tier:
            status.active_tier = band_cfg["tier"]
        if not status.active_event:
            status.active_event = f"Geopolitical risk {status.geo_band} ({score:.0f}/100)"

        logger.warning(
            "GEO GATE ACTIVE: score %.0f (%s) | Threshold: %s | Max position: %s%% | Leverage cap: %sx",
            score,
            status.geo_band,
            status.confidence_threshold,
            status.max_position_pct * 100,
            status.leverage_cap,
        )

    def can_open_position(self) -> bool:
        """Check if new positions are allowed right now."""
        status = self.evaluate()
        return status.new_positions_allowed

    def get_adjusted_params(
        self, base_confidence: float, base_position_pct: float, base_leverage: int
    ) -> dict:
        """
        Adjust trading parameters based on current gate status.
        Returns modified confidence threshold, position size, and leverage.
        """
        status = self.evaluate()

        if not status.is_restricted:
            return {
                "confidence_threshold": base_confidence,
                "max_position_pct": base_position_pct,
                "leverage_cap": base_leverage,
                "gate_active": False,
                "reason": None,
            }

        return {
            "confidence_threshold": max(base_confidence, status.confidence_threshold),
            "max_position_pct": min(base_position_pct, status.max_position_pct),
            "leverage_cap": min(base_leverage, status.leverage_cap),
            "gate_active": True,
            "reason": f"{status.active_event} ({status.active_tier})",
            "minutes_until_clear": status.minutes_until_clear,
        }

    @property
    def status(self) -> GateStatus:
        return self._status
