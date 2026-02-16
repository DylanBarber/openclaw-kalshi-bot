#!/usr/bin/env python3
"""
Test the trading-api.kalshi.com host with authenticated requests.
"""

import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path

# Load .env
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("KALSHI_API_KEY_ID", "")
KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")

# Try both hosts
ELECTIONS_HOST = "https://api.elections.kalshi.com/trade-api/v2"
TRADING_HOST = "https://trading-api.kalshi.com/trade-api/v2"


def sign_request(method, path, timestamp_ms):
    """RSA-PSS signing for Kalshi API auth."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        print("  ERROR: cryptography not installed. pip install cryptography")
        sys.exit(1)

    key_data = Path(KEY_PATH).read_bytes()
    private_key = serialization.load_pem_private_key(key_data, password=None)

    msg = f"{timestamp_ms}{method}{path}".encode()
    sig = private_key.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def authed_get(host, path):
    url = f"{host}{path}"
    ts = str(int(time.time() * 1000))
    sig = sign_request("GET", path, ts)
    req = urllib.request.Request(url)
    req.add_header("KALSHI-ACCESS-KEY", API_KEY)
    req.add_header("KALSHI-ACCESS-SIGNATURE", sig)
    req.add_header("KALSHI-ACCESS-TIMESTAMP", ts)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {e.reason}", "body": body}
    except Exception as e:
        return {"error": str(e)}


def unauthed_get(host, path):
    url = f"{host}{path}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {e.reason}", "body": body}
    except Exception as e:
        return {"error": str(e)}


print("=" * 70)
print("  Comparing elections vs trading-api hosts")
print("=" * 70)
print(f"  API key: {API_KEY[:8]}...{API_KEY[-4:]}")
print(f"  Key path: {KEY_PATH}")

tests = [
    ("/exchange/status", False),
    ("/portfolio/balance", True),
    ("/markets?limit=5", True),
    ("/markets/KXDEELRIP-40-DEEL", True),
    ("/markets/KXDEELRIP-40-DEEL/orderbook?depth=5", False),
    ("/markets/KXBTC-26FEB16-B97000", True),
    ("/markets/KXBTC-26FEB16-B97000/orderbook?depth=5", False),
]

for path, needs_auth in tests:
    print(f"\n  --- {path} ---")
    for host_name, host_url in [("elections", ELECTIONS_HOST), ("trading", TRADING_HOST)]:
        if needs_auth:
            data = authed_get(host_url, path)
        else:
            data = unauthed_get(host_url, path)
        
        err = data.get("error")
        if err:
            print(f"    {host_name:<12s} ERROR: {err}")
            body = data.get("body", "")
            if body:
                print(f"    {' ' * 12} body: {body[:120]}")
        else:
            # Summarize
            summary = json.dumps(data, default=str)
            if len(summary) > 150:
                summary = summary[:150] + "..."
            print(f"    {host_name:<12s} OK: {summary}")

# Deep dive: list markets on trading-api
print("\n" + "=" * 70)
print("  Market listing comparison")
print("=" * 70)
for host_name, host_url in [("elections", ELECTIONS_HOST), ("trading", TRADING_HOST)]:
    data = authed_get(host_url, "/markets?limit=20")
    markets = data.get("markets", [])
    if data.get("error"):
        print(f"\n  {host_name}: ERROR {data.get('error')}")
        continue
    
    from collections import Counter
    prefixes = Counter(m.get("ticker", "").split("-")[0] for m in markets)
    print(f"\n  {host_name}: {len(markets)} markets")
    print(f"    Prefixes: {dict(prefixes.most_common(10))}")
    for m in markets[:5]:
        t = m.get("ticker", "?")
        vol = m.get("volume", 0) or 0
        status = m.get("status", "?")
        print(f"    {t:<55s} vol={vol:>6d} [{status}]")

print()
