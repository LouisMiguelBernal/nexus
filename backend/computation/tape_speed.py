"""
Nexus - Tape speed tracker.

Measures trades per second over a rolling window. Flags bursts where the
current rate is >2σ above the trailing mean - often a sign of a liquidity
event, news hit, or aggressive directional player.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Optional


class TapeSpeedTracker:
    """Per-symbol rolling trades/sec sampler."""

    def __init__(self, symbol: str, window_seconds: int = 5, max_samples: int = 720):
        self.symbol = symbol
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        # Trade timestamps (unix seconds) - keep just enough for a 60s look-back
        self._ts: Deque[float] = deque(maxlen=20_000)
        # Sampled tps history: (t, tps)
        self._samples: Deque[tuple] = deque(maxlen=max_samples)

    def record(self, timestamp_s: float) -> None:
        """Record that a trade occurred at ``timestamp_s`` (unix seconds)."""
        self._ts.append(float(timestamp_s))

    def sample(self) -> Optional[Dict]:
        """Compute current trades/sec over the trailing window and append a sample.
        Returns the sample dict or None when there's no data yet."""
        now = time.time()
        cutoff = now - self.window_seconds
        # Trim from the left - deque is ordered by arrival
        while self._ts and self._ts[0] < cutoff:
            self._ts.popleft()
        count = len(self._ts)
        tps = count / self.window_seconds if self.window_seconds > 0 else 0.0
        self._samples.append((now, tps))
        return {"time": now, "tps": round(tps, 2), "count": count, "window": self.window_seconds}

    def latest(self) -> Optional[Dict]:
        if not self._samples:
            return None
        t, tps = self._samples[-1]
        return {"time": t, "tps": round(tps, 2)}

    def series(self, limit: int = 180) -> list:
        data = list(self._samples)[-limit:]
        return [{"time": t, "tps": round(tps, 2)} for t, tps in data]

    def summary(self) -> Dict:
        if not self._samples:
            return {"count": 0, "latest": None, "mean": None, "std": None, "burst": False}
        vals = [s[1] for s in self._samples]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = var ** 0.5
        latest = vals[-1]
        burst = bool(std > 0 and (latest - mean) > 2 * std and latest > 1)
        return {
            "count": len(vals),
            "latest": round(latest, 2),
            "mean": round(mean, 2),
            "std": round(std, 2),
            "max": round(max(vals), 2),
            "burst": burst,
        }
