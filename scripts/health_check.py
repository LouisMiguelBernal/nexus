"""
Nexus - Health Check Script
Verify all API connections and system readiness.
Run: python scripts/health_check.py
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx


async def main():
    print("=" * 60)
    print("NEXUS HEALTH CHECK")
    print("=" * 60)

    checks = {}

    # 1. Ollama / Gemma 4
    print("\n[1] Ollama + Gemma 4 (gemma4:e4b)...")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in resp.json().get("models", [])]
            if any("gemma4" in m for m in models):
                print(f"  OK - Models: {models}")
                checks["ollama"] = True
            else:
                print(f"  WARNING - Ollama running but gemma4 not found. Models: {models}")
                checks["ollama"] = False
    except Exception as e:
        print(f"  FAIL - {e}")
        checks["ollama"] = False

    # 2. Binance Futures API (public, no key needed)
    print("\n[2] Binance Futures API...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": "BTCUSDT"})
            price = resp.json().get("price", "?")
            print(f"  OK - BTCUSDT: ${float(price):,.2f}")
            checks["binance"] = True
    except Exception as e:
        print(f"  FAIL - {e}")
        checks["binance"] = False

    # 3. Bybit V5 API
    print("\n[3] Bybit V5 API...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.bybit.com/v5/market/tickers", params={"category": "linear", "symbol": "BTCUSDT"})
            data = resp.json()
            items = data.get("result", {}).get("list", [])
            if items:
                print(f"  OK - BTCUSDT last: ${float(items[0].get('lastPrice', 0)):,.2f}")
                checks["bybit"] = True
            else:
                print("  WARNING - No data returned")
                checks["bybit"] = False
    except Exception as e:
        print(f"  FAIL - {e}")
        checks["bybit"] = False

    # 4. OKX V5 API
    print("\n[4] OKX V5 API...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://www.okx.com/api/v5/market/ticker", params={"instId": "BTC-USDT-SWAP"})
            data = resp.json()
            items = data.get("data", [])
            if items:
                print(f"  OK - BTC-USDT-SWAP last: ${float(items[0].get('last', 0)):,.2f}")
                checks["okx"] = True
            else:
                print("  WARNING - No data returned")
                checks["okx"] = False
    except Exception as e:
        print(f"  FAIL - {e}")
        checks["okx"] = False

    # 5. Fear & Greed Index
    print("\n[5] Fear & Greed Index...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.alternative.me/fng/")
            data = resp.json()
            item = data.get("data", [{}])[0]
            print(f"  OK - {item.get('value_classification', '?')}: {item.get('value', '?')}")
            checks["fear_greed"] = True
    except Exception as e:
        print(f"  FAIL - {e}")
        checks["fear_greed"] = False

    # 6. Deribit
    print("\n[6] Deribit Options API...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://www.deribit.com/api/v2/public/get_index_price", params={"index_name": "btc_usd"})
            data = resp.json()
            price = data.get("result", {}).get("index_price", 0)
            print(f"  OK - BTC index: ${price:,.2f}")
            checks["deribit"] = True
    except Exception as e:
        print(f"  FAIL - {e}")
        checks["deribit"] = False

    # 7. API keys check
    print("\n[7] API Keys (.env)...")
    from backend.config import (
        FRED_API_KEY, FINNHUB_API_KEY, CRYPTOPANIC_API_KEY,
        TELEGRAM_BOT_TOKEN, BINANCE_API_KEY,
    )
    keys = {
        "FRED": bool(FRED_API_KEY),
        "Finnhub": bool(FINNHUB_API_KEY),
        "CryptoPanic": bool(CRYPTOPANIC_API_KEY),
        "Telegram": bool(TELEGRAM_BOT_TOKEN),
        "Binance": bool(BINANCE_API_KEY),
    }
    for name, has_key in keys.items():
        status = "SET" if has_key else "NOT SET"
        print(f"  {name}: {status}")

    # 8. SQLite
    print("\n[8] SQLite Database...")
    try:
        from backend.storage.db import get_connection
        conn = get_connection()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t["name"] for t in tables]
        print(f"  OK - Tables: {table_names}")
        checks["sqlite"] = True
    except Exception as e:
        print(f"  FAIL - {e}")
        checks["sqlite"] = False

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    print(f"RESULT: {passed}/{total} checks passed")
    if passed == total:
        print("All systems go!")
    else:
        failed = [k for k, v in checks.items() if not v]
        print(f"Failed: {', '.join(failed)}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
