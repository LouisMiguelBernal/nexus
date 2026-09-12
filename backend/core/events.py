"""Typed events and topic names.

The bus carries any payload; these are the shapes the execution engine,
the archive tap and the streaming layer agree on. Frozen and slotted: an
event is a fact, not a mutable record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Side = Literal["buy", "sell"]


class Topic:
    """Bus topic names. Producers and subscribers reference these, never strings."""

    VAR_BREACH = "var.breach"
    CORRELATION_SNAPSHOT = "correlation.snapshot"
    WS_GAP = "ws.gap"
    FUNDING_ZSCORE = "funding.zscore"
    VPIN_UPDATE = "vpin.update"
    BREAKER_STATE = "breaker.state"
    ALERT = "alert"
    MARKET_TRADE = "market.trade"  # + ".{symbol}"
    MARKET_BOOK = "market.book"
    MARKET_KLINE = "market.kline"
    MARKET_FUNDING = "market.funding"
    MARKET_OI = "market.oi"
    MARKET_LIQUIDATION = "market.liquidation"
    ORDER_UPDATE = "order.update"
    ORDER_FILL = "order.fill"
    SERVICE_STATE = "service.state"


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    price: float
    qty: float
    side: Side
    ts: float
    venue: str = "binance"


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    symbol: str
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    ts: float
    venue: str = "binance"


@dataclass(frozen=True, slots=True)
class Kline:
    symbol: str
    interval: str
    open_time: int  # ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    close_time: int  # ms
    is_closed: bool
    venue: str = "binance"


@dataclass(frozen=True, slots=True)
class FundingTick:
    symbol: str
    venue: str
    rate: float
    ts: float
    next_funding_ts: float | None = None


@dataclass(frozen=True, slots=True)
class OIUpdate:
    symbol: str
    venue: str
    open_interest: float
    open_interest_notional: float | None
    ts: float


@dataclass(frozen=True, slots=True)
class Liquidation:
    symbol: str
    venue: str
    side: Side  # side of the forced order: "sell" = long liquidated
    price: float
    qty: float
    usd_value: float
    ts: float


@dataclass(frozen=True, slots=True)
class OrderUpdate:
    client_order_id: str
    symbol: str
    status: str
    ts: float
    venue_order_id: str | None = None
    filled_qty: float = 0.0
    avg_price: float | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    client_order_id: str
    symbol: str
    side: Side
    price: float
    qty: float
    fee: float
    fee_ccy: str
    liquidity: Literal["maker", "taker", "unknown"]
    ts: float


@dataclass(frozen=True, slots=True)
class BreakerState:
    triggered: bool
    signals_suppressed: bool
    leverage_reduced: bool
    reason: str
    ts: float


@dataclass(frozen=True, slots=True)
class Alert:
    kind: str
    symbol: str
    message: str
    ts: float
    payload: dict[str, Any] = field(default_factory=dict)


def to_dict(event: Any) -> dict[str, Any]:
    """Serialise any event dataclass for the bus / JSON."""
    return asdict(event)
