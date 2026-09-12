"""
Nexus - worldmonitor.app enrichment client (strictly optional).

worldmonitor publishes derived layers we would not build ourselves: a Country
Instability Index and a supply-chain chokepoint status (Hormuz, Suez, Malacca,
Panama) that maps directly onto energy and shipping risk.

Three facts govern how this module behaves:

1. **Their REST API needs a key** (``X-WorldMonitor-Key: wm_<40 hex>``). Set
   ``WORLDMONITOR_API_KEY`` to enable it. Without one this reports
   ``available: False, reason: "no api key"`` - not an error, just absent.
2. **``NEXUS_VISION.md`` forbids mandatory cloud services.** So this never
   raises into a caller, caches for 30 minutes, and short-circuits for an hour
   after a failure rather than retrying every poll.
3. **Sandbox fixtures are not data.** ``WORLDMONITOR_SANDBOX=1`` reads their
   key-free sample payloads so the UI can be exercised without a key, but every
   such response is flagged ``sample: True`` and
   ``backend/geo/instability.py`` refuses to score it. Sample numbers must never
   reach the macro gate.

Operation paths come from their published sandbox index, not from guesswork.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from backend.config import (
    WORLDMONITOR_API_KEY,
    WORLDMONITOR_BASE,
    WORLDMONITOR_COUNTRIES,
    WORLDMONITOR_ENABLED,
    WORLDMONITOR_OPS,
    WORLDMONITOR_SANDBOX,
    WORLDMONITOR_SANDBOX_BASE,
    WORLDMONITOR_UA,
)

logger = logging.getLogger("nexus.geo.worldmonitor")

_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_TTL = 1800.0

# After a failure, stop asking for a while. An unreachable optional upstream
# should cost one request an hour, not one per poll cycle.
_COOLDOWN_UNTIL = 0.0
_COOLDOWN = 3600.0

_SANDBOX_FIXTURES = {
    "country_risk": f"{WORLDMONITOR_SANDBOX_BASE}/get-country-risk.json",
    "chokepoints": f"{WORLDMONITOR_SANDBOX_BASE}/get-chokepoint-status.json",
}


def _headers() -> dict[str, str]:
    # Their policy challenges default library user agents with a 403.
    h = {"User-Agent": WORLDMONITOR_UA, "Accept": "application/json"}
    if WORLDMONITOR_API_KEY:
        h["X-WorldMonitor-Key"] = WORLDMONITOR_API_KEY
    return h


def status() -> dict[str, Any]:
    """Why the enrichment is or is not running. Surfaced in the UI."""
    if not WORLDMONITOR_ENABLED:
        return {"mode": "disabled", "reason": "WORLDMONITOR_ENABLED=0"}
    if WORLDMONITOR_SANDBOX:
        return {"mode": "sandbox", "reason": "sample fixtures - excluded from scoring"}
    if not WORLDMONITOR_API_KEY:
        return {"mode": "unavailable", "reason": "no api key (set WORLDMONITOR_API_KEY)"}
    return {"mode": "live", "reason": None}


async def _call(client: httpx.AsyncClient, op: str, params: dict[str, str] | None = None) -> dict | None:
    """One operation. Sandbox mode unwraps the fixture's response envelope."""
    if WORLDMONITOR_SANDBOX:
        url = _SANDBOX_FIXTURES.get(op)
        if not url:
            return None
        resp = await client.get(url, headers={"User-Agent": WORLDMONITOR_UA})
        if resp.status_code != 200:
            return None
        return ((resp.json() or {}).get("response") or {}).get("body")

    path = WORLDMONITOR_OPS.get(op)
    if not path:
        return None
    resp = await client.get(f"{WORLDMONITOR_BASE}{path}", params=params or {}, headers=_headers())
    if resp.status_code != 200:
        logger.debug("worldmonitor %s -> HTTP %s", op, resp.status_code)
        return None
    return resp.json()


def _country_row(body: dict) -> dict | None:
    """Flatten their CII envelope into one row."""
    cii = body.get("cii") or {}
    score = cii.get("combinedScore")
    if not isinstance(score, (int, float)):
        return None
    components = cii.get("components") or {}
    return {
        "country": body.get("countryName") or body.get("countryCode") or "?",
        "code": body.get("countryCode"),
        "score": round(float(score), 2),
        "advisory": cii.get("advisoryLevel") or body.get("advisoryLevel"),
        "components": {
            k: components.get(k)
            for k in ("ciiContribution", "geoConvergence", "militaryActivity", "newsActivity")
            if isinstance(components.get(k), (int, float))
        },
    }


def _chokepoint_rows(body: dict) -> list[dict]:
    rows = []
    for c in body.get("chokepoints") or []:
        if not isinstance(c, dict):
            continue
        rows.append(
            {
                "name": c.get("name") or c.get("id") or "chokepoint",
                "congestion": c.get("congestionLevel"),
                "active_warnings": c.get("activeWarnings"),
                "ais_disruptions": c.get("aisDisruptions"),
                "affected_routes": c.get("affectedRoutes") or [],
            }
        )
    return rows


async def fetch_instability() -> dict:
    """
    Country instability + chokepoint status, or ``{"available": False}``.

    The returned dict always carries ``sample``: when True the payload is a
    sandbox fixture and must not be scored.
    """
    global _COOLDOWN_UNTIL

    state = status()
    if state["mode"] in ("disabled", "unavailable"):
        return {"available": False, **state}

    now = time.time()
    cached = _CACHE.get("data")
    if cached and (now - float(_CACHE.get("ts") or 0.0)) < _TTL:
        return cached  # type: ignore[return-value]
    if now < _COOLDOWN_UNTIL:
        return {"available": False, "mode": state["mode"], "reason": "cooldown"}

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            chokepoints_body = await _call(client, "chokepoints")

            if WORLDMONITOR_SANDBOX:
                # One fixture stands in for the whole set; asking ten times
                # would return the same sample ten times.
                country_bodies = [await _call(client, "country_risk")]
            else:
                country_bodies = list(
                    await asyncio.gather(
                        *(
                            _call(client, "country_risk", {"country_code": code})
                            for code in WORLDMONITOR_COUNTRIES
                        ),
                        return_exceptions=True,
                    )
                )

        countries = []
        for body in country_bodies:
            if isinstance(body, dict):
                row = _country_row(body)
                if row:
                    countries.append(row)

        chokepoints = _chokepoint_rows(chokepoints_body) if isinstance(chokepoints_body, dict) else []

        if not countries and not chokepoints:
            raise RuntimeError("no usable payload")

        countries.sort(key=lambda c: c["score"], reverse=True)
        top = countries[:20]
        result = {
            "available": True,
            "sample": WORLDMONITOR_SANDBOX,
            "mode": state["mode"],
            "source": "worldmonitor.app",
            "countries": top,
            "chokepoints": chokepoints,
            "peak_score": top[0]["score"] if top else None,
            "mean_top5": (round(sum(c["score"] for c in top[:5]) / min(5, len(top)), 2) if top else None),
        }
        _CACHE.update({"data": result, "ts": now})
        return result

    except Exception as e:  # noqa: BLE001
        logger.debug("worldmonitor enrichment failed: %s", e)

    _COOLDOWN_UNTIL = now + _COOLDOWN
    logger.info("worldmonitor unreachable; using local instability score only")
    return {"available": False, "mode": state["mode"], "reason": "unreachable"}


def reset_state() -> None:
    """Clear cache and cooldown. Tests rely on this; production does not."""
    global _COOLDOWN_UNTIL
    _CACHE.update({"data": None, "ts": 0.0})
    _COOLDOWN_UNTIL = 0.0
