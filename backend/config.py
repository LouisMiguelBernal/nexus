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
OKX_API_KEY = (
    os.getenv("OKX_API_KEY", "")
    or os.getenv("okx_apikey", "")
    or os.getenv("OKX_APIKEY", "")
)
OKX_API_SECRET = (
    os.getenv("OKX_API_SECRET", "")
    or os.getenv("okx_secretkey", "")
    or os.getenv("OKX_SECRET_KEY", "")
    or os.getenv("OKX_SECRET", "")
)
OKX_API_PASSPHRASE = (
    os.getenv("OKX_API_PASSPHRASE", "")
    or os.getenv("OKX_PASSPHRASE", "")
)
OKX_KEY_NAME = os.getenv("okx_API_key_name", "") or os.getenv("OKX_API_KEY_NAME", "")
OKX_PERMISSIONS = os.getenv("okx_Permissions", "Read") or os.getenv("OKX_PERMISSIONS", "Read")

# MEXC - read-only market data (key set has Read scope only)
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = (
    os.getenv("MEXC_SECRET_KEY", "")
    or os.getenv("MEXC_API_SECRET", "")
    or os.getenv("MEXC_SECRET", "")
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
    "bronze":   {"exchanges": 1, "weight": 0.3, "action": "monitor_only"},
    "silver":   {"exchanges": 2, "weight": 0.6, "action": "alert_on_approach"},
    "golden":   {"exchanges": 3, "weight": 1.0, "action": "full_alert_and_brief"},
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
    "BTCUSDT": {"bin_usd": 25.0,  "min_usd_per_level": 100_000.0, "max_levels_each_side": 15, "near_pct": 0.0075},
    "ETHUSDT": {"bin_usd": 5.0,   "min_usd_per_level": 50_000.0,  "max_levels_each_side": 15, "near_pct": 0.0075},
    "SOLUSDT": {"bin_usd": 0.5,   "min_usd_per_level": 25_000.0,  "max_levels_each_side": 15, "near_pct": 0.01},
    "BNBUSDT": {"bin_usd": 1.0,   "min_usd_per_level": 25_000.0,  "max_levels_each_side": 15, "near_pct": 0.01},
    "XRPUSDT": {"bin_usd": 0.005, "min_usd_per_level": 10_000.0,  "max_levels_each_side": 15, "near_pct": 0.015},
    "DEFAULT": {"bin_usd": 0.1,   "min_usd_per_level": 10_000.0,  "max_levels_each_side": 15, "near_pct": 0.02},
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
    "timeout_seconds": 120,
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
