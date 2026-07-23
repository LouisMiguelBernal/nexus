"""
Nexus - Kelly Criterion Position Sizer (Leverage + Volatility + Correlation Adjusted)

Standard Kelly:      f = (p * b - q) / b
Half Kelly:          f / 2 (always applied for leveraged crypto - Thorp 2006)
Vol-adjusted b:      b = expected_R / max(atr_pct, realized_vol_24h)
                     (same nominal R:R represents more Kelly fraction in low-vol
                      regimes, less in high-vol. Auto-scales with microstructure.)
Correlation filter:  f_final = f * (1 - max(|ρ_ij|))
                     (a position highly correlated with existing books is fractional
                      to the portfolio, so Kelly shrinks accordingly.)

Max position = 2 % of FREE COLLATERAL, not total account.

References
----------
- Thorp, E. (2006). "The Kelly Capital Growth Investment Criterion"
- Grinold & Kahn (2000). "Active Portfolio Management" - risk-adjusted sizing
- Markowitz portfolio theory - diversification penalty on correlated bets
"""

import logging
from typing import Dict, List, Mapping, Optional

from backend.config import KELLY_CONFIG

logger = logging.getLogger("nexus.kelly")


def _max_abs_correlation(
    symbol: str,
    open_positions: Optional[List[str]],
    correlations: Optional[Mapping[str, float]],
) -> float:
    """Return max |ρ| between *symbol* and each symbol in *open_positions*.

    *correlations* is a flat dict keyed by either "SYMA/SYMB" or "SYMB/SYMA"
    (output of compute_correlation_matrix().pairs). Missing pairs are treated
    as zero correlation - conservative against unknown data only when there
    really is no history, not when correlation is just high.
    """
    if not open_positions or not correlations:
        return 0.0

    sym = symbol.upper()
    worst = 0.0
    for other in open_positions:
        o = str(other).upper()
        if o == sym:
            continue
        rho = correlations.get(f"{sym}/{o}")
        if rho is None:
            rho = correlations.get(f"{o}/{sym}")
        if rho is None:
            continue
        try:
            worst = max(worst, abs(float(rho)))
        except (TypeError, ValueError):
            continue
    # Clamp - any numeric spoofing can't push the multiplier negative.
    return min(max(worst, 0.0), 1.0)


