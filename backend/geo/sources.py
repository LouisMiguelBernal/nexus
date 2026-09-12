"""
Nexus - local global-event sources.

Every feed here is free, keyless and directly attributable:

  USGS       seismic, M4.5+ rolling day        (geojson)
  GDACS      EU JRC disaster alerts, red/orange/green scale   (rss)
  EONET      NASA open natural events - storms, volcanoes, fires  (json)
  SWPC       NOAA geomagnetic / radio / radiation storm scales    (json)
  CISA KEV   actively-exploited vulnerabilities                    (json)
  OpenSky    tracked aircraft per watch region                     (json)
  RSS wires  BBC World, Al Jazeera, UN peace & security, Fed, EIA

Each fetch is independent and failure-isolated. A dead feed contributes nothing
to the composite score and is reported as unavailable rather than counted as
zero risk - the difference matters, because "no earthquakes" and "USGS is down"
are not the same signal.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from backend.config import GEO_RSS, GEO_SOURCES
from backend.geo import domains
from backend.ops.logutil import warn_throttled

logger = logging.getLogger("nexus.geo.sources")

_UA = "nexus-terminal/1.0 (local research client)"


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        resp = await client.get(url, headers={"User-Agent": _UA})
        if resp.status_code != 200:
            logger.debug("geo source %s -> HTTP %s", url, resp.status_code)
            return None
        return resp
    except Exception as e:  # noqa: BLE001
        warn_throttled(logger, f"geo_source:{url}", "geo source %s failed: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Minimal RSS reader
#
# These feeds are plain RSS 2.0 and the fields we want are top-level. A full XML
# parser would be a dependency and a parse tree we immediately discard.
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_ITEM_RE = re.compile(r"<(item|entry)[\s\S]*?</\1>", re.IGNORECASE)


def _strip(raw: str) -> str:
    text = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", raw)
    text = _TAG_RE.sub(" ", text)
    for entity, char in (
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&apos;", "'"),
        ("&#39;", "'"),
        ("&nbsp;", " "),
    ):
        text = text.replace(entity, char)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    return re.sub(r"\s+", " ", text).strip()


def _tag(block: str, name: str) -> str | None:
    m = re.search(rf"<{name}[^>]*>([\s\S]*?)</{name}>", block, re.IGNORECASE)
    return _strip(m.group(1)) if m else None


def parse_rss(
    xml: str,
    source: str,
    limit: int = 20,
    extra_tags: dict[str, str] | None = None,
) -> list[dict]:
    """
    ``extra_tags`` maps an output key to a namespaced element name, for feeds
    that carry structured fields alongside the prose (GDACS alert level, for
    instance). Reading those is always better than inferring severity from the
    text.
    """
    items: list[dict] = []
    for match in _ITEM_RE.finditer(xml):
        if len(items) >= limit:
            break
        block = match.group(0)
        title = _tag(block, "title")
        if not title:
            continue
        row = {
            "title": title,
            "link": _tag(block, "link") or "",
            "published": _tag(block, "pubDate") or _tag(block, "published") or "",
            "source": source,
            "summary": (_tag(block, "description") or "")[:400],
        }
        for key, tag_name in (extra_tags or {}).items():
            row[key] = _tag(block, tag_name)
        items.append(row)
    return items


# ---------------------------------------------------------------------------
# Individual feeds
# ---------------------------------------------------------------------------


async def fetch_seismic(client: httpx.AsyncClient) -> dict:
    resp = await _get(client, GEO_SOURCES["usgs"])
    if not resp:
        return {"available": False, "events": []}

    features = (resp.json() or {}).get("features") or []
    events = []
    for f in features:
        p = f.get("properties") or {}
        coords = ((f.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        mag = p.get("mag")
        if not isinstance(mag, (int, float)):
            continue
        events.append(
            {
                "magnitude": round(float(mag), 1),
                "place": p.get("place") or "",
                "time": p.get("time"),
                "tsunami": bool(p.get("tsunami")),
                "lon": coords[0],
                "lat": coords[1],
            }
        )
    events.sort(key=lambda e: e["magnitude"], reverse=True)
    return {"available": True, "events": events[:20]}


async def fetch_disasters(client: httpx.AsyncClient) -> dict:
    """
    GDACS alerts, severity read from the structured ``<gdacs:alertlevel>`` tag.

    Do not infer the level from the text: every single item in this feed
    contains the substring "red" somewhere in its boilerplate, so a naive
    ``"red" in blob`` check scores all 385 of them as red alerts - which pins
    the composite geo score at 100 permanently and, now that the score feeds the
    macro gate, would throttle position sizing forever.
    """
    resp = await _get(client, GEO_SOURCES["gdacs"])
    if not resp:
        return {"available": False, "events": []}

    items = parse_rss(resp.text, "GDACS", limit=60, extra_tags={"level_raw": "gdacs:alertlevel"})

    events = []
    for it in items:
        raw = (it.pop("level_raw", None) or "").strip().lower()
        if raw in ("red", "orange", "green"):
            level = raw
        else:
            # Fallback: GDACS titles begin with the colour ("Green earthquake
            # ..."), so anchor on the first word rather than searching the body.
            first = it["title"].split(" ", 1)[0].lower()
            level = first if first in ("red", "orange", "green") else "green"
        events.append({**it, "level": level})

    # Only the alerting ones are worth carrying to the UI.
    events.sort(key=lambda e: {"red": 0, "orange": 1, "green": 2}[e["level"]])
    return {"available": True, "events": events[:30]}


async def fetch_natural_events(client: httpx.AsyncClient) -> dict:
    """NASA EONET open events, bucketed by category."""
    resp = await _get(client, GEO_SOURCES["eonet"])
    if not resp:
        return {"available": False, "events": [], "by_category": {}}

    raw = (resp.json() or {}).get("events") or []
    events, by_category = [], {}
    for e in raw:
        cats = [c.get("title") for c in (e.get("categories") or []) if c.get("title")]
        category = cats[0] if cats else "Other"
        by_category[category] = by_category.get(category, 0) + 1
        geometry = (e.get("geometry") or [{}])[-1]
        events.append(
            {
                "title": e.get("title") or "",
                "category": category,
                "date": geometry.get("date"),
                "link": e.get("link") or "",
            }
        )
    return {"available": True, "events": events[:40], "by_category": by_category}


async def fetch_space_weather(client: httpx.AsyncClient) -> dict:
    """
    NOAA storm scales. G/S/R run 0-5; anything at 3+ is operationally relevant
    (HF blackouts, GPS degradation, satellite drag).
    """
    resp = await _get(client, GEO_SOURCES["noaa_swpc"])
    if not resp:
        return {"available": False}

    data = resp.json() or {}
    # Key "0" is today's observed set; the API also returns forecast days.
    today = data.get("0") or {}

    def scale(key: str) -> int:
        raw = (today.get(key) or {}).get("Scale")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    return {
        "available": True,
        "geomagnetic": scale("G"),
        "radiation": scale("S"),
        "radio_blackout": scale("R"),
    }


async def fetch_wires(client: httpx.AsyncClient) -> dict:
    """Conflict / policy / energy wires. Deduped on title prefix."""

    async def one(name: str, url: str) -> list[dict]:
        resp = await _get(client, url)
        return parse_rss(resp.text, name, limit=12) if resp else []

    batches = await asyncio.gather(*(one(name, url) for name, url in GEO_RSS), return_exceptions=True)

    seen, items = set(), []
    for batch in batches:
        if not isinstance(batch, list):
            continue
        for it in batch:
            key = it["title"].lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
    return {"available": bool(items), "items": items[:50]}


async def fetch_all() -> dict:
    """
    Every local source in parallel. Returns whatever answered; the caller reads
    ``available`` per block rather than assuming a complete snapshot.
    """
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        seismic, disasters, natural, space, wires, cyber, aviation = await asyncio.gather(
            fetch_seismic(client),
            fetch_disasters(client),
            fetch_natural_events(client),
            fetch_space_weather(client),
            fetch_wires(client),
            domains.fetch_cyber(client),
            domains.fetch_aviation(client),
            return_exceptions=True,
        )

    def ok(v, fallback):
        return v if isinstance(v, dict) else fallback

    return {
        "ts": time.time(),
        "seismic": ok(seismic, {"available": False, "events": []}),
        "disasters": ok(disasters, {"available": False, "events": []}),
        "natural": ok(natural, {"available": False, "events": [], "by_category": {}}),
        "space_weather": ok(space, {"available": False}),
        "wires": ok(wires, {"available": False, "items": []}),
        "cyber": ok(cyber, {"available": False}),
        "aviation": ok(aviation, {"available": False, "regions": []}),
    }
