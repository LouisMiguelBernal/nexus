"""
Nexus - Deflated Sharpe Ratio (DSR)

Reference
---------
Bailey, D., López de Prado, M. (2014).
"The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
 Overfitting and Non-Normality". Journal of Portfolio Management 40(5).

Intuition
---------
With `N` trials (grid points tried during research), the *expected*
maximum Sharpe under the null (zero edge) is materially > 0. DSR
subtracts that expectation - the surviving credibility is what matters.

    E[max SR | N, Var(SR)]
      = sqrt(V) · [(1 - γ) · Φ⁻¹(1 - 1/N) + γ · Φ⁻¹(1 - 1/(N·e))]
      γ = Euler-Mascheroni ≈ 0.5772156649

    DSR = Φ( (SR_obs - E[max SR]) · sqrt(T - 1) /
             sqrt(1 - skew · SR_obs + ((kurt - 1) / 4) · SR_obs²) )

`Φ` is the standard normal CDF; `T` the backtest sample length. DSR ∈
[0, 1]; treat > 0.95 as statistically "real", the plan's success target
is > 0.70.
"""

from __future__ import annotations

import math
from typing import Dict, Sequence


_EULER = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF via Acklam's rational approximation."""
    if not (0.0 < p < 1.0):
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def _moments(returns: Sequence[float]) -> Dict[str, float]:
    n = len(returns)
    if n < 4:
        return {"mean": 0.0, "std": 0.0, "skew": 0.0, "kurt": 3.0, "n": n}
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m3 = sum((r - mean) ** 3 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    std = math.sqrt(m2) if m2 > 0 else 0.0
    skew = m3 / (std ** 3) if std > 0 else 0.0
    kurt = m4 / (m2 ** 2) if m2 > 0 else 3.0
    return {"mean": mean, "std": std, "skew": skew, "kurt": kurt, "n": n}


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Closed-form expected max Sharpe under the null, per Bailey & LdP 2014."""
    if n_trials < 2 or sharpe_variance <= 0:
        return 0.0
    p1 = 1 - 1.0 / n_trials
    p2 = 1 - 1.0 / (n_trials * math.e)
    z1 = _norm_ppf(min(max(p1, 1e-9), 1 - 1e-9))
    z2 = _norm_ppf(min(max(p2, 1e-9), 1 - 1e-9))
    return math.sqrt(sharpe_variance) * ((1 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe(
    returns: Sequence[float],
    *,
    n_trials: int = 1,
    sharpe_variance: float = 0.5,
    annualization: float = math.sqrt(365),
) -> Dict[str, float]:
    """Compute DSR for a single OOS return stream.

    Parameters
    ----------
    returns
        Per-bar returns (daily convention by default).
    n_trials
        Number of strategies/grid points tried during research. Larger N
        ⇒ harsher deflation.
    sharpe_variance
        Cross-trial variance of Sharpe under the null. Default 0.5 (a
        common conservative prior in the literature).
    annualization
        Scale factor to convert bar-Sharpe to annualized; default assumes
        daily bars.
    """
    m = _moments(returns)
    if m["n"] < 10 or m["std"] <= 1e-12:
        return {
            "sharpe": 0.0,
            "deflated_sharpe": 0.0,
            "expected_max_sharpe": 0.0,
            "p_value_nonrandom": 0.0,
            "n": m["n"],
            "reason": "insufficient samples or flat return series",
        }

    sr_bar = m["mean"] / m["std"]             # per-bar Sharpe
    sr_annual = sr_bar * annualization
    exp_max = expected_max_sharpe(n_trials, sharpe_variance)

    t = m["n"]
    skew = m["skew"]
    kurt = m["kurt"]
    denom_sq = 1.0 - skew * sr_bar + ((kurt - 1.0) / 4.0) * (sr_bar ** 2)
    denom = math.sqrt(denom_sq) if denom_sq > 0 else 1.0
    z = (sr_bar - exp_max) * math.sqrt(t - 1) / denom
    dsr = _norm_cdf(z)

    return {
        "sharpe_per_bar": round(sr_bar, 6),
        "sharpe_annualized": round(sr_annual, 4),
        "expected_max_sharpe": round(exp_max, 6),
        "deflated_sharpe": round(dsr, 4),
        "p_value_nonrandom": round(dsr, 4),
        "skew": round(skew, 4),
        "excess_kurtosis": round(kurt - 3.0, 4),
        "n": t,
        "n_trials": n_trials,
    }