class KellySizer:
    """Leverage-, volatility-, and correlation-adjusted Kelly position sizing."""

    def __init__(self):
        self.max_position_pct = KELLY_CONFIG["max_position_pct"]
        self.use_half_kelly = KELLY_CONFIG["use_half_kelly"]
        self.max_leverage = KELLY_CONFIG["max_leverage_suggested"]
        self.margin_buffer = KELLY_CONFIG["margin_buffer_required"]
        self.scale_by_confidence = KELLY_CONFIG["kelly_scale_by_confidence"]

    def compute(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        leverage: int,
        total_collateral: float,
        allocated_margin: float,
        zone_tier_weight: float = 1.0,
        *,
        # Optional vol / correlation inputs (P0-2). When absent we degrade to
        # classic Kelly so existing callers keep working.
        symbol: Optional[str] = None,
        atr_pct: Optional[float] = None,
        realized_vol_24h: Optional[float] = None,
        correlations: Optional[Mapping[str, float]] = None,
        open_positions: Optional[List[str]] = None,
    ) -> Dict:
        """Compute Kelly-optimal position size.

        Parameters
        ----------
        win_rate : Historical win probability (0-1)
        avg_win  : Average winning trade return (ratio, e.g. 0.03 = 3 %)
        avg_loss : Average losing trade return (ratio, positive, e.g. 0.02 = 2 %)
        leverage : Intended leverage for this trade
        total_collateral : Total account collateral in USD
        allocated_margin : USD already allocated to open positions
        zone_tier_weight : Golden-zone tier weight (0.3 - 1.5) for confidence scaling
        symbol           : Optional - used for correlation lookup
        atr_pct          : 1-h ATR as % of price (e.g. 0.015 for 1.5 %)
        realized_vol_24h : 24-h realized vol as ratio (e.g. 0.04 for 4 %)
        correlations     : Flat pair dict, e.g. {"BTCUSDT/ETHUSDT": 0.92}
        open_positions   : Symbols already in book
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return {"position_usd": 0, "reason": "Invalid inputs", "kelly_raw": 0}

        p = win_rate
        q = 1 - p

        # --- Vol-adjusted win/loss ratio (P0-2) ----------------------------
        # Use the larger of 1-h ATR or 24-h realized vol as the risk yardstick.
        # Falls back to the supplied avg_loss when neither is provided - this
        # preserves backward compatibility for callers that don't yet pass vol.
        vol_ref = 0.0
        if atr_pct is not None and atr_pct > 0:
            vol_ref = max(vol_ref, float(atr_pct))
        if realized_vol_24h is not None and realized_vol_24h > 0:
            vol_ref = max(vol_ref, float(realized_vol_24h))

        if vol_ref > 0:
            # expected_R proxy: use avg_win (our target reward-to-move) over
            # the realized risk yardstick. Larger vol_ref => smaller b => lower
            # Kelly fraction, same as an institutional vol-targeting sizer.
            b = avg_win / vol_ref
            b_source = "vol_adjusted"
        else:
            b = avg_win / avg_loss  # Classical Kelly
            b_source = "static_avg_loss"

        if b <= 0:
            return {
                "position_usd": 0,
                "reason": "Non-positive risk-reward ratio",
                "kelly_raw": 0,
                "b_source": b_source,
            }

        # Raw Kelly fraction
        kelly_raw = (p * b - q) / b

        if kelly_raw <= 0:
            return {
                "position_usd": 0,
                "reason": "Negative edge - no trade",
                "kelly_raw": round(kelly_raw, 6),
                "kelly_final": 0,
                "b_source": b_source,
            }

        # Half Kelly (always for leveraged crypto)
        kelly = kelly_raw / 2 if self.use_half_kelly else kelly_raw

        # Scale by zone confidence
        if self.scale_by_confidence:
            kelly *= zone_tier_weight

        # --- Correlation filter (P0-2) -------------------------------------
        # Reduce Kelly fraction by max pairwise correlation with open book.
        # ρ=1 → zero incremental Kelly (pure redundancy). ρ=0 → unchanged.
        max_rho = _max_abs_correlation(
            symbol=symbol or "",
            open_positions=open_positions,
            correlations=correlations,
        )
        correlation_multiplier = max(0.0, 1.0 - max_rho)
        kelly_after_corr = kelly * correlation_multiplier

        # Free collateral (must keep margin buffer)
        free_collateral = total_collateral - allocated_margin
        usable_collateral = free_collateral * (1 - self.margin_buffer)

        if usable_collateral <= 0:
            return {
                "position_usd": 0,
                "reason": f"Insufficient free margin (buffer: {self.margin_buffer*100}%)",
                "kelly_raw": round(kelly_raw, 6),
                "kelly_final": round(kelly_after_corr, 6),
                "b_source": b_source,
                "max_abs_correlation": round(max_rho, 4),
                "correlation_multiplier": round(correlation_multiplier, 4),
            }

        # Position as % of usable collateral (cap by max_position_pct guardrail)
        position_pct = min(kelly_after_corr, self.max_position_pct)
        position_margin = usable_collateral * position_pct

        # Notional with leverage
        capped_leverage = min(leverage, self.max_leverage)
        position_notional = position_margin * capped_leverage

        return {
            "kelly_raw": round(kelly_raw, 6),
            "kelly_half": round(kelly_raw / 2, 6),
            "kelly_pre_correlation": round(kelly, 6),
            "kelly_final": round(position_pct, 6),
            "position_margin_usd": round(position_margin, 2),
            "position_notional_usd": round(position_notional, 2),
            "position_pct_of_collateral": round(position_pct * 100, 4),
            "leverage_used": capped_leverage,
            "leverage_capped": leverage > self.max_leverage,
            "free_collateral": round(free_collateral, 2),
            "usable_collateral": round(usable_collateral, 2),
            "zone_tier_weight": zone_tier_weight,
            "b": round(b, 6),
            "b_source": b_source,
            "vol_ref": round(vol_ref, 6) if vol_ref > 0 else None,
            "max_abs_correlation": round(max_rho, 4),
            "correlation_multiplier": round(correlation_multiplier, 4),
            "reason": "OK",
        }
