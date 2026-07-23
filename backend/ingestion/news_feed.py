"""
Nexus - News Feed Ingestion (ALL FREE sources)
- RSS feeds: CoinTelegraph, CoinDesk, Decrypt, Bitcoin Magazine
- Binance Square news via public API
- BloFin research section
- Finnhub crypto news (free tier)

REMOVED (paid): CryptoPanic, Whale Alert, CoinGlass
"""

import logging
import time
from typing import Dict, List

import feedparser
import httpx

from backend.config import (
    RSS_FEEDS,
    BINANCE_NEWS_URL,
    BLOFIN_BASE,
    FINNHUB_BASE, FINNHUB_API_KEY,
)

logger = logging.getLogger("nexus.news_feed")


class NewsFeed:
    """Aggregate news from multiple free sources."""

    def __init__(self):
        self._headlines: List[Dict] = []

    def fetch_rss_feeds(self, limit: int = 20) -> List[Dict]:
        """Fetch latest crypto news from RSS feeds (sync - feedparser)."""
        articles = []
        for url in RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                source_name = feed.feed.get("title", url.split("/")[2])
                for entry in feed.entries[:5]:
                    articles.append({
                        "source": source_name,
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "summary": entry.get("summary", "")[:200] if entry.get("summary") else "",
                    })
            except Exception as e:
                logger.warning(f"RSS feed error ({url}): {e}")
        return articles[:limit]

    async def fetch_binance_news(self, limit: int = 15) -> List[Dict]:
        """Fetch news from Binance Square / CMS API."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Binance public CMS article list
                resp = await client.post(BINANCE_NEWS_URL, json={
                    "type": 1,
                    "pageNo": 1,
                    "pageSize": limit,
                    "catalogId": 48,  # Crypto news category
                })
                data = resp.json()
                articles = data.get("data", {}).get("catalogs", [{}])
                if articles:
                    articles = articles[0].get("articles", [])

                results = []
                for item in articles[:limit]:
                    results.append({
                        "source": "binance_square",
                        "title": item.get("title", ""),
                        "url": f"https://www.binance.com/en/news/detail/{item.get('id', '')}",
                        "published": item.get("releaseDate", ""),
                    })
                return results
        except Exception as e:
            logger.warning(f"Binance news error: {e}")
            # Fallback: try the Binance announcements API
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                        params={"type": 1, "pageNo": 1, "pageSize": limit},
                    )
                    data = resp.json()
                    items = data.get("data", {}).get("catalogs", [{}])
                    results = []
                    if items:
                        for art in items[0].get("articles", [])[:limit]:
                            results.append({
                                "source": "binance_announcements",
                                "title": art.get("title", ""),
                                "url": f"https://www.binance.com/en/support/announcement/{art.get('code', '')}",
                                "published": art.get("releaseDate", ""),
                            })
                    return results
            except Exception as e2:
                logger.warning(f"Binance announcements fallback error: {e2}")
                return []

    async def fetch_blofin_research(self, limit: int = 10) -> List[Dict]:
        """Fetch BloFin research / news section."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{BLOFIN_BASE}/api/v1/market/news", params={"limit": limit})
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", [])
                    return [{
                        "source": "blofin_research",
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "published": item.get("publishTime", ""),
                    } for item in items[:limit]]
        except Exception as e:
            logger.debug(f"BloFin research: {e}")
        return []

    async def fetch_finnhub(self, category: str = "crypto") -> List[Dict]:
        """Fetch market news from Finnhub (free tier)."""
        if not FINNHUB_API_KEY:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{FINNHUB_BASE}/news", params={
                    "category": category,
                    "token": FINNHUB_API_KEY,
                })
                data = resp.json()
                return [{
                    "source": "finnhub",
                    "title": item.get("headline", ""),
                    "url": item.get("url", ""),
                    "published": item.get("datetime", 0),
                    "summary": item.get("summary", "")[:200],
                } for item in data[:20]]
        except Exception as e:
            logger.error(f"Finnhub error: {e}")
            return []

    async def fetch_all(self) -> List[Dict]:
        """Fetch from all sources. RSS is sync, rest are async."""
        import asyncio

        # RSS feeds (sync - runs in executor to not block)
        loop = asyncio.get_event_loop()
        rss_news = await loop.run_in_executor(None, self.fetch_rss_feeds)

        # Async feeds
        results = await asyncio.gather(
            self.fetch_binance_news(),
            self.fetch_blofin_research(),
            self.fetch_finnhub(),
            return_exceptions=True,
        )

        all_news = list(rss_news)
        for r in results:
            if isinstance(r, list):
                all_news.extend(r)

        self._headlines = all_news
        logger.info(f"News feed: {len(all_news)} headlines from {len(set(h.get('source', '') for h in all_news))} sources")
        return all_news

    def get_headline_texts(self) -> List[str]:
        """Get just the headline text for FinBERT scoring."""
        return [h["title"] for h in self._headlines if h.get("title")]
