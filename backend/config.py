"""
Nexus - Central Configuration
Loads all settings from .env via environment variables.
NEVER hardcode API keys. NEVER modify .env programmatically.

REMOVED (paid/unavailable):
- CoinGlass ($50/mo) → removed
- Whale Alert (paid) → removed
- CryptoPanic (no free tier) → replaced with RSS feeds
- CoinGecko → replaced with CoinMarketCap (free tier)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Exchange WebSocket endpoints
# ---------------------------------------------------------------------------
WS_BINANCE_FUTURES = "wss://fstream.binance.com/stream"
WS_OKX = "wss://ws.okx.com:8443/ws/v5/public"
WS_MEXC = "wss://contract.mexc.com/edge"

# Binance Futures streams per symbol
BINANCE_STREAMS = [
    "{symbol}@depth20@100ms",
    "{symbol}@aggTrade",
    "{symbol}@forceOrder",
    "{symbol}@kline_{interval}",
    "{symbol}@markPrice@1s",
]

# ---------------------------------------------------------------------------
# Exchange REST base URLs
# ---------------------------------------------------------------------------
BINANCE_FUTURES_BASE = "https://fapi.binance.com"
BINANCE_PM_BASE = "https://papi.binance.com"
BINANCE_BASE = "https://api.binance.com"
OKX_BASE = "https://www.okx.com"
DERIBIT_BASE = "https://www.deribit.com/api/v2/public"
BLOFIN_BASE = "https://openapi.blofin.com"
MEXC_FUTURES_BASE = "https://contract.mexc.com"

# ---------------------------------------------------------------------------
# Binance Futures REST endpoints (USDⓈ-M Derivatives)
# ---------------------------------------------------------------------------
BINANCE_FUTURES_ENDPOINTS = {
    "order_book": "/fapi/v1/depth",
    "oi": "/fapi/v1/openInterest",
    "funding": "/fapi/v1/fundingRate",
    "ls_ratio": "/futures/data/globalLongShortAccountRatio",
    "top_ls": "/futures/data/topLongShortPositionRatio",
    "klines": "/fapi/v1/klines",
    "agg_trades": "/fapi/v1/aggTrades",
    "mark_price": "/fapi/v1/premiumIndex",
    "liq_orders": "/fapi/v1/forceOrders",
    "exchange_info": "/fapi/v1/exchangeInfo",
    "leverage_bracket": "/fapi/v1/leverageBracket",
    "position_risk": "/fapi/v2/positionRisk",
    "account": "/fapi/v2/account",
    "change_leverage": "/fapi/v1/leverage",
    "change_margin_type": "/fapi/v1/marginType",
    "income_history": "/fapi/v1/income",
    "taker_buy_sell": "/futures/data/takerlongshortRatio",
}

# Binance Portfolio Margin endpoints
BINANCE_PM_ENDPOINTS = {
    "account": "/papi/v1/account",
    "balance": "/papi/v1/balance",
    "position": "/papi/v1/um/positionRisk",
    "cm_position": "/papi/v1/cm/positionRisk",
    "margin_order": "/papi/v1/um/order",
    "auto_repay": "/papi/v1/repay-futures-switch",
    "max_leverage": "/papi/v1/um/leverageBracket",
    "margin_balance": "/papi/v1/marginLoan",
    "transfer": "/papi/v1/asset/transfer",
}

# ---------------------------------------------------------------------------
# News & Intelligence sources (ALL FREE)
# ---------------------------------------------------------------------------
# RSS Feeds - free, no key needed
RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/.rss/full/",
]

# Binance Square / Binance News
BINANCE_NEWS_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"

# BloFin research
BLOFIN_NEWS_URL = "https://openapi.blofin.com/api/v1/market/news"

# CoinMarketCap - free tier (replaces CoinGecko)
CMC_BASE = "https://pro-api.coinmarketcap.com/v1"
CMC_API_KEY = os.getenv("CMC_API_KEY", "")

# Finnhub - news + social sentiment (free tier)
FINNHUB_BASE = "https://finnhub.io/api/v1"
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# ---------------------------------------------------------------------------
# Macro feeds (ALL FREE)
# ---------------------------------------------------------------------------
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = {
    "CPI": "CPIAUCSL",
    "FED_FUNDS_RATE": "FEDFUNDS",
    "US10Y": "DGS10",
    "US2Y": "DGS2",
    "DXY": "DTWEXBGS",
    "M2": "M2SL",
    "PCE": "PCE",
    "UNEMPLOYMENT": "UNRATE",
    "PMI_MFG": "MANEMP",
}
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

FEAR_GREED_URL = "https://api.alternative.me/fng/"
BLOCKCHAIN_BASE = "https://api.blockchain.info"
ETHERSCAN_BASE = "https://api.etherscan.io/api"
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")

# Yahoo Finance tickers (via yfinance - no key)
YFINANCE_TICKERS = {
    "SPX": "^GSPC",
    "VIX": "^VIX",
    "GOLD": "GC=F",
    "DXY": "DX-Y.NYB",
    "US10Y": "^TNX",
    "OIL": "CL=F",
}

# ---------------------------------------------------------------------------
# API keys - loaded from .env (placeholders, user fills manually)
# ---------------------------------------------------------------------------
# Binance (derivatives focused - USDⓈ-M)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
# Canonical Binance secret env var is BINANCE_API_SECRET. Legacy BINANCE_SECRET
# is accepted as a fallback and aliased back into os.environ so every consumer
# (os.getenv or config import) sees the same value.
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "") or os.getenv("BINANCE_SECRET", "")
if BINANCE_API_SECRET and not os.environ.get("BINANCE_API_SECRET"):
    os.environ["BINANCE_API_SECRET"] = BINANCE_API_SECRET
BINANCE_SECRET = BINANCE_API_SECRET  # back-compat alias for old imports
BINANCE_TESTNET = True  # ALWAYS True until paper trading validated

# BloFin (CCXT - paper trading)
BLOFIN_API_KEY = os.getenv("BLOFIN_API_KEY", "")
BLOFIN_SECRET = os.getenv("BLOFIN_SECRET", "")
BLOFIN_PASSPHRASE = os.getenv("BLOFIN_PASSPHRASE", "")  # "nexus"
BLOFIN_DEMO = True  # ALWAYS True until Phase 6

# OKX - read-only market data + (future) execution
# Accept multiple env spellings the user may have placed in .env.
OKX_API_KEY = os.getenv("OKX_API_KEY", "") or os.getenv("okx_apikey", "") or os.getenv("OKX_APIKEY", "")
OKX_API_SECRET = (
    os.getenv("OKX_API_SECRET", "")
    or os.getenv("okx_secretkey", "")
    or os.getenv("OKX_SECRET_KEY", "")
    or os.getenv("OKX_SECRET", "")
)
OKX_API_PASSPHRASE = os.getenv("OKX_API_PASSPHRASE", "") or os.getenv("OKX_PASSPHRASE", "")
OKX_KEY_NAME = os.getenv("okx_API_key_name", "") or os.getenv("OKX_API_KEY_NAME", "")
OKX_PERMISSIONS = os.getenv("okx_Permissions", "Read") or os.getenv("OKX_PERMISSIONS", "Read")

# MEXC - read-only market data (key set has Read scope only)
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = (
    os.getenv("MEXC_SECRET_KEY", "") or os.getenv("MEXC_API_SECRET", "") or os.getenv("MEXC_SECRET", "")
)
MEXC_IP = os.getenv("MEXC_IP", "")  # whitelisted IP, used by MEXC REST signed calls

# MEXC futures contract sizes (base-asset units per contract).
# Source: https://contract.mexc.com/api/v1/contract/detail
# Used by ingestion/mexc_ws.py to normalise contract volumes -> base units
# so depth aggregates correctly with Binance / OKX.
MEXC_CONTRACT_SIZE = {
    "BTCUSDT": 0.0001,
    "ETHUSDT": 0.01,
    "SOLUSDT": 1.0,
    "BNBUSDT": 0.01,
    "XRPUSDT": 10.0,
    "DEFAULT": 1.0,
}

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Golden Zone engine config
# ---------------------------------------------------------------------------
EXCHANGE_WEIGHTS = {
    "binance": 0.55,
    "okx": 0.27,
    "mexc": 0.14,
    "deribit": 0.04,
}

FUZZY_TOLERANCE = 0.0005  # +/-0.05% - NON-NEGOTIABLE

ZONE_TIERS = {
    "bronze": {"exchanges": 1, "weight": 0.3, "action": "monitor_only"},
    "silver": {"exchanges": 2, "weight": 0.6, "action": "alert_on_approach"},
    "golden": {"exchanges": 3, "weight": 1.0, "action": "full_alert_and_brief"},
    "platinum": {"exchanges": 3, "weight": 1.5, "action": "macro_gate_check_then_alert"},
    # 3-venue overlap (binance + okx + mexc) is the strongest institutional
    # consensus we can build without paid sources after retiring bybit/gate.
}

PERSISTENCE_HOURS = 2  # Zone must hold 2+ hours to be real

BIN_SIZE_USD = {
    "BTCUSDT": 50,
    "ETHUSDT": 10,
    "SOLUSDT": 0.5,
    "DEFAULT": 0.1,
}

# ---------------------------------------------------------------------------
# Institutional liquidity filtering (Liquidity Map)
# Strips retail noise from the heatmap & depth profile so users see the
# big bids only - institutional walls + golden zones, not $0.10 ladder noise.
# ---------------------------------------------------------------------------
INSTITUTIONAL_DEPTH = {
    "BTCUSDT": {
        "bin_usd": 25.0,
        "min_usd_per_level": 100_000.0,
        "max_levels_each_side": 15,
        "near_pct": 0.0075,
    },
    "ETHUSDT": {
        "bin_usd": 5.0,
        "min_usd_per_level": 50_000.0,
        "max_levels_each_side": 15,
        "near_pct": 0.0075,
    },
    "SOLUSDT": {"bin_usd": 0.5, "min_usd_per_level": 25_000.0, "max_levels_each_side": 15, "near_pct": 0.01},
    "BNBUSDT": {"bin_usd": 1.0, "min_usd_per_level": 25_000.0, "max_levels_each_side": 15, "near_pct": 0.01},
    "XRPUSDT": {
        "bin_usd": 0.005,
        "min_usd_per_level": 10_000.0,
        "max_levels_each_side": 15,
        "near_pct": 0.015,
    },
    "DEFAULT": {"bin_usd": 0.1, "min_usd_per_level": 10_000.0, "max_levels_each_side": 15, "near_pct": 0.02},
}

ZONE_TYPES = {
    "support": "Bid wall cluster - price likely to react upward",
    "resistance": "Ask wall cluster - price likely to react downward",
    "magnet": "Dense liquidation cluster not yet visited - price tends to seek this",
    "void": "Order book gap - price will move fast here with no friction",
    "absorption": "Large orders being filled without moving price - smart money accumulation",
}

# ---------------------------------------------------------------------------
# Signal thresholds
# ---------------------------------------------------------------------------
FUNDING_THRESHOLDS = {
    "extreme_long": 0.10,
    "high_long": 0.05,
    "neutral": 0.02,
    "high_short": -0.05,
    "extreme_short": -0.10,
}

LS_RATIO_THRESHOLDS = {
    "extreme_long": 1.8,
    "high_long": 1.4,
    "balanced": 1.0,
    "high_short": 0.7,
    "extreme_short": 0.55,
}

# ---------------------------------------------------------------------------
# Risk engine config
# ---------------------------------------------------------------------------
KELLY_CONFIG = {
    "max_position_pct": 0.02,
    "use_half_kelly": True,
    "max_leverage_suggested": 10,
    "margin_buffer_required": 0.30,
    "kelly_scale_by_confidence": True,
}

CIRCUIT_BREAKER = {
    "daily_loss_limit_pct": 0.05,
    "weekly_loss_limit_pct": 0.10,
    "max_drawdown_from_peak_pct": 0.15,
    "leverage_reduction_threshold": 0.03,
    "reset_time": "00:00 UTC",
    "override_allowed": False,
}

# ---------------------------------------------------------------------------
# Macro gate config
# ---------------------------------------------------------------------------
MACRO_GATE = {
    "Tier1_Critical": {
        "events": ["FOMC", "CPI", "NFP", "Fed_Chair_Speech", "Emergency_Fed"],
        "danger_window_hours": 2,
        "confidence_threshold": 0.85,
        "max_position_pct": 0.005,
        "leverage_cap": 3,
        "new_positions_allowed": False,
    },
    "Tier2_High": {
        "events": ["GDP", "PPI", "PCE", "ECB_Meeting", "BOJ_Meeting", "BOE_Meeting"],
        "danger_window_hours": 1,
        "confidence_threshold": 0.75,
        "max_position_pct": 0.01,
        "leverage_cap": 5,
        "new_positions_allowed": True,
    },
    "Tier3_Medium": {
        "events": ["PMI_Major", "Retail_Sales", "ISM", "JOLTS"],
        "danger_window_hours": 0.5,
        "confidence_threshold": 0.70,
        "max_position_pct": 0.015,
        "leverage_cap": 7,
        "new_positions_allowed": True,
    },
    "Tier4_Low": {
        "events": ["Regional_PMI", "Minor_Fed_Speech"],
        "danger_window_hours": 0,
        "confidence_threshold": 0.65,
        "max_position_pct": 0.02,
        "leverage_cap": 10,
        "new_positions_allowed": True,
    },
}

# ---------------------------------------------------------------------------
# AI / Ollama config - gemma4:e4b on localhost
# ---------------------------------------------------------------------------
OLLAMA_CONFIG = {
    "model": "gemma4:e4b",
    "endpoint": "http://localhost:11434/api/generate",
    "tags_endpoint": "http://localhost:11434/api/tags",
    # Fallback chain tried in order if the primary OOMs or 500s. Smallest first
    # so we can still synthesise under memory pressure.
    "fallback_models": ["gemma2:2b", "qwen2.5:1.5b", "llama3.2:1b", "phi3:mini"],
    "max_tokens": 1000,
    "max_tokens_fallback": 400,  # Shorter payload under pressure
    "temperature": 0.2,
    # Cold-loading gemma4:e4b (8.9GB Q4_K_M) on a 6GB-VRAM GPU takes ~85s before
    # the first token, so a 120s budget left no room for the actual generation
    # and every first click timed out. 300s covers cold load + a 1000-tok brief.
    "timeout_seconds": 300,
    # Keep the model resident between clicks so only the first call ever pays
    # the cold-load cost. Warm throughput is ~30 tok/s.
    "keep_alive": "30m",
}

FINBERT_CONFIG = {
    "model": "ProsusAI/finbert",
    "device": "cuda",
    "batch_size": 32,
    "inference_ms_target": 50,
    "labels": ["positive", "negative", "neutral"],
    "threshold_for_signal": 0.75,
}

MORNING_BRIEF_SCHEDULE = "08:00"

# ---------------------------------------------------------------------------
# Backtest config
# ---------------------------------------------------------------------------
BACKTEST_CONFIG = {
    "leverage_range": [1, 3, 5, 10],
    "funding_rate_cost": True,
    "model_liquidations": True,
    "slippage_model": "volume_adjusted",
    "taker_fee": 0.0004,
    "maker_fee": 0.0002,
}

# ---------------------------------------------------------------------------
# Default watchlist
# ---------------------------------------------------------------------------
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
DEFAULT_INTERVAL = "15m"

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DB_PATH = PROJECT_ROOT / "nexus.db"

# ---------------------------------------------------------------------------
# Cross-asset layer (OpenBB-shaped coverage, keyless)
#
# Nexus trades USDT-M perps. Everything below is *context*, never a tradable
# universe: it exists so the regime classifier, the macro gate and the research
# brief can see what the rest of the world is doing. Asset classes stay strictly
# separated - a cross-asset symbol must never reach a perp code path.
# ---------------------------------------------------------------------------

# Yahoo v8 chart is open; v10 quoteSummary / v7 options / v1 screener need a
# cookie+crumb pair that we mint and rotate ourselves. No API key either way.
YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_GATED_BASE = "https://query2.finance.yahoo.com"
YAHOO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# FRED's public CSV export - the same file the fredgraph charts download.
# No registration, no key. FRED_API_KEY stays supported as a faster path when
# the user has one, but nothing here requires it.
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# The cross-asset context universe, grouped the way OpenBB groups its router.
CROSS_ASSET_UNIVERSE = {
    "index": [
        ("^GSPC", "S&P 500"),
        ("^NDX", "Nasdaq 100"),
        ("^DJI", "Dow Jones"),
        ("^RUT", "Russell 2000"),
        ("^VIX", "VIX"),
        ("^FTSE", "FTSE 100"),
        ("^N225", "Nikkei 225"),
        ("^GDAXI", "DAX"),
    ],
    "rates": [
        ("^IRX", "US 13W"),
        ("^FVX", "US 5Y"),
        ("^TNX", "US 10Y"),
        ("^TYX", "US 30Y"),
        ("TLT", "20Y+ Treasury"),
        ("HYG", "High Yield"),
    ],
    "currency": [
        ("DX-Y.NYB", "Dollar Index"),
        ("EURUSD=X", "EUR/USD"),
        ("USDJPY=X", "USD/JPY"),
        ("GBPUSD=X", "GBP/USD"),
        ("USDCNY=X", "USD/CNY"),
        ("AUDUSD=X", "AUD/USD"),
    ],
    "commodity": [
        ("CL=F", "WTI Crude"),
        ("BZ=F", "Brent Crude"),
        ("NG=F", "Natural Gas"),
        ("GC=F", "Gold"),
        ("SI=F", "Silver"),
        ("HG=F", "Copper"),
        ("ZW=F", "Wheat"),
        ("ZC=F", "Corn"),
    ],
    "sector": [
        ("XLK", "Technology"),
        ("XLF", "Financials"),
        ("XLE", "Energy"),
        ("XLV", "Health Care"),
        ("XLI", "Industrials"),
        ("XLY", "Cons Discretionary"),
        ("XLP", "Cons Staples"),
        ("XLU", "Utilities"),
        ("XLB", "Materials"),
    ],
    "equity": [
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("NVDA", "NVIDIA"),
        ("GOOGL", "Alphabet"),
        ("AMZN", "Amazon"),
        ("META", "Meta"),
        ("TSLA", "Tesla"),
        ("COIN", "Coinbase"),
        ("MSTR", "Strategy"),
        ("MARA", "MARA"),
    ],
}

# The subset the regime classifier and risk-appetite score actually read.
# Kept small and stable: every one of these is a canonical macro axis.
REGIME_PROXIES = {
    "spx": "^GSPC",
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "us10y": "^TNX",
    "us2y": "^FVX",
    "gold": "GC=F",
    "oil": "CL=F",
    "hyg": "HYG",
    "copper": "HG=F",
}

# FRED series pulled for the macro screen. Keyless CSV; each carries its own
# publication lag, which the UI shows per card.
FRED_MACRO_SERIES = [
    ("CPIAUCSL", "CPI", "index", True),
    ("UNRATE", "Unemployment", "%", False),
    ("FEDFUNDS", "Fed Funds Rate", "%", False),
    ("GDPC1", "Real GDP", "$B", True),
    ("PAYEMS", "Nonfarm Payrolls", "K", False),
    ("T10Y2Y", "10Y-2Y Spread", "%", False),
    ("M2SL", "M2 Money Supply", "$B", True),
    ("UMCSENT", "Consumer Sentiment", "index", False),
    ("MORTGAGE30US", "30Y Mortgage", "%", False),
    ("BAMLH0A0HYM2", "HY Credit Spread", "%", False),
]

YAHOO_SCREENS = [
    ("day_gainers", "Gainers"),
    ("day_losers", "Losers"),
    ("most_actives", "Most Active"),
    ("growth_technology_stocks", "Growth Tech"),
    ("undervalued_growth_stocks", "Undervalued Growth"),
    ("most_shorted_stocks", "Most Shorted"),
]

CROSS_ASSET_POLL_SECONDS = 120.0  # ~55 daily-bar symbols per sweep; faster only risks a Yahoo 429

# ---------------------------------------------------------------------------
# Geopolitical / global-event layer (worldmonitor-shaped)
#
# Local sources are the mandatory base - Nexus must run with worldmonitor.app
# unreachable. The hosted API is optional enrichment only.
# ---------------------------------------------------------------------------
GEO_SOURCES = {
    # Seismic: M4.5+ in the last day. Free, no key, very reliable uptime.
    "usgs": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
    # Global Disaster Alerting Coordination System - EU JRC.
    "gdacs": "https://www.gdacs.org/xml/rss.xml",
    # NASA Earth Observatory Natural Event Tracker - storms, volcanoes, fires.
    "eonet": "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=100",
    # NOAA Space Weather Prediction Center - geomagnetic storm scale.
    "noaa_swpc": "https://services.swpc.noaa.gov/products/noaa-scales.json",
}
# Deliberately absent: ReliefWeb (v1 is 410 Gone, v2 403s without a registered
# appname) and GDELT DOC (hard 429s from a residential IP). Conflict signal comes
# from GEO_RSS instead. Do not re-add an upstream that has not been verified from
# this machine - a source that silently never answers is worse than no source,
# because the score renormalises around it and nobody notices.

# Conflict / security wires. RSS, no key, deduped against the existing news feed.
# Verified from this machine - each one returns items. The Google-News/Reuters
# proxy that used to sit here parsed fine but returned zero <item> elements,
# which is the worst kind of dead source: the score renormalises around it and
# nothing looks broken.
GEO_RSS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("UN News", "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("EIA Energy", "https://www.eia.gov/rss/todayinenergy.xml"),
]

# Optional enrichment. Their REST API requires an API key
# (X-WorldMonitor-Key: wm_<40 hex>); without one Nexus degrades to the locally
# computed instability score and says so. Never a hard dependency.
#
# Operation paths are the documented ones from worldmonitor.app/sandbox/index.json.
WORLDMONITOR_BASE = os.getenv("WORLDMONITOR_BASE", "https://api.worldmonitor.app")
WORLDMONITOR_API_KEY = os.getenv("WORLDMONITOR_API_KEY", "")
WORLDMONITOR_ENABLED = os.getenv("WORLDMONITOR_ENABLED", "1") not in ("0", "false", "False")

# Reads their key-free sandbox fixtures instead of the live API. For exercising
# the UI without a key ONLY - fixture payloads are flagged `sample` and are
# excluded from the instability score and the macro gate.
WORLDMONITOR_SANDBOX = os.getenv("WORLDMONITOR_SANDBOX", "0") in ("1", "true", "True")
WORLDMONITOR_SANDBOX_BASE = "https://www.worldmonitor.app/sandbox"

WORLDMONITOR_OPS = {
    "country_risk": "/api/intelligence/v1/get-country-risk",
    "chokepoints": "/api/supply-chain/v1/get-chokepoint-status",
}

# Their policy 403s short/default user agents.
WORLDMONITOR_UA = "nexus-terminal/1.0 (local research client)"

# Countries whose instability actually transmits into a crypto/macro book.
WORLDMONITOR_COUNTRIES = ["US", "CN", "RU", "IR", "IL", "UA", "TW", "VE", "SA", "KP"]

# ---------------------------------------------------------------------------
# Additional global-event domains (worldmonitor-shaped, sourced keylessly)
# ---------------------------------------------------------------------------

# CISA Known Exploited Vulnerabilities - the authoritative "being exploited
# right now" catalog. Free, no key, updated on business days.
CYBER_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

# OpenSky Network anonymous API. Rate-limited hard (~100 credits/day
# unauthenticated), so this is polled slowly and treated as best-effort.
AVIATION_STATES_URL = "https://opensky-network.org/api/states/all"

# Boxes worth watching for airspace disruption, as (name, lamin, lomin, lamax, lomax).
AVIATION_REGIONS = [
    ("Europe", 35.0, -10.0, 60.0, 30.0),
    ("Middle East", 12.0, 34.0, 40.0, 63.0),
    ("East Asia", 20.0, 100.0, 46.0, 146.0),
]

AVIATION_POLL_SECONDS = 900.0

# Geo risk -> macro gate escalation. Mirrors the MACRO_GATE tier shape so the
# gate can take the max of calendar risk and geopolitical risk without a
# translation table.
GEO_GATE = {
    "critical": {  # score >= 80
        "min_score": 80,
        "tier": "Tier1_Critical",
        "confidence_threshold": 0.85,
        "max_position_pct": 0.005,
        "leverage_cap": 3,
        "new_positions_allowed": False,
    },
    "elevated": {  # score >= 60
        "min_score": 60,
        "tier": "Tier2_High",
        "confidence_threshold": 0.75,
        "max_position_pct": 0.01,
        "leverage_cap": 5,
        "new_positions_allowed": True,
    },
    "watch": {  # score >= 40
        "min_score": 40,
        "tier": "Tier3_Medium",
        "confidence_threshold": 0.70,
        "max_position_pct": 0.015,
        "leverage_cap": 7,
        "new_positions_allowed": True,
    },
}

GEO_POLL_SECONDS = 300.0
