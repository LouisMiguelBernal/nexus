"""
Nexus - Value-at-Risk (Leverage-Aware, Multi-Method)

Three independent VaR methods for crypto's fat-tailed regime. The *ensemble_max*
(= the most conservative of the three at each confidence level) is what the
Kelly sizer and circuit breaker should consume - a single-method VaR silently
under-states tail risk when the assumed distribution is wrong.

Methods
-------
1. **Historical simulation**: empirical percentile of realized returns. No
   distributional assumption. Weak when history is short or regime has shifted.

2. **Monte Carlo (Student-t)**: 500-path fat-tailed simulation. df=4 by default
   (empirically reasonable for crypto daily returns; higher df → thinner tails).
   Drift = sample mean, vol = EWMA σ (λ=0.94, RiskMetrics standard).

3. **Parametric Student-t**: analytic VaR from the t-distribution with fitted
   (μ, σ, df). Cheap, closed-form, useful for sanity-checking MC.

Component VaR (marginal contribution per position) is exposed via
`contribution_var()` for portfolio risk attribution (P2).

References
----------
- Jorion, P. (2006). "Value at Risk", 3rd ed. - historical + parametric.
- Glasserman, P. (2004). "Monte Carlo Methods in Financial Engineering".
- RiskMetrics Technical Document (1996) - EWMA σ, λ=0.94 daily.
- Embrechts/Klüppelberg/Mikosch (1997). "Modelling Extremal Events" - t-tails.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np

logger = logging.getLogger("nexus.var")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ewma_sigma(returns: np.ndarray, lam: float = 0.94) -> float:
    """EWMA volatility (RiskMetrics). Newest observation gets highest weight."""
    if returns.size == 0:
        return 0.0
    r2 = returns ** 2
    # Weights w_i = (1-lam) * lam^(n-1-i) for i=0..n-1  (oldest..newest)
    n = r2.size
    weights = (1.0 - lam) * lam ** np.arange(n - 1, -1, -1)
    # Renormalize to protect against truncation bias on short series.
    weights /= weights.sum()
    return float(np.sqrt(np.sum(weights * r2)))


def _fit_student_t_df(returns: np.ndarray, max_df: float = 30.0) -> float:
    """Lightweight df estimator from sample kurtosis.

    For Student-t with df > 4:  excess_kurt = 6 / (df - 4)  →  df = 6/k + 4.
    Falls back to df=4 (moderately fat) when the sample kurtosis is
    ill-conditioned or non-positive.
    """
    if returns.size < 20:
        return 4.0
    try:
        mu = float(returns.mean())
        centered = returns - mu
        var = float((centered ** 2).mean())
        if var <= 0:
            return 4.0
        m4 = float((centered ** 4).mean())
        excess_k = m4 / (var ** 2) - 3.0
        if excess_k <= 0:
            return max_df  # near-normal tails
        df_est = 6.0 / excess_k + 4.0
        return float(max(2.5, min(df_est, max_df)))
    except Exception:
        return 4.0


def _student_t_quantile(alpha: float, df: float) -> float:
    """Inverse CDF of Student-t at left-tail probability *alpha*.

    Pure-numpy fallback avoids a hard scipy dependency. When scipy is present
    we use it for accuracy; otherwise we use a cornish-fisher-style expansion.
    """
    try:
        from scipy.stats import t as _t  # type: ignore
        return float(_t.ppf(alpha, df))
    except Exception:
        # Cornish-Fisher expansion around normal quantile - adequate for
        # alpha in [0.005, 0.10] and df ≥ 3.
        # Normal inverse via rational approximation (Acklam).
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00]
        p = alpha
        if p <= 0:
            return -float("inf")
        if p >= 1:
            return float("inf")
        p_low = 0.02425
        p_high = 1 - p_low
        if p < p_low:
            q = math.sqrt(-2 * math.log(p))
            z = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        elif p <= p_high:
            q = p - 0.5
            r = q * q
            z = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
                (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
        else:
            q = math.sqrt(-2 * math.log(1 - p))
            z = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                 ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        # Kurtosis inflation to move normal quantile toward t_{df}.
        if df > 4:
            scale = math.sqrt(df / (df - 2))
            return z * scale
        return z * 1.15  # rough fat-tail bump when df is small


def _sample_student_t(df: float, size: int, rng: np.random.Generator) -> np.ndarray:
    """Sample from standard Student-t with *df* degrees of freedom."""
    # t = Z / sqrt(chi2/df), Z ~ N(0,1), chi2 ~ χ²_df
    z = rng.standard_normal(size)
    chi2 = rng.chisquare(df, size)
    return z / np.sqrt(chi2 / df)


# ---------------------------------------------------------------------------
# VaRCalculator
# ---------------------------------------------------------------------------

class VaRCalculator:
    """Leverage-aware multi-method VaR: historical + MC + parametric + ensemble."""

    def __init__(
        self,
        *,
        mc_paths: int = 500,
        mc_horizon_steps: int = 1,
        ewma_lambda: float = 0.94,
        seed: Optional[int] = None,
    ) -> None:
        self.mc_paths = int(mc_paths)
        self.mc_horizon_steps = int(mc_horizon_steps)
        self.ewma_lambda = float(ewma_lambda)
        self._rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    # Individual methods
    # ------------------------------------------------------------------

    def historical(
        self,
        returns: np.ndarray,
        confidence_levels: Sequence[float],
    ) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for cl in confidence_levels:
            pct = (1 - cl) * 100
            out[f"{int(cl*100)}"] = float(np.percentile(returns, pct))
        return out

    def parametric_t(
        self,
        returns: np.ndarray,
        confidence_levels: Sequence[float],
        df: Optional[float] = None,
    ) -> Dict[str, float]:
        if df is None:
            df = _fit_student_t_df(returns)
        mu = float(returns.mean())
        sigma = _ewma_sigma(returns, self.ewma_lambda)
        out: Dict[str, float] = {"_df": df, "_mu": mu, "_sigma": sigma}
        for cl in confidence_levels:
            alpha = 1.0 - cl
            q = _student_t_quantile(alpha, df)
            # Scale-shift: t quantile * σ + μ (standard parametric VaR).
            out[f"{int(cl*100)}"] = mu + sigma * q
        return out

    def monte_carlo(
        self,
        returns: np.ndarray,
        confidence_levels: Sequence[float],
        df: Optional[float] = None,
    ) -> Dict[str, float]:
        """Simulate *mc_paths* 1-step returns from Student-t(df, μ, σ_ewma)."""
        if df is None:
            df = _fit_student_t_df(returns)
        mu = float(returns.mean())
        sigma = _ewma_sigma(returns, self.ewma_lambda)

        if self.mc_horizon_steps <= 1:
            samples = _sample_student_t(df, self.mc_paths, self._rng) * sigma + mu
        else:
            # Multi-step cumulative return path - sum of iid t shocks.
            steps = _sample_student_t(df, self.mc_paths * self.mc_horizon_steps, self._rng)
            steps = steps.reshape(self.mc_paths, self.mc_horizon_steps) * sigma + mu
            samples = steps.sum(axis=1)

        out: Dict[str, float] = {
            "_df": df, "_mu": mu, "_sigma": sigma, "_n_paths": float(self.mc_paths),
        }
        for cl in confidence_levels:
            pct = (1 - cl) * 100
            out[f"{int(cl*100)}"] = float(np.percentile(samples, pct))
        return out

    # ------------------------------------------------------------------
    # Public composite
    # ------------------------------------------------------------------

    def compute(
        self,
        returns: List[float],
        position_usd: float,
        leverage: float = 1.0,
        confidence_levels: Sequence[float] = (0.95, 0.99),
    ) -> Dict:
        """Compute VaR via three methods + ensemble.

        Returns a dict with top-level *historical*, *monte_carlo*, *parametric*,
        and *ensemble_max* sub-dicts. Each reports {return_pct, usd_loss,
        unleveraged_pct, confidence} per confidence level. *ensemble_max* picks
        the worst (most negative) per-level loss across methods - the number
        the position sizer should consume.
        """
        if len(returns) < 30:
            return {
                "error": "Insufficient data (need 30+ returns)",
                "historical": {}, "monte_carlo": {}, "parametric": {}, "ensemble_max": {},
            }

        returns_arr = np.asarray(returns, dtype=float)

        hist = self.historical(returns_arr, confidence_levels)
        mc = self.monte_carlo(returns_arr, confidence_levels)
        para = self.parametric_t(returns_arr, confidence_levels)

        def _pack(raw: Dict[str, float]) -> Dict:
            packed: Dict[str, Dict] = {}
            for cl in confidence_levels:
                key = f"{int(cl*100)}"
                var_unlev = raw.get(key)
                if var_unlev is None:
                    continue
                var_lev = var_unlev * leverage
                packed[f"var_{key}"] = {
                    "return_pct": round(var_lev * 100, 4),
                    "usd_loss": round(abs(var_lev) * position_usd, 2),
                    "unleveraged_pct": round(var_unlev * 100, 4),
                    "confidence": cl,
                }
            for meta_key in ("_df", "_mu", "_sigma", "_n_paths"):
                if meta_key in raw:
                    packed[meta_key.lstrip("_")] = round(float(raw[meta_key]), 6)
            return packed

        hist_packed = _pack(hist)
        mc_packed = _pack(mc)
        para_packed = _pack(para)

        # Ensemble: take the most negative (worst loss) per confidence level.
        ensemble: Dict[str, Dict] = {}
        for cl in confidence_levels:
            key = f"var_{int(cl*100)}"
            candidates = [
                (hist.get(f"{int(cl*100)}"), "historical"),
                (mc.get(f"{int(cl*100)}"), "monte_carlo"),
                (para.get(f"{int(cl*100)}"), "parametric"),
            ]
            candidates = [(v, name) for v, name in candidates if v is not None]
            if not candidates:
                continue
            worst_val, worst_name = min(candidates, key=lambda x: x[0])
            worst_lev = worst_val * leverage
            ensemble[key] = {
                "return_pct": round(worst_lev * 100, 4),
                "usd_loss": round(abs(worst_lev) * position_usd, 2),
                "unleveraged_pct": round(worst_val * 100, 4),
                "confidence": cl,
                "source_method": worst_name,
            }

        # Stressed VaR: mean of worst 5 % of empirical returns.
        worst_5 = returns_arr[returns_arr <= np.percentile(returns_arr, 5)]
        stressed = None
        if worst_5.size > 0:
            sv = float(worst_5.mean()) * leverage
            stressed = {
                "return_pct": round(sv * 100, 4),
                "usd_loss": round(abs(sv) * position_usd, 2),
            }

        # Liquidation VaR - probability of hitting maintenance margin in 1 step.
        liq_threshold = -1.0 / max(leverage, 1.0)
        prob_liq = float(np.mean(returns_arr * leverage <= liq_threshold))

        return {
            "historical": hist_packed,
            "monte_carlo": mc_packed,
            "parametric": para_packed,
            "ensemble_max": ensemble,
            "stressed_var": stressed,
            "liquidation_risk": {
                "probability_horizon": round(prob_liq * 100, 4),
                "threshold_pct": round(liq_threshold * 100, 4),
                "leverage": leverage,
            },
            "inputs": {
                "n_returns": int(returns_arr.size),
                "mc_paths": self.mc_paths,
                "ewma_lambda": self.ewma_lambda,
            },
        }

    # ------------------------------------------------------------------
    # Component / marginal VaR for attribution (P2)
    # ------------------------------------------------------------------

    def contribution_var(
        self,
        positions: Mapping[str, float],
        returns_by_symbol: Mapping[str, Iterable[float]],
        confidence: float = 0.95,
        leverage: float = 1.0,
    ) -> Dict:
        """Return marginal + component VaR per symbol (Euler allocation).

        marginal_i = ∂VaR_p / ∂w_i      (sensitivity of portfolio VaR to weight_i)
        component_i = w_i · marginal_i  (sums across i to total VaR_p)

        Method
        ------
        Build aligned return matrix R (T × N), w = weights from *positions*
        normalized to sum to 1 (or to total notional). Portfolio returns
        r_p = R @ w. σ_p = std(r_p). For each i compute ρ(R_i, r_p). Under
        the Gaussian approximation: marginal_i ≈ z_α · σ_i · ρ_i,p where
        z_α is the normal quantile. Fine as an attribution view - the
        headline VaR should still come from `compute()`.
        """
        symbols = [s for s, w in positions.items() if abs(w) > 0]
        if len(symbols) < 1:
            return {"error": "No non-zero positions"}

        aligned: List[np.ndarray] = []
        keep_symbols: List[str] = []
        min_len = None
        for s in symbols:
            r = np.asarray(list(returns_by_symbol.get(s, []) or []), dtype=float)
            if r.size < 30:
                continue
            aligned.append(r)
            keep_symbols.append(s)
            min_len = r.size if min_len is None else min(min_len, r.size)

        if not aligned or min_len is None or min_len < 30:
            return {"error": "Insufficient per-symbol return history (need 30+ each)"}

        R = np.vstack([a[-min_len:] for a in aligned])  # N × T
        w = np.array([positions[s] for s in keep_symbols], dtype=float)
        gross = float(np.sum(np.abs(w)))
        if gross <= 0:
            return {"error": "Zero gross exposure"}
        w_norm = w / gross  # dollar weights, signed

        r_p = w_norm @ R  # portfolio return series, length T
        sigma_p = float(np.std(r_p, ddof=1))
        if sigma_p <= 0:
            return {"error": "Zero portfolio variance"}

        # Normal VaR quantile (positive number): |z_α| · σ_p
        z_alpha = abs(_student_t_quantile(1 - confidence, 30.0))  # ~normal
        var_p = z_alpha * sigma_p * leverage

        contributions: Dict[str, Dict] = {}
        for i, s in enumerate(keep_symbols):
            sigma_i = float(np.std(R[i], ddof=1))
            rho_i = float(np.corrcoef(R[i], r_p)[0, 1]) if sigma_i > 0 else 0.0
            marginal = z_alpha * sigma_i * rho_i * leverage
            component = w_norm[i] * marginal * gross  # in dollar-weight units
            contributions[s] = {
                "weight": round(float(w_norm[i]), 6),
                "sigma": round(sigma_i, 6),
                "corr_with_portfolio": round(rho_i, 4),
                "marginal_var_pct": round(marginal * 100, 4),
                "component_var_usd": round(component, 2),
            }

        return {
            "portfolio_var_pct": round(var_p * 100, 4),
            "portfolio_sigma": round(sigma_p, 6),
            "confidence": confidence,
            "leverage": leverage,
            "contributions": contributions,
        }
