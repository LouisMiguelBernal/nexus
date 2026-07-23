"""
Nexus -- Smart Money Flow Detection
Institutional-grade detection of whale activity, iceberg orders,
accumulation/distribution phases, and large trade clustering.
"""

import logging
import math
import statistics
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nexus.smart_money")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Trades above this USD percentile are considered "large"
LARGE_TRADE_PERCENTILE = 0.95

# For iceberg detection: max deviation in quantity between fills
ICEBERG_QTY_TOLERANCE = 0.05  # 5% tolerance on repeated sizes

# Minimum number of same-size fills to flag as iceberg
ICEBERG_MIN_FILLS = 4

# Time window for clustering (milliseconds)
CLUSTER_WINDOW_MS = 30_000  # 30 seconds

# Minimum USD value to qualify as whale trade
WHALE_THRESHOLD_USD = 50_000


# ---------------------------------------------------------------------------
# SmartMoneyTracker
# ---------------------------------------------------------------------------

class SmartMoneyTracker:
    """
    Detects institutional smart money patterns from aggregated trade flow:
    - Iceberg orders (repeated same-size fills)
    - Accumulation / distribution phases
    - Whale activity summary
    - Large trade flow with direction
    """

    def __init__(self, symbol: str = "BTCUSDT", whale_threshold_usd: float = WHALE_THRESHOLD_USD):
        self.symbol = symbol.upper()

        # All processed trades (rolling window)
        self._trades: deque[dict] = deque(maxlen=50_000)

        # Large trades only
        self.large_orders: deque[dict] = deque(maxlen=1000)

        # Detected clusters and icebergs
        self.trade_clusters: list[dict] = []
        self.iceberg_candidates: list[dict] = []

        # Running statistics for adaptive thresholds
        self._usd_values: deque[float] = deque(maxlen=10_000)
        self._large_threshold: float = whale_threshold_usd
        self._whale_threshold_usd = whale_threshold_usd

        # Accumulation / distribution state
        self._phase_window: deque[dict] = deque(maxlen=5000)

        logger.info(
            "SmartMoneyTracker initialised for %s (whale_threshold=$%s)",
            self.symbol, f"{whale_threshold_usd:,.0f}",
        )

    # ------------------------------------------------------------------
    # Trade ingestion
    # ------------------------------------------------------------------

    def process_trade(
        self,
        price: float,
        qty: float,
        is_buyer_maker: bool,
        timestamp: float,
    ) -> None:
        """
        Process each aggTrade to detect smart money patterns.

        Parameters
        ----------
        price : trade price
        qty : trade quantity (base asset)
        is_buyer_maker : True means taker sold (sell aggressor)
        timestamp : epoch milliseconds
        """
        if price <= 0 or qty <= 0:
            return

        usd_value = price * qty
        trade = {
            "price": price,
            "qty": qty,
            "usd": usd_value,
            "side": "sell" if is_buyer_maker else "buy",
            "is_buyer_maker": is_buyer_maker,
            "ts": timestamp,
        }

        self._trades.append(trade)
        self._usd_values.append(usd_value)

        # Update adaptive large threshold periodically
        if len(self._usd_values) >= 100 and len(self._usd_values) % 100 == 0:
            self._update_threshold()

        # Track large orders
        if usd_value >= self._large_threshold:
            self.large_orders.append(trade)

    def _update_threshold(self) -> None:
        """Recalculate the large trade threshold from recent trade distribution."""
        values = sorted(self._usd_values)
        idx = int(len(values) * LARGE_TRADE_PERCENTILE)
        adaptive = values[min(idx, len(values) - 1)]
        # Use the higher of adaptive and fixed minimum
        self._large_threshold = max(adaptive, self._whale_threshold_usd)

    # ------------------------------------------------------------------
    # Iceberg detection
    # ------------------------------------------------------------------

    def detect_iceberg_orders(self) -> list[dict]:
        """
        Detect hidden iceberg orders from repeated same-size fills.

        Icebergs show as many consecutive fills at very similar quantities,
        often at the same or very close price level, because the exchange
        is slicing a large hidden order into uniform child orders.

        Returns
        -------
        list of dicts:
            qty_pattern    : float  -- the repeated quantity
            fill_count     : int
            side           : "buy" | "sell"
            price_range    : [min, max]
            total_usd      : float
            duration_ms    : float
            confidence     : float  -- 0-1
            timestamp_start: float
            timestamp_end  : float
        """
        if len(self._trades) < ICEBERG_MIN_FILLS * 2:
            return []

        candidates: list[dict] = []
        trades_list = list(self._trades)

        # Group trades by approximate quantity using a bucketing approach
        # Key: (rounded_qty, side) -> list of trades
        qty_buckets: Dict[Tuple[int, str], list[dict]] = defaultdict(list)

        for t in trades_list:
            # Round qty to reduce floating point noise
            # Use 3 significant figures for bucketing
            if t["qty"] > 0:
                magnitude = 10 ** (math.floor(math.log10(t["qty"])) - 2)
                bucket_qty = round(t["qty"] / magnitude) * magnitude
                key = (int(bucket_qty * 1e8), t["side"])  # int key for hashing
                qty_buckets[key].append(t)

        for (bucket_key, side), fills in qty_buckets.items():
            if len(fills) < ICEBERG_MIN_FILLS:
                continue

            # Check if fills are clustered in time (within reasonable windows)
            fills_sorted = sorted(fills, key=lambda f: f["ts"])

            # Sliding window to find time-clustered groups
            i = 0
            while i < len(fills_sorted):
                cluster: list[dict] = [fills_sorted[i]]
                j = i + 1
                while j < len(fills_sorted):
                    gap = fills_sorted[j]["ts"] - fills_sorted[j - 1]["ts"]
                    if gap < 60_000:  # fills within 60s of each other
                        cluster.append(fills_sorted[j])
                        j += 1
                    else:
                        break

                if len(cluster) >= ICEBERG_MIN_FILLS:
                    # Verify quantity consistency
                    qtys = [f["qty"] for f in cluster]
                    avg_qty = statistics.mean(qtys)
                    if avg_qty > 0:
                        max_dev = max(abs(q - avg_qty) / avg_qty for q in qtys)
                        if max_dev <= ICEBERG_QTY_TOLERANCE:
                            prices = [f["price"] for f in cluster]
                            total_usd = sum(f["usd"] for f in cluster)
                            duration = cluster[-1]["ts"] - cluster[0]["ts"]

                            # Confidence based on fill count, consistency, and size
                            conf = min(
                                0.3 + 0.1 * len(cluster)
                                + 0.3 * (1.0 - max_dev / ICEBERG_QTY_TOLERANCE)
                                + 0.2 * min(total_usd / 100_000, 1.0),
                                1.0,
                            )

                            candidates.append({
                                "qty_pattern": round(avg_qty, 6),
                                "fill_count": len(cluster),
                                "side": side,
                                "price_range": [min(prices), max(prices)],
                                "total_usd": round(total_usd, 2),
                                "duration_ms": duration,
                                "confidence": round(conf, 3),
                                "timestamp_start": cluster[0]["ts"],
                                "timestamp_end": cluster[-1]["ts"],
                            })

                i = j

        candidates.sort(key=lambda c: c["total_usd"], reverse=True)
        self.iceberg_candidates = candidates[:50]  # keep top 50
        return self.iceberg_candidates

    # ------------------------------------------------------------------
    # Accumulation / Distribution
    # ------------------------------------------------------------------

    def detect_accumulation_distribution(self) -> dict:
        """
        Detect institutional accumulation (buying) or distribution (selling) phases.

        Uses multiple heuristics:
        - Large trade directional bias over time
        - Price behaviour relative to large-trade flow
        - Volume profile (increasing large-order activity)

        Returns
        -------
        dict:
            phase         : "accumulation" | "distribution" | "neutral"
            bias          : float  -- -1 (distribution) to +1 (accumulation)
            large_buy_usd : float
            large_sell_usd: float
            net_flow      : float
            price_trend   : "up" | "down" | "flat"
            divergence    : bool  -- price vs flow divergence
            confidence    : float
            window_minutes: float
        """
        if len(self.large_orders) < 5:
            return {
                "phase": "neutral",
                "bias": 0.0,
                "large_buy_usd": 0.0,
                "large_sell_usd": 0.0,
                "net_flow": 0.0,
                "price_trend": "flat",
                "divergence": False,
                "confidence": 0.0,
                "window_minutes": 0,
            }

        orders = list(self.large_orders)

        # Split into time halves for trend detection
        mid = len(orders) // 2
        first_half = orders[:mid]
        second_half = orders[mid:]

        def _calc_flow(trades: list[dict]) -> Tuple[float, float]:
            buy = sum(t["usd"] for t in trades if t["side"] == "buy")
            sell = sum(t["usd"] for t in trades if t["side"] == "sell")
            return buy, sell

        buy_1, sell_1 = _calc_flow(first_half)
        buy_2, sell_2 = _calc_flow(second_half)

        total_buy = buy_1 + buy_2
        total_sell = sell_1 + sell_2
        net_flow = total_buy - total_sell
        total_flow = total_buy + total_sell

        if total_flow < 1e-9:
            bias = 0.0
        else:
            bias = net_flow / total_flow  # [-1, 1]

        # Price trend
        first_prices = [t["price"] for t in first_half] if first_half else [0]
        second_prices = [t["price"] for t in second_half] if second_half else [0]
        avg_first = statistics.mean(first_prices)
        avg_second = statistics.mean(second_prices)

        if avg_first > 0:
            price_change_pct = (avg_second - avg_first) / avg_first * 100
        else:
            price_change_pct = 0.0

        if price_change_pct > 0.1:
            price_trend = "up"
        elif price_change_pct < -0.1:
            price_trend = "down"
        else:
            price_trend = "flat"

        # Divergence: smart money buying while price drops (accumulation)
        # or selling while price rises (distribution)
        divergence = False
        if bias > 0.15 and price_trend == "down":
            divergence = True  # accumulation on dips
        elif bias < -0.15 and price_trend == "up":
            divergence = True  # distribution into strength

        # Phase classification
        if bias > 0.2:
            phase = "accumulation"
        elif bias < -0.2:
            phase = "distribution"
        else:
            phase = "neutral"

        # Confidence
        confidence = min(
            0.2 + 0.3 * min(len(orders) / 50, 1.0)
            + 0.2 * abs(bias)
            + 0.15 * (1.0 if divergence else 0.0)
            + 0.15 * min(total_flow / 500_000, 1.0),
            1.0,
        )

        # Time window
        window_ms = orders[-1]["ts"] - orders[0]["ts"] if len(orders) > 1 else 0
        window_minutes = window_ms / 60_000

        return {
            "phase": phase,
            "bias": round(bias, 4),
            "large_buy_usd": round(total_buy, 2),
            "large_sell_usd": round(total_sell, 2),
            "net_flow": round(net_flow, 2),
            "price_trend": price_trend,
            "divergence": divergence,
            "confidence": round(confidence, 3),
            "window_minutes": round(window_minutes, 1),
        }

    # ------------------------------------------------------------------
    # Whale activity
    # ------------------------------------------------------------------

    def get_whale_activity(self) -> dict:
        """
        Summary of recent whale activity.

        Returns
        -------
        dict:
            total_whale_trades : int
            total_whale_usd    : float
            buy_count          : int
            sell_count         : int
            buy_usd            : float
            sell_usd           : float
            net_whale_flow     : float
            avg_whale_size_usd : float
            largest_trade      : dict | None
            recent_trades      : list[dict]  -- last 10 whale trades
            intensity          : str  -- "low" | "moderate" | "high" | "extreme"
        """
        if not self.large_orders:
            return {
                "total_whale_trades": 0,
                "total_whale_usd": 0,
                "buy_count": 0,
                "sell_count": 0,
                "buy_usd": 0,
                "sell_usd": 0,
                "net_whale_flow": 0,
                "avg_whale_size_usd": 0,
                "largest_trade": None,
                "recent_trades": [],
                "intensity": "low",
            }

        orders = list(self.large_orders)

        buy_trades = [o for o in orders if o["side"] == "buy"]
        sell_trades = [o for o in orders if o["side"] == "sell"]

        buy_usd = sum(o["usd"] for o in buy_trades)
        sell_usd = sum(o["usd"] for o in sell_trades)
        total_usd = buy_usd + sell_usd

        largest = max(orders, key=lambda o: o["usd"])

        # Intensity based on trade frequency and size
        now = time.time() * 1000
        recent_window = 300_000  # 5 minutes
        recent_count = sum(1 for o in orders if (now - o["ts"]) < recent_window)

        if recent_count > 20:
            intensity = "extreme"
        elif recent_count > 10:
            intensity = "high"
        elif recent_count > 3:
            intensity = "moderate"
        else:
            intensity = "low"

        return {
            "total_whale_trades": len(orders),
            "total_whale_usd": round(total_usd, 2),
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "buy_usd": round(buy_usd, 2),
            "sell_usd": round(sell_usd, 2),
            "net_whale_flow": round(buy_usd - sell_usd, 2),
            "avg_whale_size_usd": round(total_usd / len(orders), 2) if orders else 0,
            "largest_trade": {
                "price": largest["price"],
                "qty": largest["qty"],
                "usd": round(largest["usd"], 2),
                "side": largest["side"],
                "ts": largest["ts"],
            },
            "recent_trades": [
                {
                    "price": o["price"],
                    "qty": o["qty"],
                    "usd": round(o["usd"], 2),
                    "side": o["side"],
                    "ts": o["ts"],
                }
                for o in orders[-10:]
            ],
            "intensity": intensity,
        }

    # ------------------------------------------------------------------
    # Large trade flow
    # ------------------------------------------------------------------

    def get_large_trade_flow(self, lookback_minutes: int = 30) -> list[dict]:
        """
        Recent large trades with direction and size.

        Parameters
        ----------
        lookback_minutes : how far back to look

        Returns
        -------
        list of dicts sorted by timestamp (newest first):
            price     : float
            qty       : float
            usd_value : float
            side      : "buy" | "sell"
            timestamp : float (ms)
            time_ago  : str  -- human-readable
            size_rank : str  -- "large" | "very_large" | "whale"
        """
        if not self.large_orders:
            return []

        cutoff = (time.time() - lookback_minutes * 60) * 1000
        recent = [o for o in self.large_orders if o["ts"] >= cutoff]

        if not recent:
            return []

        # Size ranking thresholds
        usd_values = [o["usd"] for o in recent]
        if len(usd_values) >= 3:
            p75 = sorted(usd_values)[int(len(usd_values) * 0.75)]
            p95 = sorted(usd_values)[int(len(usd_values) * 0.95)]
        else:
            p75 = self._whale_threshold_usd * 2
            p95 = self._whale_threshold_usd * 5

        now_ms = time.time() * 1000
        result: list[dict] = []

        for o in reversed(recent):  # newest first
            ago_ms = now_ms - o["ts"]
            ago_sec = ago_ms / 1000

            if ago_sec < 60:
                time_ago = f"{ago_sec:.0f}s ago"
            elif ago_sec < 3600:
                time_ago = f"{ago_sec / 60:.0f}m ago"
            else:
                time_ago = f"{ago_sec / 3600:.1f}h ago"

            if o["usd"] >= p95:
                size_rank = "whale"
            elif o["usd"] >= p75:
                size_rank = "very_large"
            else:
                size_rank = "large"

            result.append({
                "price": o["price"],
                "qty": o["qty"],
                "usd_value": round(o["usd"], 2),
                "side": o["side"],
                "timestamp": o["ts"],
                "time_ago": time_ago,
                "size_rank": size_rank,
            })

        return result

    # ------------------------------------------------------------------
    # Trade clustering
    # ------------------------------------------------------------------

    def detect_trade_clusters(self) -> list[dict]:
        """
        Find clusters of large trades in time, indicating coordinated
        institutional activity.

        Returns
        -------
        list of dicts:
            start_ts   : float
            end_ts     : float
            trade_count: int
            total_usd  : float
            net_flow   : float  -- positive = net buy
            avg_price  : float
            side_bias  : "buy" | "sell" | "mixed"
        """
        if len(self.large_orders) < 3:
            self.trade_clusters = []
            return []

        orders = sorted(self.large_orders, key=lambda o: o["ts"])
        clusters: list[dict] = []

        # Greedy clustering: merge trades within CLUSTER_WINDOW_MS
        current_cluster: list[dict] = [orders[0]]

        for i in range(1, len(orders)):
            gap = orders[i]["ts"] - current_cluster[-1]["ts"]
            if gap <= CLUSTER_WINDOW_MS:
                current_cluster.append(orders[i])
            else:
                if len(current_cluster) >= 3:
                    clusters.append(self._summarise_cluster(current_cluster))
                current_cluster = [orders[i]]

        # Don't forget the last cluster
        if len(current_cluster) >= 3:
            clusters.append(self._summarise_cluster(current_cluster))

        clusters.sort(key=lambda c: c["total_usd"], reverse=True)
        self.trade_clusters = clusters[:50]
        return self.trade_clusters

    @staticmethod
    def _summarise_cluster(trades: list[dict]) -> dict:
        buy_usd = sum(t["usd"] for t in trades if t["side"] == "buy")
        sell_usd = sum(t["usd"] for t in trades if t["side"] == "sell")
        total = buy_usd + sell_usd
        net = buy_usd - sell_usd

        if total > 0:
            buy_ratio = buy_usd / total
        else:
            buy_ratio = 0.5

        if buy_ratio > 0.65:
            side_bias = "buy"
        elif buy_ratio < 0.35:
            side_bias = "sell"
        else:
            side_bias = "mixed"

        prices = [t["price"] for t in trades]
        usd_values = [t["usd"] for t in trades]
        # VWAP of the cluster
        vwap = sum(p * u for p, u in zip(prices, usd_values)) / total if total > 0 else 0

        return {
            "start_ts": trades[0]["ts"],
            "end_ts": trades[-1]["ts"],
            "trade_count": len(trades),
            "total_usd": round(total, 2),
            "net_flow": round(net, 2),
            "avg_price": round(vwap, 2),
            "side_bias": side_bias,
        }
