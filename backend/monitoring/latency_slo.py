"""
Nexus - Latency SLO Tracker

Per-stream percentile tracker (p50/p95/p99) using a streaming quantile
estimator (P2 quantile algorithm) - constant memory, O(1) per update.

SLO default: p99 ≤ 250 ms. Alerts fire when any tracked stream breaches
the configured budget for a sustained `breach_window` of samples.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional


class _P2Estimator:
    """Jain & Chlamtac (1985) P2 streaming quantile estimator."""

    def __init__(self, p: float):
        if not (0.0 < p < 1.0):
            raise ValueError("p must be in (0, 1)")
        self.p = p
        self.n = [1, 2, 3, 4, 5]
        self.n_prime = [1.0, 1.0 + 2.0 * p, 1.0 + 4.0 * p, 3.0 + 2.0 * p, 5.0]
        self.dn = [0.0, p / 2.0, p, (1.0 + p) / 2.0, 1.0]
        self.q: List[float] = []

    def add(self, x: float) -> None:
        if len(self.q) < 5:
            self.q.append(x)
            if len(self.q) == 5:
                self.q.sort()
            return
        # Locate cell k.
        if x < self.q[0]:
            self.q[0] = x
            k = 0
        elif x < self.q[1]:
            k = 0
        elif x < self.q[2]:
            k = 1
        elif x < self.q[3]:
            k = 2
        elif x <= self.q[4]:
            k = 3
        else:
            self.q[4] = x
            k = 3

        for i in range(k + 1, 5):
            self.n[i] += 1
        for i in range(5):
            self.n_prime[i] += self.dn[i]

        for i in range(1, 4):
            d = self.n_prime[i] - self.n[i]
            if (d >= 1 and self.n[i + 1] - self.n[i] > 1) or \
               (d <= -1 and self.n[i - 1] - self.n[i] < -1):
                ds = 1 if d >= 0 else -1
                qp = self._parabolic(i, ds)
                if self.q[i - 1] < qp < self.q[i + 1]:
                    self.q[i] = qp
                else:
                    self.q[i] = self._linear(i, ds)
                self.n[i] += ds

    def _parabolic(self, i: int, d: int) -> float:
        term1 = d / (self.n[i + 1] - self.n[i - 1])
        term2 = ((self.n[i] - self.n[i - 1] + d) *
                 (self.q[i + 1] - self.q[i]) / (self.n[i + 1] - self.n[i]))
        term3 = ((self.n[i + 1] - self.n[i] - d) *
                 (self.q[i] - self.q[i - 1]) / (self.n[i] - self.n[i - 1]))
        return self.q[i] + term1 * (term2 + term3)

    def _linear(self, i: int, d: int) -> float:
        return self.q[i] + d * (self.q[i + d] - self.q[i]) / (self.n[i + d] - self.n[i])

    def quantile(self) -> Optional[float]:
        if len(self.q) < 5:
            return None
        return self.q[2]


@dataclass
class LatencySLO:
    stream: str
    budget_ms: float
    breach_window: int = 10
    breach_threshold: int = 5


class LatencyTracker:
    """Per-stream streaming latency percentiles + SLO breach detection."""

    def __init__(self, slos: Optional[List[LatencySLO]] = None, default_budget_ms: float = 250.0):
        self.default_budget_ms = default_budget_ms
        self._slos: Dict[str, LatencySLO] = {s.stream: s for s in (slos or [])}
        self._p50: Dict[str, _P2Estimator] = {}
        self._p95: Dict[str, _P2Estimator] = {}
        self._p99: Dict[str, _P2Estimator] = {}
        self._recent: Dict[str, Deque[float]] = {}
        self._count: Dict[str, int] = {}

    def _ensure(self, stream: str) -> None:
        if stream not in self._p99:
            self._p50[stream] = _P2Estimator(0.50)
            self._p95[stream] = _P2Estimator(0.95)
            self._p99[stream] = _P2Estimator(0.99)
            self._recent[stream] = deque(maxlen=128)
            self._count[stream] = 0
            if stream not in self._slos:
                self._slos[stream] = LatencySLO(stream=stream, budget_ms=self.default_budget_ms)

    def record(self, stream: str, latency_ms: float) -> None:
        self._ensure(stream)
        self._p50[stream].add(latency_ms)
        self._p95[stream].add(latency_ms)
        self._p99[stream].add(latency_ms)
        self._recent[stream].append(latency_ms)
        self._count[stream] += 1

    def breached(self, stream: str) -> bool:
        if stream not in self._slos:
            return False
        slo = self._slos[stream]
        recent = list(self._recent.get(stream, []))[-slo.breach_window:]
        if len(recent) < slo.breach_window:
            return False
        breaches = sum(1 for ms in recent if ms > slo.budget_ms)
        return breaches >= slo.breach_threshold

    def snapshot(self) -> Dict[str, Dict]:
        out: Dict[str, Dict] = {}
        for stream in self._count.keys():
            slo = self._slos[stream]
            out[stream] = {
                "p50_ms": round(self._p50[stream].quantile() or 0.0, 3),
                "p95_ms": round(self._p95[stream].quantile() or 0.0, 3),
                "p99_ms": round(self._p99[stream].quantile() or 0.0, 3),
                "count": self._count[stream],
                "budget_ms": slo.budget_ms,
                "breached": self.breached(stream),
            }
        return out
