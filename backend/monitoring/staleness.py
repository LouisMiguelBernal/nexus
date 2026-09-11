"""
Nexus - Feed Staleness Detector

Flags streams where `now - last_event_time > multiplier · median_inter_arrival`.

Consumes `WSManager.gap_report()` from `backend/ingestion/ws_manager.py`
(P0-4). Separate from `LatencyTracker` - latency measures *per-message*
arrival jitter; staleness measures *absence* of messages.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, Optional


class StalenessDetector:
    def __init__(self, multiplier: float = 3.0, sample_cap: int = 128):
        self.multiplier = float(multiplier)
        self._arrivals: Dict[str, Deque[float]] = {}
        self._sample_cap = int(sample_cap)

    def record_arrival(self, stream: str, ts: Optional[float] = None) -> None:
        t = time.time() if ts is None else float(ts)
        dq = self._arrivals.setdefault(stream, deque(maxlen=self._sample_cap))
        dq.append(t)

    def _median_inter_arrival(self, stream: str) -> Optional[float]:
        dq = self._arrivals.get(stream)
        if not dq or len(dq) < 3:
            return None
        seq = list(dq)
        gaps = [seq[i] - seq[i - 1] for i in range(1, len(seq))]
        gaps.sort()
        m = len(gaps)
        if m == 0:
            return None
        return (gaps[m // 2] if m % 2 == 1 else 0.5 * (gaps[m // 2 - 1] + gaps[m // 2]))

    def check(self, stream: str) -> Dict[str, Any]:
        dq = self._arrivals.get(stream)
        if not dq:
            return {"stream": stream, "stale": False, "reason": "no samples"}
        last = dq[-1]
        now = time.time()
        since_last = now - last
        median = self._median_inter_arrival(stream)
        if median is None or median <= 0:
            return {
                "stream": stream,
                "stale": False,
                "reason": "insufficient history",
                "seconds_since_last": round(since_last, 3),
            }
        threshold = self.multiplier * median
        return {
            "stream": stream,
            "stale": since_last > threshold,
            "seconds_since_last": round(since_last, 3),
            "median_inter_arrival": round(median, 3),
            "threshold": round(threshold, 3),
            "multiplier": self.multiplier,
        }

    def check_all(self) -> Dict[str, Dict[str, Any]]:
        return {s: self.check(s) for s in self._arrivals.keys()}

    def ingest_gap_report(self, gap_report: Dict[str, Any]) -> None:
        """Pull `last_event_time` values from `WSManager.gap_report()` and
        register them as synthetic arrivals. Lets monitoring run off the
        same ground-truth timestamps the ingestion layer already records."""
        for stream, bundle in gap_report.items():
            if not isinstance(bundle, dict):
                continue
            let = bundle.get("last_event_time")
            if let is None:
                continue
            self.record_arrival(stream, ts=float(let))
