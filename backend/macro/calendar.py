"""
Nexus - Economic Calendar + Tier Classification
Fetches upcoming macro events and classifies them by impact tier.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from backend.config import FRED_API_KEY, FRED_BASE, FRED_SERIES, MACRO_GATE

logger = logging.getLogger("nexus.calendar")

# Static event schedule - updated periodically from FRED + investing.com
# In production, this is populated from scraping or API calls.
# For now, a classification lookup for event names.
EVENT_TIER_MAP: dict[str, str] = {}
for tier_name, tier_cfg in MACRO_GATE.items():
    for event in tier_cfg["events"]:
        EVENT_TIER_MAP[event.lower()] = tier_name


@dataclass
class MacroEvent:
    name: str
    tier: str  # Tier1_Critical, Tier2_High, etc.
    timestamp: float  # UTC epoch
    description: str = ""
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None

    @property
    def minutes_until(self) -> float:
        return (self.timestamp - time.time()) / 60

    @property
    def is_past(self) -> bool:
        return self.timestamp < time.time()

    @property
    def danger_window_hours(self) -> float:
        cfg = MACRO_GATE.get(self.tier, {})
        return cfg.get("danger_window_hours", 0)

    @property
    def in_danger_window(self) -> bool:
        window_sec = self.danger_window_hours * 3600
        return abs(time.time() - self.timestamp) <= window_sec

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": self.tier,
            "timestamp": self.timestamp,
            "datetime_utc": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "minutes_until": round(self.minutes_until, 1),
            "in_danger_window": self.in_danger_window,
            "danger_window_hours": self.danger_window_hours,
            "description": self.description,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
        }


class EconomicCalendar:
    """Manages upcoming economic events."""

    def __init__(self):
        self._events: list[MacroEvent] = []
        self._last_fetch: float = 0

    def add_event(
        self,
        name: str,
        timestamp: float,
        description: str = "",
        forecast: float | None = None,
        previous: float | None = None,
    ):
        """Add a macro event with automatic tier classification."""
        name_lower = name.lower().replace(" ", "_")
        tier = "Tier4_Low"
        for event_key, event_tier in EVENT_TIER_MAP.items():
            if event_key in name_lower:
                tier = event_tier
                break

        event = MacroEvent(
            name=name,
            tier=tier,
            timestamp=timestamp,
            description=description,
            forecast=forecast,
            previous=previous,
        )
        self._events.append(event)
        # Keep sorted by time
        self._events.sort(key=lambda e: e.timestamp)
        # Prune old events (> 24h past)
        cutoff = time.time() - 86400
        self._events = [e for e in self._events if e.timestamp > cutoff]

    def get_upcoming(self, hours: int = 48) -> list[MacroEvent]:
        """Get events within the next N hours."""
        cutoff = time.time() + hours * 3600
        return [e for e in self._events if time.time() <= e.timestamp <= cutoff]

    def get_next_n(self, n: int = 5) -> list[MacroEvent]:
        """Get next N upcoming events."""
        future = [e for e in self._events if not e.is_past]
        return future[:n]

    def get_active_danger_windows(self) -> list[MacroEvent]:
        """Get events currently in their danger window."""
        return [e for e in self._events if e.in_danger_window]

    async def fetch_fred_data(self, series_id: str) -> dict | None:
        """Fetch latest data point from FRED."""
        if not FRED_API_KEY:
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    FRED_BASE,
                    params={
                        "series_id": series_id,
                        "api_key": FRED_API_KEY,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": 1,
                    },
                )
                data = resp.json()
                observations = data.get("observations", [])
                if observations:
                    return {
                        "value": observations[0].get("value"),
                        "date": observations[0].get("date"),
                    }
        except Exception as e:  # noqa: BLE001
            logger.error(f"FRED fetch error for {series_id}: {e}")
        return None

    async def fetch_macro_snapshot(self) -> dict:
        """Fetch current values for all tracked FRED series."""

        results = {}
        tasks = {name: self.fetch_fred_data(sid) for name, sid in FRED_SERIES.items()}
        for name, coro in tasks.items():
            result = await coro
            if result:
                results[name] = result
        self._last_fetch = time.time()
        return results
