"""
Nexus - Minimal zone back-testing hook.

Replays historical klines against a given list of golden-zone bands and reports
hit-rate + reaction stats: how often price touched the zone, and whether it
bounced (bullish reversal off support / bearish off resistance) within N bars.

This is intentionally simple - it's a scaffolding to let the trader quickly
sanity-check whether their current zone map would have caught recent swings.
For proper alpha research we'd plug this into a vectorized backtester; for
now it's plumbing that opens the door.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass
class ZoneBand:
    price_low: float
    price_high: float
    zone_type: str      # "support" | "resistance" | …
    tier: str
    score: float = 0.0


@dataclass
class ZoneResult:
    zone: ZoneBand
    touches: int = 0
    bounces: int = 0
    breaks: int = 0
    touch_times: List[int] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        total = self.bounces + self.breaks
        return (self.bounces / total) if total > 0 else 0.0


def backtest_zones(
    candles: Iterable[Dict],
    zones: Iterable[ZoneBand],
    reaction_bars: int = 6,
    bounce_pct: float = 0.8,
) -> Dict:
    """Replay ``candles`` (each {time, open, high, low, close}) against ``zones``.

    A "touch" occurs when a candle's wick pierces the band.
    A "bounce" is registered when, within ``reaction_bars`` following bars,
    price moves at least ``bounce_pct`` percent in the direction expected by the
    zone type (up for support, down for resistance).
    Otherwise we count a "break".
    """
    candles = list(candles)
    zones = list(zones)
    results = [ZoneResult(zone=z) for z in zones]

    for i, c in enumerate(candles):
        high = float(c.get("high", 0))
        low = float(c.get("low", 0))
        if high <= 0 or low <= 0:
            continue
        for r in results:
            z = r.zone
            if high >= z.price_low and low <= z.price_high:
                # Touch - check reaction window
                r.touches += 1
                r.touch_times.append(int(c.get("time", 0)))
                future = candles[i + 1 : i + 1 + reaction_bars]
                if not future:
                    continue
                entry = float(c.get("close", 0)) or z.price_high
                if z.zone_type == "support":
                    peak = max((float(f.get("high", 0)) for f in future), default=entry)
                    move_pct = ((peak - entry) / entry * 100) if entry > 0 else 0
                    if move_pct >= bounce_pct:
                        r.bounces += 1
                    else:
                        r.breaks += 1
                else:  # resistance / default
                    trough = min((float(f.get("low", 0)) for f in future), default=entry)
                    move_pct = ((entry - trough) / entry * 100) if entry > 0 else 0
                    if move_pct >= bounce_pct:
                        r.bounces += 1
                    else:
                        r.breaks += 1

    # Aggregate
    total_touches = sum(r.touches for r in results)
    total_bounces = sum(r.bounces for r in results)
    total_breaks = sum(r.breaks for r in results)
    aggregate_hit_rate = (total_bounces / (total_bounces + total_breaks)) if (total_bounces + total_breaks) else 0.0

    return {
        "candles": len(candles),
        "zones": len(zones),
        "touches": total_touches,
        "bounces": total_bounces,
        "breaks": total_breaks,
        "hit_rate": round(aggregate_hit_rate, 4),
        "reaction_bars": reaction_bars,
        "bounce_pct": bounce_pct,
        "per_zone": [
            {
                "price_low": r.zone.price_low,
                "price_high": r.zone.price_high,
                "zone_type": r.zone.zone_type,
                "tier": r.zone.tier,
                "touches": r.touches,
                "bounces": r.bounces,
                "breaks": r.breaks,
                "hit_rate": round(r.hit_rate, 4),
            }
            for r in results
        ],
    }
