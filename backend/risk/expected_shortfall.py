"""
Nexus - Expected Shortfall (Conditional VaR)

ES_α = E[ L | L ≥ VaR_α ]

Three matched methods to mirror VaRCalculator's API. ES is the more coherent
tail-risk measure (sub-additive); the institutional convention is to surface
both VaR and ES side by side. Used in the Risk panel under VaR.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np

from backend.risk.var import (
    _ewma_sigma,
    _fit_student_t_df,
    _sample_student_t,
    _student_t_quantile,
)


class ESCalculator:
    """Multi-method Expected Shortfall."""

    def __init__(
        self,
        *,
        mc_paths: int = 500,
        ewma_lambda: float = 0.94,
        seed: Optional[int] = None,
    ) -> None:
        self.mc_paths = int(mc_paths)
        self.ewma_lambda = float(ewma_lambda)
        self._rng = np.random.default_rng(seed)

    def historical(self, returns: np.ndarray, cls: Sequence[float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for cl in cls:
            pct = (1 - cl) * 100
            cutoff = float(np.percentile(returns, pct))
            tail = returns[returns <= cutoff]
            out[f"{int(cl*100)}"] = float(tail.mean()) if tail.size else cutoff
        return out

    def parametric_t(
        self,
        returns: np.ndarray,
        cls: Sequence[float],
        df: Optional[float] = None,
    ) -> Dict[str, float]:
        # Closed-form ES for Student-t:
        #   ES_α = -μ + σ · ( f(t_α) / (1-α) ) · ( (df + t_α²) / (df - 1) )
        # where t_α = quantile of standardized t at alpha=1-cl, and f is the
        # standard t pdf at t_α. We avoid scipy: use the t pdf formula.
        if df is None:
            df = _fit_student_t_df(returns)
        mu = float(returns.mean())
        sigma = _ewma_sigma(returns, self.ewma_lambda)
        out: Dict[str, float] = {"_df": df, "_mu": mu, "_sigma": sigma}
        for cl in cls:
            alpha = 1.0 - cl
            t_a = _student_t_quantile(alpha, df)
            # Student-t pdf at t_a (normalising constant via lgamma).
            from math import lgamma, log, exp, pi, sqrt
            log_const = (
                lgamma((df + 1) / 2)
                - lgamma(df / 2)
                - 0.5 * log(df * pi)
            )
            log_kernel = -((df + 1) / 2) * log(1 + (t_a * t_a) / df)
            f_t = exp(log_const + log_kernel)
            # ES expressed as a *return* (negative number for losses).
            es = mu - sigma * (f_t / max(alpha, 1e-9)) * ((df + t_a * t_a) / max(df - 1, 1e-6))
            out[f"{int(cl*100)}"] = float(es)
        return out

    def monte_carlo(
        self,
        returns: np.ndarray,
        cls: Sequence[float],
        df: Optional[float] = None,
    ) -> Dict[str, float]:
        if df is None:
            df = _fit_student_t_df(returns)
        mu = float(returns.mean())
        sigma = _ewma_sigma(returns, self.ewma_lambda)
        samples = _sample_student_t(df, self.mc_paths, self._rng) * sigma + mu
        out: Dict[str, float] = {"_df": df, "_mu": mu, "_sigma": sigma}
        for cl in cls:
            pct = (1 - cl) * 100
            cutoff = float(np.percentile(samples, pct))
            tail = samples[samples <= cutoff]
            out[f"{int(cl*100)}"] = float(tail.mean()) if tail.size else cutoff
        return out

    def compute(
        self,
        returns: List[float],
        position_usd: float,
        leverage: float = 1.0,
        confidence_levels: Sequence[float] = (0.95, 0.99),
    ) -> Dict:
        if len(returns) < 30:
            return {"error": "Insufficient data (need 30+ returns)", "ensemble_max": {}}

        arr = np.asarray(returns, dtype=float)
        hist = self.historical(arr, confidence_levels)
        mc = self.monte_carlo(arr, confidence_levels)
        para = self.parametric_t(arr, confidence_levels)

        def _pack(raw: Dict[str, float]) -> Dict:
            packed: Dict[str, Dict] = {}
            for cl in confidence_levels:
                key = f"{int(cl*100)}"
                v = raw.get(key)
                if v is None:
                    continue
                v_lev = v * leverage
                packed[f"es_{key}"] = {
                    "return_pct": round(v_lev * 100, 4),
                    "usd_loss": round(abs(v_lev) * position_usd, 2),
                    "unleveraged_pct": round(v * 100, 4),
                    "confidence": cl,
                }
            return packed

        ensemble: Dict[str, Dict] = {}
        for cl in confidence_levels:
            key = f"{int(cl*100)}"
            cands = [
                (hist.get(key), "historical"),
                (mc.get(key), "monte_carlo"),
                (para.get(key), "parametric"),
            ]
            cands = [(v, n) for v, n in cands if v is not None]
            if not cands:
                continue
            worst, name = min(cands, key=lambda x: x[0])
            ensemble[f"es_{key}"] = {
                "return_pct": round(worst * leverage * 100, 4),
                "usd_loss": round(abs(worst) * leverage * position_usd, 2),
                "unleveraged_pct": round(worst * 100, 4),
                "confidence": cl,
                "source_method": name,
            }

        return {
            "historical": _pack(hist),
            "monte_carlo": _pack(mc),
            "parametric": _pack(para),
            "ensemble_max": ensemble,
            "inputs": {"n_returns": int(arr.size), "mc_paths": self.mc_paths},
        }
