#!/usr/bin/env python3
"""Test external crypto price APIs."""
import json, urllib.request, urllib.error

print("=" * 60)
print("  Testing Crypto Price APIs")
print("=" * 60)

# Test 1: Binance
print("\n  [1] Binance (api.binance.com):")
try:
    url = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    print(f"    BTC: ${float(data['lastPrice']):,.2f}")
    print(f"    24h change: {data['priceChangePercent']}%")
except Exception as e:
    print(f"    ERROR: {e}")

# Test 2: Binance US (if main is geo-blocked)
print("\n  [2] Binance US (api.binance.us):")
try:
    url = "https://api.binance.us/api/v3/ticker/24hr?symbol=BTCUSDT"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    print(f"    BTC: ${float(data['lastPrice']):,.2f}")
except Exception as e:
    print(f"    ERROR: {e}")

# Test 3: CoinGecko
print("\n  [3] CoinGecko:")
try:
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "kalshi-bot/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    btc = data.get("bitcoin", {})
    print(f"    BTC: ${btc.get('usd', 0):,.2f}")
    print(f"    24h change: {btc.get('usd_24h_change', 0):.2f}%")
except Exception as e:
    print(f"    ERROR: {e}")

# Test 4: CryptoCompare (no key needed for basic)
print("\n  [4] CryptoCompare:")
try:
    url = "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    print(f"    BTC: ${data.get('USD', 0):,.2f}")
except Exception as e:
    print(f"    ERROR: {e}")

# Test 5: Coinbase
print("\n  [5] Coinbase:")
try:
    url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    amount = data.get("data", {}).get("amount", "0")
    print(f"    BTC: ${float(amount):,.2f}")
except Exception as e:
    print(f"    ERROR: {e}")
