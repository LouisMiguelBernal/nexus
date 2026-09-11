"""
Nexus - additional global-event domains: cyber and aviation.

Both replicate a worldmonitor panel from a keyless upstream, and both are
deliberately narrow. The question is never "what is happening in the world" but
"is something happening that reprices risk" - so each returns a small number of
numbers with a defensible meaning, not a firehose.

  cyber     CISA Known Exploited Vulnerabilities. Counts *additions*, because
            the catalogue only ever grows and its total encodes nothing but
            elapsed time. Feeds the instability composite.

  aviation  OpenSky anonymous states, bucketed into watch regions. Airspace
            closures show up as a collapse in tracked aircraft over a box.
            Display-only: it needs a per-region baseline before the deviation
            means anything, and that baseline is built in memory over the
            session, so an early reading is honestly labelled as warming up.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional

import httpx

from backend.config import AVIATION_REGIONS, AVIATION_STATES_URL, CYBER_KEV_URL

logger = logging.getLogger("nexus.geo.domains")

_UA = "nexus-terminal/1.0 (local research client)"


# ---------------------------------------------------------------------------
# Cyber - CISA KEV
# ---------------------------------------------------------------------------

_KEV_CACHE: Dict[str, object] = {"data": None, "ts": 0.0}
_KEV_TTL = 6 * 3600.0  # the catalogue updates on business days at most


async def fetch_cyber(client: httpx.AsyncClient) -> Dict:
    now = time.time()
    cached = _KEV_CACHE.get("data")
    if cached and (now - float(_KEV_CACHE.get("ts") or 0.0)) < _KEV_TTL:
        return cached  # type: ignore[return-value]

    try:
        resp = await client.get(CYBER_KEV_URL, headers={"User-Agent": _UA})
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        body = resp.json() or {}
    except Exception as e:
        logger.debug("CISA KEV failed: %s", e)
        return cached if cached else {"available": False}  # type: ignore[return-value]

    vulns = body.get("vulnerabilities") or []
    today = datetime.now(timezone.utc).date()
    cutoff_7 = today - timedelta(days=7)
    cutoff_30 = today - timedelta(days=30)

    added_7 = added_30 = ransomware_7 = 0
    recent: List[Dict] = []
    for v in vulns:
        raw = v.get("dateAdded")
        if not isinstance(raw, str):
            continue
        try:
            added = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            continue

        known_ransomware = str(v.get("knownRansomwareCampaignUse", "")).lower() == "known"
        if added >= cutoff_30:
            added_30 += 1
        if added >= cutoff_7:
            added_7 += 1
            if known_ransomware:
                ransomware_7 += 1
            recent.append({
                "cve": v.get("cveID"),
                "vendor": v.get("vendorProject"),
                "product": v.get("product"),
                "name": v.get("vulnerabilityName"),
                "date_added": raw,
                "ransomware": known_ransomware,
            })

    recent.sort(key=lambda r: r["date_added"] or "", reverse=True)
    result = {
        "available": True,
        "catalog_size": len(vulns),
        "catalog_version": body.get("catalogVersion"),
        "added_7d": added_7,
        "added_30d": added_30,
        "ransomware_7d": ransomware_7,
        "recent": recent[:12],
    }
    _KEV_CACHE.update({"data": result, "ts": now})
    return result


# ---------------------------------------------------------------------------
# Aviation - OpenSky
# ---------------------------------------------------------------------------

# Rolling per-region counts, newest last. In memory only: OpenSky's anonymous
# tier will not support backfilling a real history, so the baseline is whatever
# this session has observed.
_BASELINE: Dict[str, Deque[int]] = {name: deque(maxlen=24) for name, *_ in AVIATION_REGIONS}
_MIN_SAMPLES = 6

_AV_CACHE: Dict[str, object] = {"data": None, "ts": 0.0}
_AV_TTL = 600.0


async def fetch_aviation(client: httpx.AsyncClient) -> Dict:
    """
    Tracked aircraft per watch region, with a deviation from the session
    baseline once enough samples exist.

    OpenSky's anonymous tier is metered aggressively, so one bounding box is
    fetched per call and the result is cached for ten minutes. A 429 is normal
    and simply leaves the previous reading in place.
    """
    now = time.time()
    cached = _AV_CACHE.get("data")
    if cached and (now - float(_AV_CACHE.get("ts") or 0.0)) < _AV_TTL:
        return cached  # type: ignore[return-value]

    regions: List[Dict] = []
    for name, lamin, lomin, lamax, lomax in AVIATION_REGIONS:
        try:
            resp = await client.get(
                AVIATION_STATES_URL,
                params={"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax},
                headers={"User-Agent": _UA},
                timeout=25,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            states = (resp.json() or {}).get("states") or []
        except Exception as e:
            logger.debug("OpenSky %s failed: %s", name, e)
            regions.append({"region": name, "available": False})
            continue

        count = len(states)
        history = _BASELINE[name]
        # Deviation is measured against the baseline BEFORE this sample, so a
        # collapse is not partly averaged into its own reference.
        deviation: Optional[float] = None
        warming = len(history) < _MIN_SAMPLES
        if not warming:
            mean = sum(history) / len(history)
            if mean > 0:
                deviation = (count - mean) / mean * 100.0
        history.append(count)

        regions.append({
            "region": name,
            "available": True,
            "aircraft": count,
            "baseline_samples": len(history),
            "warming_up": warming,
            "deviation_pct": round(deviation, 1) if deviation is not None else None,
        })

    live = [r for r in regions if r.get("available")]
    result = {
        "available": bool(live),
        "regions": regions,
        "total_aircraft": sum(r["aircraft"] for r in live),
    }
    if live:
        _AV_CACHE.update({"data": result, "ts": now})
    return result


def reset_state() -> None:
    """Clear caches and the aviation baseline. For tests."""
    _KEV_CACHE.update({"data": None, "ts": 0.0})
    _AV_CACHE.update({"data": None, "ts": 0.0})
    for history in _BASELINE.values():
        history.clear()
