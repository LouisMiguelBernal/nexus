# Data Sources

Every external source Nexus touches, what protects it, and what could break. This is the human-readable side of the source registry (`backend/data/registry.py`, Phase 1); until the registry exists, this file is the contract. All sources are free. Keys are read from `.env` and every source degrades to "unavailable" — never to zero — when its key is missing or it fails (`instability.py`: *unavailable is not zero*).

## Market data (tradable universe)

| Source | Kind | Host | Key | Cadence / throttle | Guard | Notes |
|---|---|---|---|---|---|---|
| Binance USDⓈ-M | WebSocket | `fstream.binance.com` | no | `depth20@100ms`, `aggTrade`, `forceOrder`, `kline_15m`, `markPrice@1s` | reconnect backoff ≤ 120 s, gap log, kline re-fetch | Primary venue; the only one whose outage should trip the breaker |
| Binance USDⓈ-M | REST | `fapi.binance.com` | public; signed for account reads | pollers own freshness (OI/funding 30 s); request path never hits REST | `rate_guard` parses 418/-1003 bans | Signed calls use the live key for **read-only** journal/PM endpoints; `BINANCE_TESTNET` gets a consumer in Phase 3 |
| Binance spot | REST | `api.binance.com` | no | strip 10 s | `rate_guard` | |
| OKX | WebSocket + REST | `ws.okx.com`, `www.okx.com` | optional (read scope) | live | reconnect backoff | Frequently ISP-blocked (PLDT); secondary venue |
| MEXC | WebSocket + REST | `contract.mexc.com` | optional (read scope, IP allow-list) | live; app-level ping | reconnect backoff | Contract sizes normalised via `MEXC_CONTRACT_SIZE` |
| Deribit | REST | `deribit.com/api/v2/public` | no | 60 s TTL | — | Options / IV / DVOL context |
| BloFin | REST (ccxt) | `openapi.blofin.com` | yes (key, secret, passphrase) | on demand | `BLOFIN_DEMO=True` forced | Paper venue. Live is locked (ADR 0004, plan §3.7) |

## News and sentiment

| Source | Kind | Key | Cadence | Guard | Notes |
|---|---|---|---|---|---|
| Cointelegraph, CoinDesk, Decrypt, Bitcoin Magazine | RSS | no | 90 s TTL on `/api/news` | none per feed (**Phase 1**: per-feed backoff on 429/5xx) | CoinDesk rate-limits aggressive pollers |
| Binance Square | internal `bapi/` JSON | no | 90 s TTL | none | **Unofficial, undocumented endpoint** backing binance.com's UI; may change without notice. RSS is the fallback |
| BloFin news | REST | no | 90 s TTL | none | |
| CoinMarketCap | REST | yes (free tier) | strip | none (**Phase 1**: 300/day budget) | ~10k credits/month cap |
| Finnhub | REST | yes (free tier) | on demand | none (**Phase 1**: 60/min budget) | |
| FinBERT (`ProsusAI/finbert`) | local model | no | per brief | — | Downloaded from Hugging Face on first use; runs on CUDA |

## Macro and cross-asset (context only, never tradable)

| Source | Kind | Key | Cadence | Guard | Notes |
|---|---|---|---|---|---|
| FRED CSV (`fredgraph.csv`) | REST | **no** | 30 min (world poller) | — | Primary keyless path; YoY computed by date, not index offset |
| FRED API | REST | optional | fallback | — | |
| Fear & Greed (`alternative.me`) | REST | no | 5 min | — | |
| Yahoo v8 chart (`query1`) | REST | no | 120 s sweep of ~55 symbols | `rate_guard` | Faster sweeps risk a 429 |
| Yahoo gated v10/v7/v1 (`query2`) | REST | **self-minted cookie + crumb** | on demand | `rate_guard` | **ToS / stability risk**: circumvents an access gate and requires a desktop-browser UA. Context-only; kill flag `NEXUS_SOURCE_YAHOO_GATED=0` (Phase 1). `openInterest` is unreliable and is credibility-gated |
| yfinance | library | no | daily bars | — | |
| blockchain.info, Etherscan | REST | Etherscan: yes (free) | slow | — | On-chain context |

## Global events

| Source | Kind | Key | Cadence | Notes |
|---|---|---|---|---|
| USGS M4.5+ (GeoJSON) | REST | no | 5 min | |
| GDACS (RSS) | RSS | no | 5 min | Severity from `<gdacs:alertlevel>` **only** — every item contains the substring "red" |
| NASA EONET v3 | REST | no | 5 min | |
| NOAA SWPC scales | REST | no | 5 min | Space weather |
| BBC World, Al Jazeera, UN News, Federal Reserve, EIA | RSS | no | 5 min | Conflict/policy wire |
| CISA KEV | JSON | no | 5 min | Scores **additions** against the catalogue's trailing 30-day rate, never catalogue size |
| OpenSky (anonymous) | REST | no | 15 min | ~100 credits/day; display-only, never scored |
| worldmonitor.app | REST | optional (`X-WorldMonitor-Key`) | 30 min cache, 1 h cooldown on failure | Sandbox fixtures carry `sample: True` and are refused by the scorer |

**Deliberately excluded** (verified dead from this machine): ReliefWeb (410/403), GDELT DOC (hard 429s), Google-News/Reuters proxy (zero items). A source that silently never answers is worse than none.

## Alerts

Telegram bot (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). **Phase 1** adds dedupe + cooldown and breaker-trip messages.

## Freshness SLAs (target, enforced by `staleness.py` once wired)

| Stream | Stale after |
|---|---|
| Binance trades / book | 30 s |
| OKX / MEXC book | 120 s (degraded, not outage) |
| OI / funding | 5 min |
| News | 15 min |
| World board / geo | 30 min |
| FRED macro | 24 h |
