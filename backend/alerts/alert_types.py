"""Alert registry: trigger, severity, delivery, and the dedupe policy.

This table was imported by nothing - alerts were emitted ad hoc from the loops
and every one was delivered, so ``zone_approach`` re-fired every 60s for as
long as price stayed within 0.5% of a zone. It is now the registry the
dispatcher validates and rate-limits against (``alerts/dispatcher.py``).

Fields
------
cooldown_s
    Minimum seconds between two alerts sharing a dedupe key. 0 = always send
    (the sender is already event-driven and does its own deduplication).
bucket
    How the dedupe key is narrowed beyond ``type:symbol``. "zone" buckets by
    price so a *different* zone still alerts; "none" collapses to the symbol.
"""

ALERT_TYPES: dict[str, dict] = {
    "zone_approach": {
        "trigger": "price within 0.5% of Golden/Platinum zone",
        "severity": "medium",
        "telegram": True,
        "cooldown_s": 1800,
        "bucket": "zone",
    },
    "zone_hit": {
        "trigger": "price enters zone boundary",
        "severity": "high",
        "telegram": True,
        "cooldown_s": 600,
        "bucket": "zone",
    },
    "macro_danger": {
        "trigger": "Tier 1 or Tier 2 event within danger window",
        "severity": "critical",
        "telegram": True,
        "cooldown_s": 3600,
        "bucket": "event",
    },
    "squeeze_alert": {
        "trigger": "squeeze_risk_pct > 70 on either side",
        "severity": "high",
        "telegram": True,
        "cooldown_s": 1800,
        "bucket": "direction",
    },
    "liquidation_cascade": {
        # Emitted by the liquidation loop since long before this registry
        # existed; it simply was not listed here.
        "trigger": "clustered forced orders exceed the cascade threshold",
        "severity": "high",
        "telegram": True,
        "cooldown_s": 600,
        "bucket": "none",
    },
    "leverage_warning": {
        "trigger": "effective_leverage > 8 or margin_ratio > 0.75",
        "severity": "high",
        "telegram": True,
        "cooldown_s": 1800,
        "bucket": "none",
    },
    "circuit_breaker": {
        "trigger": "a breaker trip or clear",
        "severity": "critical",
        "telegram": True,
        # The breaker only notifies on transitions, so this is a backstop
        # against a flapping feed, not the primary dedupe.
        "cooldown_s": 300,
        "bucket": "trip",
    },
    "morning_brief": {
        "trigger": "08:00 daily scheduled",
        "severity": "info",
        "telegram": True,
        "cooldown_s": 0,
        "bucket": "none",
    },
}

DEFAULT_COOLDOWN_S = 900
