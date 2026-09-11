"""
Nexus - Tick-Level Replay Harness

Replays archived WS event logs back into the alpha + risk stack so the
same state machine that runs live can be validated against historical
microstructure without any time-travel bias.

Tick archives are expected to be JSONL files where each line is:
    {"ts": <epoch_s>, "stream": "<name>", "data": {...}}

This module does not *produce* the archives - that's the job of the
ingestion layer's tap (future work). It consumes anything matching the
schema above.
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Iterator, List, Optional


def iter_archive(path: str | Path) -> Iterator[Dict[str, Any]]:
    """Stream events from a JSONL(.gz) archive, oldest → newest."""
    p = Path(path)
    opener = gzip.open if str(p).endswith(".gz") else open
    with opener(p, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


async def replay(
    archives: Iterable[str | Path],
    on_event: Callable[[str, Dict[str, Any]], Awaitable[Any]],
    *,
    speed: float = 0.0,
    max_events: Optional[int] = None,
    stream_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Async replay - dispatches events to `on_event(stream, data)`.

    Parameters
    ----------
    archives
        Paths (possibly multiple shards) to read sequentially.
    on_event
        Awaitable callback receiving `(stream_name, event_dict)`.
    speed
        Realtime factor. 0 = as-fast-as-possible (default). 1 = real-time,
        2 = 2× real-time. Honors the *original* inter-arrival spacing.
    max_events
        Optional cap; useful for quick smoke replays.
    stream_filter
        If set, only events whose `stream` is in this list are dispatched.
    """
    import asyncio

    delivered = 0
    dropped = 0
    t_wall_start = time.time()
    t_event_start: Optional[float] = None

    for archive in archives:
        for ev in iter_archive(archive):
            if max_events is not None and delivered >= max_events:
                break

            stream = ev.get("stream", "")
            if stream_filter and stream not in stream_filter:
                dropped += 1
                continue
            ts = float(ev.get("ts", 0.0))
            data = ev.get("data", {})

            if speed > 0 and t_event_start is not None:
                event_elapsed = ts - t_event_start
                wall_elapsed = time.time() - t_wall_start
                target_wall = event_elapsed / speed
                lag = target_wall - wall_elapsed
                if lag > 0:
                    await asyncio.sleep(lag)
            if t_event_start is None:
                t_event_start = ts

            await on_event(stream, data)
            delivered += 1

    return {
        "events_delivered": delivered,
        "events_dropped": dropped,
        "wall_seconds": round(time.time() - t_wall_start, 3),
    }
