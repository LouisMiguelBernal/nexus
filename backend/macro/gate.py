"""
Nexus - Macro Danger Window Gate
Automatically suppresses/restricts signals during high-impact macro events.
NO signal bypasses this gate. NO manual override.
"""

import logging
import time
from typing import Dict, Optional

from backend.config import MACRO_GATE
from backend.macro.calendar import EconomicCalendar, MacroEvent

logger = logging.getLogger("nexus.macro_gate")


class GateStatus:
    """Current state of the macro gate."""

    def __init__(self):
        self.is_restricted = False
        self.active_tier: Optional[str] = None
        self.active_event: Optional[str] = None
        self.confidence_threshold: float = 0.65
        self.max_position_pct: float = 0.02
        self.leverage_cap: int = 10
        self.new_positions_allowed: bool = True
        self.minutes_until_event: Optional[float] = None
        self.minutes_until_clear: Optional[float] = None

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
        }


class MacroGate:
    """
    The macro gate - what makes the system safe under leverage.
    Without it, a 10x position can be wiped by a surprise CPI print.
    """

    def __init__(self, calendar: EconomicCalendar):
        self.calendar = calendar
        self._status = GateStatus()

    def evaluate(self) -> GateStatus:
        """
        Check all active danger windows and return the most restrictive gate status.
        Called every signal evaluation cycle.
        """
        active_events = self.calendar.get_active_danger_windows()
        self._status = GateStatus()  # Reset

        if not active_events:
            return self._status

        # Find the most restrictive active event
        most_restrictive: Optional[MacroEvent] = None
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
            return self._status

        tier_cfg = MACRO_GATE.get(most_restrictive.tier, {})

        self._status.is_restricted = True
        self._status.active_tier = most_restrictive.tier
        self._status.active_event = most_restrictive.name
        self._status.confidence_threshold = tier_cfg.get("confidence_threshold", 0.65)
        self._status.max_position_pct = tier_cfg.get("max_position_pct", 0.02)
        self._status.leverage_cap = tier_cfg.get("leverage_cap", 10)
        self._status.new_positions_allowed = tier_cfg.get("new_positions_allowed", True)
        self._status.minutes_until_event = most_restrictive.minutes_until

        # Time until danger window clears
        window_sec = most_restrictive.danger_window_hours * 3600
        clear_time = most_restrictive.timestamp + window_sec
        self._status.minutes_until_clear = max(0, (clear_time - time.time()) / 60)

        logger.warning(
            f"MACRO GATE ACTIVE: {most_restrictive.name} ({most_restrictive.tier}) "
            f"| Threshold: {self._status.confidence_threshold} "
            f"| Max position: {self._status.max_position_pct*100}% "
            f"| Leverage cap: {self._status.leverage_cap}x"
        )

        return self._status

    def can_open_position(self) -> bool:
        """Check if new positions are allowed right now."""
        status = self.evaluate()
        return status.new_positions_allowed

    def get_adjusted_params(self, base_confidence: float, base_position_pct: float,
                            base_leverage: int) -> Dict:
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
