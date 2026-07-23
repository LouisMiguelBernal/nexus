"""
Nexus - Risk Attribution

Per-symbol VaR contribution via Euler allocation:

    MCVaR_i = ∂VaR/∂w_i
    CVaR_i  = w_i · MCVaR_i
    Σ CVaR_i = VaR_total        (exactly, by Euler's theorem on H1)

This file is a thin adapter over `backend/risk/var.py::contribution_var`
so callers on the monitoring side don't need to import the risk engine
directly - and so the contribution surface can be diffed sample-over-
sample to detect concentration creep without the risk module carrying
any monitoring state.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

try:
    from backend.risk.var import VaRCalculator  # type: ignore
except Exception:  # pragma: no cover - keep module importable in isolation
    VaRCalculator = None  # type: ignore


class RiskAttributionTracker:
    def __init__(self):
        self._last_contributions: Dict[str, float] = {}
        self._last_total_var: float = 0.0

    def compute(
        self,
        positions: Dict[str, float],
        returns_by_symbol: Dict[str, Sequence[float]],
        *,
        confidence: float = 0.99,
    ) -> Dict:
        if VaRCalculator is None:
            return {"error": "VaRCalculator unavailable"}

        calc = VaRCalculator()
        if not hasattr(calc, "contribution_var"):
            return {"error": "contribution_var not implemented on VaRCalculator"}

        result = calc.contribution_var(
            positions=positions,
            returns_by_symbol=returns_by_symbol,
            confidence=confidence,
        )  # type: ignore[attr-defined]

        contribs = result.get("component_var", {}) if isinstance(result, dict) else {}
        total = result.get("portfolio_var", 0.0) if isinstance(result, dict) else 0.0
        self._last_contributions = dict(contribs)
        self._last_total_var = float(total)

        ranked = sorted(contribs.items(), key=lambda kv: abs(kv[1]), reverse=True)
        return {
            "portfolio_var": total,
            "component_var": contribs,
            "marginal_var": result.get("marginal_var", {}) if isinstance(result, dict) else {},
            "ranked_contributions": [
                {"symbol": s, "component_var": v,
                 "pct_of_total": (v / total * 100.0) if total else 0.0}
                for s, v in ranked
            ],
            "confidence": confidence,
        }

    def last_snapshot(self) -> Dict:
        return {
            "portfolio_var": self._last_total_var,
            "component_var": dict(self._last_contributions),
        }
