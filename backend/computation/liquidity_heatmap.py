"""
Nexus -- Liquidity Heatmap Generator
Builds a 2D price-vs-time heatmap of liquidity from raw order book snapshots.
Detects liquidity walls, voids, and liquidation clusters for institutional
order-flow analysis.
"""

import logging
import math
import statistics
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nexus.liquidity_heatmap")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lerp_index(value: float, lo: float, hi: float, num_bins: int) -> int:
    """Map a continuous value into a discrete bin index."""
    if hi <= lo:
        return 0
    ratio = (value - lo) / (hi - lo)
    idx = int(ratio * (num_bins - 1))
    return max(0, min(num_bins - 1, idx))


# ---------------------------------------------------------------------------
# LiquidityHeatmap
# ---------------------------------------------------------------------------

class LiquidityHeatmap:
    """
    Collects order book snapshots over time and produces a 2D intensity map.

    Y-axis: price levels
    X-axis: time buckets
    Cell value: normalised liquidity intensity (0..1)
    """

    def __init__(
        self,
        symbol: str,
        price_bins: int = 50,
        time_bins: int = 40,
        max_snapshots: int = 3600,
    ):
        self.symbol = symbol.upper()
        self.price_bins = price_bins
        self.time_bins = time_bins
        self.snapshots: deque[dict] = deque(maxlen=max_snapshots)

        # Liquidity wall / void detection thresholds
        self._wall_multiplier = 3.0   # size > 3x average = wall
        self._void_fraction = 0.15    # total liquidity in band < 15% of average = void

        # Most recent per-exchange order books (set by add_aggregated_snapshot)
        # Used by detect_aggregated_walls() to attribute walls to venues.
        self._latest_books_by_exchange: Dict[str, dict] = {}

        logger.info(
            "LiquidityHeatmap initialised for %s (price_bins=%d, time_bins=%d)",
            self.symbol, price_bins, time_bins,
        )

    # ------------------------------------------------------------------
    # Snapshot ingestion
    # ------------------------------------------------------------------

    def add_snapshot(
        self,
        bids: list[list[float]],
        asks: list[list[float]],
        timestamp: float,
    ) -> None:
        """
        Store an order book snapshot.

        Parameters
        ----------
        bids : list of [price, qty]
        asks : list of [price, qty]
        timestamp : epoch seconds (float)
        """
        if not bids and not asks:
            return

        self.snapshots.append({
            "bids": bids,
            "asks": asks,
            "ts": timestamp,
        })

    def add_aggregated_snapshot(
        self,
        books_by_exchange: Dict[str, dict],
        timestamp: float,
    ) -> None:
        """
        Aggregate per-exchange order books into a single combined snapshot.

        For the institutional Liquidity Map: a wall at $X is the SUM of bids
        sitting at $X across binance + okx + mexc. Detection
        runs on the combined book, so a $5M wall split across 3 venues at the
        same price is still a $5M wall.

        Quantities must already be normalised to base-asset units (the per-
        exchange ingestion modules handle contract→base conversion).
        """
        if not books_by_exchange:
            return

        # Snapshot the per-exchange books for later attribution in walls.
        self._latest_books_by_exchange = {
            ex: {
                "bids": list(book.get("bids", []) or []),
                "asks": list(book.get("asks", []) or []),
            }
            for ex, book in books_by_exchange.items()
            if book and (book.get("bids") or book.get("asks"))
        }

        # Bin to fuzzy ticks so the same wall reported at slightly different
        # prices on two venues lands on one bin. Tick = 0.05% of mid, matching
        # the Golden Zone fuzzy tolerance.
        all_prices: list[float] = []
        for book in self._latest_books_by_exchange.values():
            for p, _ in book["bids"]:
                if p > 0:
                    all_prices.append(p)
            for p, _ in book["asks"]:
                if p > 0:
                    all_prices.append(p)
        if not all_prices:
            return
        mid = (max(all_prices) + min(all_prices)) / 2.0
        tick = max(mid * 0.0005, 0.01)  # 0.05% of mid

        bid_acc: Dict[float, float] = {}
        ask_acc: Dict[float, float] = {}
        for book in self._latest_books_by_exchange.values():
            for p, q in book["bids"]:
                if p <= 0 or q <= 0:
                    continue
                key = round(p / tick) * tick
                bid_acc[key] = bid_acc.get(key, 0.0) + q
            for p, q in book["asks"]:
                if p <= 0 or q <= 0:
                    continue
                key = round(p / tick) * tick
                ask_acc[key] = ask_acc.get(key, 0.0) + q

        bids = sorted(bid_acc.items(), key=lambda kv: -kv[0])
        asks = sorted(ask_acc.items(), key=lambda kv: kv[0])

        if not bids and not asks:
            return

        self.snapshots.append({
            "bids": [[p, q] for p, q in bids],
            "asks": [[p, q] for p, q in asks],
            "ts": timestamp,
        })

    # ------------------------------------------------------------------
    # Heatmap generation
    # ------------------------------------------------------------------

    def generate_heatmap(
        self,
        lookback_minutes: int = 30,
        min_usd_per_cell: float = 0.0,
    ) -> dict:
        """
        Generate heatmap data for the frontend.

        Returns
        -------
        dict with keys:
            price_levels  : list[float]   -- y-axis tick values
            time_labels   : list[str]     -- x-axis labels (HH:MM)
            bid_intensity : list[list[float]]  -- 2D [time_bin][price_bin]
            ask_intensity : list[list[float]]  -- 2D [time_bin][price_bin]
            liquidation_clusters : list[dict]
            current_price : float
            price_range   : [min, max]
        """
        now = time.time()
        cutoff = now - lookback_minutes * 60

        relevant = [s for s in self.snapshots if s["ts"] >= cutoff]
        if not relevant:
            return self._empty_heatmap()

        # Determine price range from all snapshots
        all_prices: list[float] = []
        for snap in relevant:
            for level in snap["bids"]:
                all_prices.append(level[0])
            for level in snap["asks"]:
                all_prices.append(level[0])

        if not all_prices:
            return self._empty_heatmap()

        price_min = min(all_prices)
        price_max = max(all_prices)

        # Add 0.5% padding
        padding = (price_max - price_min) * 0.005
        price_min -= padding
        price_max += padding

        if price_max <= price_min:
            price_max = price_min + 1.0

        # Build price levels (y-axis)
        price_step = (price_max - price_min) / self.price_bins
        price_levels = [round(price_min + i * price_step, 2) for i in range(self.price_bins)]

        # Build time buckets (x-axis)
        time_start = relevant[0]["ts"]
        time_end = relevant[-1]["ts"]
        if time_end <= time_start:
            time_end = time_start + 1.0

        time_step = (time_end - time_start) / self.time_bins

        time_labels: list[str] = []
        for i in range(self.time_bins):
            t = time_start + i * time_step
            lt = time.localtime(t)
            time_labels.append(f"{lt.tm_hour:02d}:{lt.tm_min:02d}")

        # Accumulate intensity into 2D grids
        bid_grid = [[0.0] * self.price_bins for _ in range(self.time_bins)]
        ask_grid = [[0.0] * self.price_bins for _ in range(self.time_bins)]

        for snap in relevant:
            t_idx = _lerp_index(snap["ts"], time_start, time_end, self.time_bins)

            for price, qty in snap["bids"]:
                p_idx = _lerp_index(price, price_min, price_max, self.price_bins)
                bid_grid[t_idx][p_idx] += qty

            for price, qty in snap["asks"]:
                p_idx = _lerp_index(price, price_min, price_max, self.price_bins)
                ask_grid[t_idx][p_idx] += qty

        # Institutional filter: zero out cells whose notional is below the
        # USD floor. Retail tick noise vanishes; only the big bids stay.
        if min_usd_per_cell > 0:
            for t in range(self.time_bins):
                for p in range(self.price_bins):
                    px = price_levels[p] if p < len(price_levels) else 0.0
                    if bid_grid[t][p] * px < min_usd_per_cell:
                        bid_grid[t][p] = 0.0
                    if ask_grid[t][p] * px < min_usd_per_cell:
                        ask_grid[t][p] = 0.0

        # Normalise to 0..1
        global_max = 1e-12
        for row in bid_grid:
            m = max(row) if row else 0
            if m > global_max:
                global_max = m
        for row in ask_grid:
            m = max(row) if row else 0
            if m > global_max:
                global_max = m

        bid_intensity = [[round(v / global_max, 4) for v in row] for row in bid_grid]
        ask_intensity = [[round(v / global_max, 4) for v in row] for row in ask_grid]

        # Current price from latest snapshot
        latest = relevant[-1]
        current_price = 0.0
        if latest["bids"] and latest["asks"]:
            current_price = (latest["bids"][0][0] + latest["asks"][0][0]) / 2.0
        elif latest["bids"]:
            current_price = latest["bids"][0][0]
        elif latest["asks"]:
            current_price = latest["asks"][0][0]

        # Liquidation clusters (from persistent concentration of liquidity)
        liq_clusters = self._detect_liquidation_clusters(bid_grid, ask_grid, price_levels)

        return {
            "price_levels": price_levels,
            "time_labels": time_labels,
            "bid_intensity": bid_intensity,
            "ask_intensity": ask_intensity,
            "liquidation_clusters": liq_clusters,
            "current_price": round(current_price, 2),
            "price_range": [round(price_min, 2), round(price_max, 2)],
            "snapshot_count": len(relevant),
            "lookback_minutes": lookback_minutes,
        }

    # ------------------------------------------------------------------
    # Depth profile
    # ------------------------------------------------------------------

    def get_depth_profile(self) -> dict:
        """
        Current order book depth as a profile chart.

        Returns
        -------
        dict with keys:
            bids : list[dict] with price, qty, cumulative
            asks : list[dict] with price, qty, cumulative
            mid_price : float
            total_bid_depth : float
            total_ask_depth : float
            imbalance : float  -- -1 (ask heavy) to +1 (bid heavy)
        """
        if not self.snapshots:
            return {
                "bids": [], "asks": [], "mid_price": 0,
                "total_bid_depth": 0, "total_ask_depth": 0, "imbalance": 0,
            }

        latest = self.snapshots[-1]
        bids = latest["bids"]
        asks = latest["asks"]

        bid_profile: list[dict] = []
        cum = 0.0
        for price, qty in bids:
            cum += qty
            bid_profile.append({"price": price, "qty": qty, "cumulative": round(cum, 4)})

        ask_profile: list[dict] = []
        cum = 0.0
        for price, qty in asks:
            cum += qty
            ask_profile.append({"price": price, "qty": qty, "cumulative": round(cum, 4)})

        total_bid = sum(b[1] for b in bids) if bids else 0
        total_ask = sum(a[1] for a in asks) if asks else 0
        total = total_bid + total_ask

        mid_price = 0.0
        if bids and asks:
            mid_price = (bids[0][0] + asks[0][0]) / 2.0
        elif bids:
            mid_price = bids[0][0]
        elif asks:
            mid_price = asks[0][0]

        imbalance = (total_bid - total_ask) / total if total > 0 else 0.0

        return {
            "bids": bid_profile,
            "asks": ask_profile,
            "mid_price": round(mid_price, 2),
            "total_bid_depth": round(total_bid, 4),
            "total_ask_depth": round(total_ask, 4),
            "imbalance": round(imbalance, 4),
        }

    # ------------------------------------------------------------------
    # Institutional depth profile (filters retail noise)
    # ------------------------------------------------------------------

    def get_institutional_depth_profile(
        self,
        bin_usd: float,
        min_usd_per_level: float,
        max_levels_each_side: int = 15,
        near_pct: float = 0.01,
    ) -> dict:
        """
        Build a depth profile that ONLY shows institutional-size resting
        liquidity. Levels are re-binned into wide USD buckets (e.g. $25 for
        BTC) so $0.10-tick retail noise collapses, then any bucket below
        `min_usd_per_level` notional is dropped.

        Returns top `max_levels_each_side` levels each side within
        `near_pct` of mid, sorted by distance from mid (nearest first).
        """
        if not self.snapshots or bin_usd <= 0:
            return {
                "bids": [], "asks": [], "mid_price": 0.0,
                "total_bid_usd": 0.0, "total_ask_usd": 0.0, "imbalance": 0.0,
                "bin_usd": bin_usd, "min_usd_per_level": min_usd_per_level,
            }

        latest = self.snapshots[-1]
        bids_raw = latest["bids"]
        asks_raw = latest["asks"]

        mid = 0.0
        if bids_raw and asks_raw:
            mid = (bids_raw[0][0] + asks_raw[0][0]) / 2.0
        elif bids_raw:
            mid = bids_raw[0][0]
        elif asks_raw:
            mid = asks_raw[0][0]
        if mid <= 0:
            return {
                "bids": [], "asks": [], "mid_price": 0.0,
                "total_bid_usd": 0.0, "total_ask_usd": 0.0, "imbalance": 0.0,
                "bin_usd": bin_usd, "min_usd_per_level": min_usd_per_level,
            }

        near_band = mid * near_pct

        def _bin_side(levels, is_bid: bool):
            buckets: Dict[float, float] = {}
            for p, q in levels:
                if p <= 0 or q <= 0:
                    continue
                if abs(p - mid) > near_band:
                    continue
                # Floor for bids (round down), ceil for asks (round up) so
                # buckets sit on the price-action side of mid.
                if is_bid:
                    key = math.floor(p / bin_usd) * bin_usd
                else:
                    key = math.ceil(p / bin_usd) * bin_usd
                buckets[key] = buckets.get(key, 0.0) + q
            out = []
            for px, qty in buckets.items():
                usd = qty * px
                if usd < min_usd_per_level:
                    continue
                out.append({
                    "price": round(px, 2),
                    "qty": round(qty, 6),
                    "usd_value": round(usd, 0),
                    "contributors": self._wall_contributors(px, "bid" if is_bid else "ask"),
                })
            # Nearest-to-mid first, then size as tiebreaker
            out.sort(key=lambda lv: (abs(lv["price"] - mid), -lv["usd_value"]))
            return out[:max_levels_each_side]

        bid_levels = _bin_side(bids_raw, is_bid=True)
        ask_levels = _bin_side(asks_raw, is_bid=False)

        total_bid_usd = sum(lv["usd_value"] for lv in bid_levels)
        total_ask_usd = sum(lv["usd_value"] for lv in ask_levels)
        total = total_bid_usd + total_ask_usd
        imbalance = (total_bid_usd - total_ask_usd) / total if total > 0 else 0.0

        max_usd = max(
            (lv["usd_value"] for lv in bid_levels + ask_levels),
            default=0.0,
        )
        for lv in bid_levels:
            lv["intensity"] = round(lv["usd_value"] / max_usd, 4) if max_usd > 0 else 0.0
        for lv in ask_levels:
            lv["intensity"] = round(lv["usd_value"] / max_usd, 4) if max_usd > 0 else 0.0

        return {
            "bids": bid_levels,
            "asks": ask_levels,
            "mid_price": round(mid, 2),
            "total_bid_usd": round(total_bid_usd, 0),
            "total_ask_usd": round(total_ask_usd, 0),
            "imbalance": round(imbalance, 4),
            "bin_usd": bin_usd,
            "min_usd_per_level": min_usd_per_level,
            "max_usd": round(max_usd, 0),
        }

    # ------------------------------------------------------------------
    # Liquidity walls
    # ------------------------------------------------------------------

    def detect_liquidity_walls(self) -> list[dict]:
        """
        Find significant liquidity walls (large resting orders).

        Detection criteria (OR'd - either is sufficient):
          1. Relative: size ≥ wall_multiplier × **median** level size (median
             is robust to the very wall we're trying to detect; the previous
             mean-based test was self-defeating because a single $90M level
             dragged the average up enough to disqualify itself).
          2. Absolute: USD value ≥ INSTITUTIONAL_USD_FLOOR ($1M default).
             A $5M resting bid is institutional regardless of how it stacks
             against the rest of the book.

        Returns a list of dicts:
            price : float
            qty   : float
            side  : "bid" | "ask"
            usd_value : float
            significance : float  -- multiple of median level size
        """
        if not self.snapshots:
            return []

        latest = self.snapshots[-1]
        bids = latest["bids"]
        asks = latest["asks"]

        all_sizes = [level[1] for level in bids if level[1] > 0] + \
                    [level[1] for level in asks if level[1] > 0]
        if not all_sizes:
            return []

        # Median is robust to the wall outliers we're detecting. Mean would
        # absorb a $90M wall into the threshold and disqualify it - verified
        # against live BTCUSDT books showing $92M asks failing 3x mean test.
        median_size = statistics.median(all_sizes)
        if median_size <= 0:
            return []

        ABSOLUTE_USD_FLOOR = 1_000_000.0

        walls: list[dict] = []

        for price, qty in bids:
            usd = price * qty
            ratio = qty / median_size
            if ratio >= self._wall_multiplier or usd >= ABSOLUTE_USD_FLOOR:
                walls.append({
                    "price": price,
                    "total_size": qty,
                    "side": "bid",
                    "usd_value": round(usd, 2),
                    "persistence": 1.0,
                    "significance": round(ratio, 2),
                })

        for price, qty in asks:
            usd = price * qty
            ratio = qty / median_size
            if ratio >= self._wall_multiplier or usd >= ABSOLUTE_USD_FLOOR:
                walls.append({
                    "price": price,
                    "total_size": qty,
                    "side": "ask",
                    "usd_value": round(usd, 2),
                    "persistence": 1.0,
                    "significance": round(ratio, 2),
                })

        walls.sort(key=lambda w: w["significance"], reverse=True)

        # Attribute each wall to the exchanges that contributed (institutional
        # liquidity map shows which venue is parking the size).
        if self._latest_books_by_exchange:
            for w in walls:
                w["contributors"] = self._wall_contributors(w["price"], w["side"])

        return walls

    def _wall_contributors(self, price: float, side: str) -> List[Dict]:
        """
        Find which exchanges have orders at (or fuzzily near) `price` on
        `side` ("bid" | "ask"), and how much each contributes.
        """
        if not self._latest_books_by_exchange or price <= 0:
            return []
        tol = max(price * 0.0005, 0.01)  # 0.05%
        side_key = "bids" if side == "bid" else "asks"
        out: List[Dict] = []
        for ex, book in self._latest_books_by_exchange.items():
            qty = 0.0
            for p, q in book.get(side_key, []):
                if abs(p - price) <= tol:
                    qty += q
            if qty > 0:
                out.append({
                    "exchange": ex,
                    "qty": round(qty, 6),
                    "usd_value": round(qty * price, 2),
                })
        out.sort(key=lambda c: -c["usd_value"])
        return out

    # ------------------------------------------------------------------
    # Liquidity voids
    # ------------------------------------------------------------------

    def detect_liquidity_voids(self) -> list[dict]:
        """
        Find price ranges with minimal liquidity (fast-move zones).

        Scans the latest order book for gaps or thin regions where a market
        order would cause outsized price impact.

        Returns a list of dicts:
            price_start : float
            price_end   : float
            side        : "bid" | "ask"
            total_qty   : float
            avg_qty     : float
            void_score  : float  -- lower = thinner
        """
        if not self.snapshots:
            return []

        latest = self.snapshots[-1]
        voids: list[dict] = []

        for side_key, side_label in [("bids", "bid"), ("asks", "ask")]:
            levels = latest[side_key]
            if len(levels) < 4:
                continue

            sizes = [lv[1] for lv in levels]
            avg_size = statistics.mean(sizes)
            if avg_size <= 0:
                continue

            # Sliding window of 3 levels
            window = 3
            for i in range(len(levels) - window + 1):
                window_levels = levels[i: i + window]
                window_qty = sum(lv[1] for lv in window_levels)
                window_avg = window_qty / window

                if window_avg < avg_size * self._void_fraction:
                    voids.append({
                        "price_start": window_levels[0][0],
                        "price_end": window_levels[-1][0],
                        "side": side_label,
                        "total_qty": round(window_qty, 6),
                        "avg_qty": round(window_avg, 6),
                        "void_score": round(window_avg / avg_size, 4) if avg_size > 0 else 0,
                    })

        voids.sort(key=lambda v: v["void_score"])
        return voids

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_heatmap(self) -> dict:
        return {
            "price_levels": [],
            "time_labels": [],
            "bid_intensity": [],
            "ask_intensity": [],
            "liquidation_clusters": [],
            "current_price": 0.0,
            "price_range": [0.0, 0.0],
            "snapshot_count": 0,
            "lookback_minutes": 0,
        }

    def _detect_liquidation_clusters(
        self,
        bid_grid: list[list[float]],
        ask_grid: list[list[float]],
        price_levels: list[float],
    ) -> list[dict]:
        """
        Identify persistent concentrations of liquidity across time that
        likely represent liquidation cluster zones.

        A cluster is a price bin where liquidity has been consistently high
        across multiple time buckets (orders are refreshed, not swept).
        """
        if not price_levels or not bid_grid:
            return []

        clusters: list[dict] = []
        num_time = len(bid_grid)
        num_price = len(price_levels)

        # For each price bin, count how many time bins had above-average liquidity
        all_values: list[float] = []
        for t in range(num_time):
            for p in range(num_price):
                v = bid_grid[t][p] + ask_grid[t][p]
                all_values.append(v)

        if not all_values:
            return clusters

        avg_val = statistics.mean(all_values)
        if avg_val <= 0:
            return clusters

        threshold = avg_val * 2.5

        for p in range(num_price):
            high_count = 0
            total_size = 0.0
            bid_total = 0.0
            ask_total = 0.0
            for t in range(num_time):
                bv = bid_grid[t][p]
                av = ask_grid[t][p]
                combined = bv + av
                if combined > threshold:
                    high_count += 1
                total_size += combined
                bid_total += bv
                ask_total += av

            persistence = high_count / max(num_time, 1)
            if persistence > 0.3 and total_size > avg_val * num_time * 1.5:
                side = "bid" if bid_total > ask_total else "ask"
                clusters.append({
                    "price": price_levels[p],
                    "size": round(total_size, 4),
                    "side": side,
                    "persistence": round(persistence, 3),
                })

        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters[:20]  # top 20 clusters
