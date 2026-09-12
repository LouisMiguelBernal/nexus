"""Alert dispatch with dedupe and cooldown.

Every alert used to be delivered. ``_zone_check_loop`` runs every 60s and
re-emits ``zone_approach`` for as long as price sits within 0.5% of a zone, so
a quiet afternoon near a level produced dozens of identical Telegram messages
and dozens of identical rows in ``alerts`` - which is how an alert channel
stops being read.

Here every alert is reduced to a dedupe key (``type:symbol:bucket``) and
suppressed if that key fired inside its cooldown (``alerts/alert_types.py``).
A suppressed alert is neither stored nor sent: the first alert in a window is
the record, and the suppression is counted for ``/metrics``.

The breaker publishes trips through the bus rather than calling this directly,
because breaker listeners are synchronous and dispatch is not - which is
exactly why ``core.bus.publish`` is synchronous.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from backend.alerts.alert_types import ALERT_TYPES, DEFAULT_COOLDOWN_S
from backend.data.store import Store

logger = logging.getLogger("nexus.alerts.dispatcher")


class TelegramLike(Protocol):
    configured: bool

    async def send_alert(self, alert_type: str, data: dict) -> bool: ...


@dataclass(frozen=True, slots=True)
class DispatchResult:
    sent: bool
    reason: str  # sent | cooldown | unknown_type | telegram_failed | telegram_disabled
    dedupe_key: str
    cooldown_remaining_s: float = 0.0
    alert_id: int | None = None


def _round_bucket(value: float, rel_width: float = 0.005) -> str:
    """Snap a price to a fixed logarithmic grid ``rel_width`` wide.

    The grid must not depend on the value being bucketed. Deriving a step from
    ``value * 0.001`` is self-referential - every price then rounds to roughly
    itself and two quotes of the same zone never collapse, which is the whole
    point. A log grid is uniform at any scale, so BTC at 80,000 and XRP at 0.5
    both get 0.5%-wide buckets (matching the zone_approach trigger band).

    Returns the grid representative, so the key stays readable in logs.
    """
    if value <= 0:
        return "0"
    step = math.log1p(rel_width)
    index = math.floor(math.log(value) / step)
    return f"{math.exp(index * step):.6g}"


def dedupe_key(alert_type: str, payload: dict[str, Any]) -> str:
    """``type:symbol:bucket`` - stable across repeats of the same condition."""
    symbol = str(payload.get("symbol") or "").upper()
    bucket_kind = str(ALERT_TYPES.get(alert_type, {}).get("bucket", "none"))
    bucket = ""
    if bucket_kind == "zone":
        level = payload.get("zone_price") or payload.get("price_center") or payload.get("price") or 0
        bucket = f"{payload.get('tier', '')}@{_round_bucket(float(level or 0))}"
    elif bucket_kind == "direction":
        bucket = str(payload.get("direction") or "")
    elif bucket_kind == "event":
        bucket = str(payload.get("event_name") or "")
    elif bucket_kind == "trip":
        bucket = f"{payload.get('trip_kind', '')}:{payload.get('action', '')}"
    return f"{alert_type}:{symbol}:{bucket}"


def cooldown_for(alert_type: str) -> float:
    return float(ALERT_TYPES.get(alert_type, {}).get("cooldown_s", DEFAULT_COOLDOWN_S))


class AlertDispatcher:
    def __init__(
        self,
        store: Store,
        telegram: TelegramLike | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.telegram = telegram
        self._clock = clock
        self.sent = 0
        self.suppressed = 0
        self.unknown = 0

    async def dispatch(self, alert: dict[str, Any]) -> DispatchResult:
        """Store and deliver one alert unless its key is inside a cooldown."""
        alert_type = str(alert.get("type") or alert.get("alert_type") or "unknown")
        symbol = str(alert.get("symbol") or "")
        message = str(alert.get("message") or alert.get("detail") or alert_type)
        key = dedupe_key(alert_type, alert)
        now = self._clock()

        spec = ALERT_TYPES.get(alert_type)
        if spec is None:
            # A typo in an emitter used to vanish into the alerts table. Say so.
            self.unknown += 1
            logger.warning("alert type %r is not in the registry; delivering without dedupe", alert_type)

        cooldown = cooldown_for(alert_type)
        if cooldown > 0:
            row = await self.store.fetch_one(
                "SELECT last_sent_at FROM alert_state WHERE dedupe_key = ?", (key,)
            )
            if row is not None:
                elapsed = now - float(row["last_sent_at"])
                if elapsed < cooldown:
                    self.suppressed += 1
                    logger.debug("alert %s suppressed, %.0fs of cooldown left", key, cooldown - elapsed)
                    return DispatchResult(False, "cooldown", key, cooldown - elapsed)

        payload_json = json.dumps(alert, default=str)[:20_000]
        telegram_wanted = bool(spec.get("telegram", True)) if spec else True
        telegram_ok = bool(self.telegram and self.telegram.configured and telegram_wanted)

        delivered = False
        reason = "telegram_disabled"
        if telegram_ok and self.telegram is not None:
            try:
                delivered = bool(await self.telegram.send_alert(alert_type, alert))
                reason = "sent" if delivered else "telegram_failed"
            except Exception:  # noqa: BLE001  # reason: delivery failure must not lose the stored alert
                logger.exception("telegram send failed for %s", alert_type)
                reason = "telegram_failed"

        alert_id = await self.store.execute(
            "INSERT INTO alerts (alert_type, symbol, message, data, sent_telegram) VALUES (?, ?, ?, ?, ?)",
            (alert_type, symbol, message, payload_json, 1 if delivered else 0),
        )

        # The cooldown starts when the alert was accepted, whether or not
        # Telegram happened to be reachable - otherwise an outage turns into a
        # burst of retries the moment it recovers.
        await self.store.execute(
            """
            INSERT INTO alert_state (dedupe_key, alert_type, symbol, last_sent_at, send_count, last_payload)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                last_sent_at = excluded.last_sent_at,
                send_count = alert_state.send_count + 1,
                last_payload = excluded.last_payload
            """,
            (key, alert_type, symbol, now, payload_json),
        )
        self.sent += 1
        return DispatchResult(delivered, reason, key, 0.0, alert_id)

    async def recent(self, limit: int = 50, alert_type: str | None = None) -> list[dict[str, Any]]:
        if alert_type:
            return await self.store.fetch_all(
                "SELECT * FROM alerts WHERE alert_type = ? ORDER BY id DESC LIMIT ?", (alert_type, limit)
            )
        return await self.store.fetch_all("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))

    async def prune_state(self, older_than_s: float = 7 * 24 * 3600) -> int:
        cutoff = self._clock() - older_than_s
        return await self.store.execute("DELETE FROM alert_state WHERE last_sent_at < ?", (cutoff,))

    def stats(self) -> dict[str, int]:
        return {"sent": self.sent, "suppressed": self.suppressed, "unknown_type": self.unknown}
