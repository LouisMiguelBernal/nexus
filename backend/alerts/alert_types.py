"""
Nexus - Alert Type Definitions
All alert message templates and trigger conditions.
"""

ALERT_TYPES = {
    "zone_approach": {
        "trigger": "price within 0.5% of Golden/Platinum zone",
        "severity": "medium",
        "telegram": True,
    },
    "zone_hit": {
        "trigger": "price enters zone boundary",
        "severity": "high",
        "telegram": True,
    },
    "macro_danger": {
        "trigger": "Tier 1 or Tier 2 event within danger window",
        "severity": "critical",
        "telegram": True,
    },
    "squeeze_alert": {
        "trigger": "squeeze_risk_pct > 70 on either side",
        "severity": "high",
        "telegram": True,
    },
    "leverage_warning": {
        "trigger": "effective_leverage > 8 or margin_ratio > 0.75",
        "severity": "high",
        "telegram": True,
    },
    "morning_brief": {
        "trigger": "08:00 daily scheduled",
        "severity": "info",
        "telegram": True,
    },
    "circuit_breaker": {
        "trigger": "daily loss > 5% or drawdown > 15% from peak",
        "severity": "critical",
        "telegram": True,
    },
}
