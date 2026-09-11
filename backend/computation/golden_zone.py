"""
Nexus - Golden Zone Detection Engine
CORE EDGE - Multi-exchange order book overlap with fuzzy matching.

NEVER simplify to single-exchange check.
NEVER remove fuzzy matching (±0.05%).
NEVER remove persistence filter (2h minimum).

Algorithm:
1. Bin price action into BIN_SIZE_USD buckets per exchange
2. Identify top N buckets by depth + OI concentration per exchange
3. Fuzzy match across exchanges (bins within FUZZY_TOLERANCE = same zone)
4. Weight each exchange by EXCHANGE_WEIGHTS
5. Score = sum(depth * weight) for all overlapping exchanges
6. Persistence filter: only zones stable for PERSISTENCE_HOURS qualify
7. Classify tier by exchange overlap count
8. Classify zone type (support/resistance/magnet/void/absorption)
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.config import (
    EXCHANGE_WEIGHTS,
    FUZZY_TOLERANCE,
    ZONE_TIERS,
    PERSISTENCE_HOURS,
    BIN_SIZE_USD,
    ZONE_TYPES,
)

logger = logging.getLogger("nexus.golden_zone")


@dataclass
class LiquidityCluster:
    """A detected liquidity cluster on a single exchange."""
    exchange: str
    price: float
    bid_depth: float  # USD value of bids at this level
    ask_depth: float  # USD value of asks at this level
    net_depth: float  # bid - ask (positive = support, negative = resistance)
    bin_center: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class GoldenZone:
    """A validated multi-exchange liquidity zone."""
    price_low: float
    price_high: float
    price_center: float
    zone_type: str  # support, resistance, magnet, void, absorption
    tier: str  # bronze, silver, golden, platinum
    score: float
    exchanges: List[str]
    exchange_count: int
    clusters: List[LiquidityCluster]
    first_seen: float
    last_seen: float
    persistent: bool  # True if held for PERSISTENCE_HOURS
    bid_depth_total: float
    ask_depth_total: float

    @property
    def age_hours(self) -> float:
        return (time.time() - self.first_seen) / 3600

    @property
    def weight(self) -> float:
        tier_cfg = ZONE_TIERS.get(self.tier, {})
        return tier_cfg.get("weight", 0.3)

    def to_dict(self) -> dict:
        return {
            "price_low": self.price_low,
            "price_high": self.price_high,
            "price_center": self.price_center,
            "zone_type": self.zone_type,
            "tier": self.tier,
            "score": round(self.score, 4),
            "exchanges": self.exchanges,
            "exchange_count": self.exchange_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "persistent": self.persistent,
            "age_hours": round(self.age_hours, 2),
            "bid_depth_total": round(self.bid_depth_total, 2),
            "ask_depth_total": round(self.ask_depth_total, 2),
            "clusters": [
                {
                    "exchange": c.exchange,
                    "price": round(c.price, 4),
                    "bid_depth": round(c.bid_depth, 2),
                    "ask_depth": round(c.ask_depth, 2),
                    "net_depth": round(c.net_depth, 2),
                }
                for c in self.clusters
            ],
        }


class GoldenZoneEngine:
    """
    Multi-exchange Golden Zone detection with fuzzy matching.
    Call update_order_book() with each exchange's data, then detect_zones().
    """

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self._bin_size = BIN_SIZE_USD.get(symbol, BIN_SIZE_USD["DEFAULT"])
        self._exchange_books: Dict[str, dict] = {}  # {exchange: {"bids": [...], "asks": [...]}}
        self._zone_history: Dict[str, GoldenZone] = {}  # {zone_key: GoldenZone}
        self._top_n_bins = 20  # Top N bins per exchange to consider

    def update_order_book(self, exchange: str, order_book: dict):
        """Update order book data for an exchange."""
        if order_book and ("bids" in order_book or "asks" in order_book):
            self._exchange_books[exchange] = order_book

    def _bin_order_book(self, exchange: str) -> Dict[float, LiquidityCluster]:
        """Bin an exchange's order book into price buckets."""
        book = self._exchange_books.get(exchange, {})
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        bins: Dict[float, dict] = {}

        for price, qty in bids:
            if price <= 0:
                continue
            bin_center = round(price / self._bin_size) * self._bin_size
            if bin_center not in bins:
                bins[bin_center] = {"bid": 0.0, "ask": 0.0}
            bins[bin_center]["bid"] += price * qty

        for price, qty in asks:
            if price <= 0:
                continue
            bin_center = round(price / self._bin_size) * self._bin_size
            if bin_center not in bins:
                bins[bin_center] = {"bid": 0.0, "ask": 0.0}
            bins[bin_center]["ask"] += price * qty

        clusters = {}
        for center, depths in bins.items():
            clusters[center] = LiquidityCluster(
                exchange=exchange,
                price=center,
                bid_depth=depths["bid"],
                ask_depth=depths["ask"],
                net_depth=depths["bid"] - depths["ask"],
                bin_center=center,
            )
        return clusters

    def _get_top_bins(self, clusters: Dict[float, LiquidityCluster]) -> List[LiquidityCluster]:
        """Get the top N bins by total depth."""
        sorted_clusters = sorted(
            clusters.values(),
            key=lambda c: c.bid_depth + c.ask_depth,
            reverse=True,
        )
        return sorted_clusters[:self._top_n_bins]

    def _fuzzy_match(self, price_a: float, price_b: float) -> bool:
        """Check if two prices are within FUZZY_TOLERANCE (±0.05%)."""
        if price_a == 0 or price_b == 0:
            return False
        mid = (price_a + price_b) / 2
        return abs(price_a - price_b) / mid <= FUZZY_TOLERANCE

    def _classify_zone_type(self, bid_total: float, ask_total: float) -> str:
        """Classify zone as support, resistance, or other type."""
        if bid_total == 0 and ask_total == 0:
            return "void"
        ratio = bid_total / max(ask_total, 1e-10)
        if ratio > 2.0:
            return "support"
        elif ratio < 0.5:
            return "resistance"
        elif bid_total + ask_total < self._bin_size * 100:
            return "void"
        else:
            return "absorption"

    def _classify_tier(self, exchange_count: int, has_coinglass: bool = False) -> str:
        """Classify zone tier based on exchange overlap."""
        if exchange_count >= 3 and has_coinglass:
            return "platinum"
        elif exchange_count >= 3:
            return "golden"
        elif exchange_count >= 2:
            return "silver"
        else:
            return "bronze"

    def _zone_key(self, price_center: float) -> str:
        """Generate a unique key for a zone based on its center price."""
        return f"{self.symbol}_{price_center:.2f}"

    def detect_zones(self) -> List[GoldenZone]:
        """
        Run full Golden Zone detection across all available exchanges.
        Returns list of detected zones sorted by score (highest first).
        """
        if not self._exchange_books:
            return []

        # Step 1-2: Bin each exchange's order book, get top clusters
        exchange_top_bins: Dict[str, List[LiquidityCluster]] = {}
        for exchange in self._exchange_books:
            clusters = self._bin_order_book(exchange)
            top = self._get_top_bins(clusters)
            if top:
                exchange_top_bins[exchange] = top

        if not exchange_top_bins:
            return []

        # Step 3-4: Fuzzy match across exchanges
        # Use Binance bins as anchor (highest weight), match others to it
        anchor_exchange = "binance" if "binance" in exchange_top_bins else list(exchange_top_bins.keys())[0]
        anchor_bins = exchange_top_bins[anchor_exchange]

        zones: List[GoldenZone] = []
        now = time.time()

        for anchor_cluster in anchor_bins:
            matching_clusters = [anchor_cluster]
            matching_exchanges = {anchor_exchange}

            for other_exchange, other_bins in exchange_top_bins.items():
                if other_exchange == anchor_exchange:
                    continue
                for other_cluster in other_bins:
                    if self._fuzzy_match(anchor_cluster.price, other_cluster.price):
                        matching_clusters.append(other_cluster)
                        matching_exchanges.add(other_exchange)
                        break  # One match per exchange

            # Step 5: Score = sum(depth * weight)
            score = 0.0
            bid_total = 0.0
            ask_total = 0.0
            for cluster in matching_clusters:
                weight = EXCHANGE_WEIGHTS.get(cluster.exchange, 0.05)
                score += (cluster.bid_depth + cluster.ask_depth) * weight
                bid_total += cluster.bid_depth
                ask_total += cluster.ask_depth

            # Step 7: Classify tier
            tier = self._classify_tier(len(matching_exchanges))

            # Step 8: Classify zone type
            zone_type = self._classify_zone_type(bid_total, ask_total)

            # Calculate zone boundaries (±half bin size)
            half_bin = self._bin_size / 2
            price_center = anchor_cluster.price

            # Step 6: Check persistence
            zone_key = self._zone_key(price_center)
            if zone_key in self._zone_history:
                existing = self._zone_history[zone_key]
                existing.last_seen = now
                existing.score = score
                existing.clusters = matching_clusters
                existing.exchanges = list(matching_exchanges)
                existing.exchange_count = len(matching_exchanges)
                existing.tier = tier
                existing.zone_type = zone_type
                existing.bid_depth_total = bid_total
                existing.ask_depth_total = ask_total
                existing.persistent = existing.age_hours >= PERSISTENCE_HOURS
                zones.append(existing)
            else:
                zone = GoldenZone(
                    price_low=price_center - half_bin,
                    price_high=price_center + half_bin,
                    price_center=price_center,
                    zone_type=zone_type,
                    tier=tier,
                    score=score,
                    exchanges=list(matching_exchanges),
                    exchange_count=len(matching_exchanges),
                    clusters=matching_clusters,
                    first_seen=now,
                    last_seen=now,
                    persistent=False,
                    bid_depth_total=bid_total,
                    ask_depth_total=ask_total,
                )
                self._zone_history[zone_key] = zone
                zones.append(zone)

        # Prune stale zones (not seen in 4 hours)
        stale_keys = [
            k for k, z in self._zone_history.items()
            if now - z.last_seen > 4 * 3600
        ]
        for k in stale_keys:
            del self._zone_history[k]

        # Sort by score descending
        zones.sort(key=lambda z: z.score, reverse=True)
        return zones

    def get_persistent_zones(self) -> List[GoldenZone]:
        """Get only zones that have passed the persistence filter."""
        return [z for z in self.detect_zones() if z.persistent]

    def get_golden_plus_zones(self) -> List[GoldenZone]:
        """Get only golden and platinum tier zones."""
        return [
            z for z in self.detect_zones()
            if z.tier in ("golden", "platinum")
        ]
