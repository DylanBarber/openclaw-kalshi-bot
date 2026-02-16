#!/usr/bin/env python3
"""Raw HTTP positions fetch with proper auth signing."""

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
HOST = "https://api.elections.kalshi.com/trade-api/v2"

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def sign_request(method, path, timestamp_ms):
    key_data = Path(KEY_PATH).read_bytes()
    private_key = serialization.load_pem_private_key(key_data, password=None)
    msg = f"{timestamp_ms}{method}{path}".encode()
    sig = private_key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def authed_get(path):
    url = f"{HOST}{path}"
    ts = str(int(time.time() * 1000))
    sig = sign_request("GET", path, ts)
    req = urllib.request.Request(url)
    req.add_header("KALSHI-ACCESS-KEY", API_KEY)
    req.add_header("KALSHI-ACCESS-SIGNATURE", sig)
    req.add_header("KALSHI-ACCESS-TIMESTAMP", ts)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
            return json.loads(raw), raw
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {e.reason}", "body": body}, body


print("=" * 70)
print("  Raw HTTP Positions Debug")
print("=" * 70)
print(f"  API key: {API_KEY[:8]}...{API_KEY[-4:]}")

# Test various position endpoints
paths = [
    "/portfolio/positions",
    "/portfolio/positions?limit=100",
    "/portfolio/positions?limit=100&settlement_status=unsettled",
    "/portfolio/positions?limit=100&count_filter=has_position",
    "/portfolio/positions?limit=100&settlement_status=all",
]

for path in paths:
    print(f"\n  GET {path}")
    data, raw = authed_get(path)
    if data.get("error"):
        print(f"    ERROR: {data.get('error')}")
        print(f"    Body: {data.get('body', '')[:200]}")
    else:
        # Check response structure
        print(f"    Response keys: {list(data.keys())}")
        for k, v in data.items():
            if isinstance(v, list):
                print(f"    '{k}': list of {len(v)} items")
                if v:
                    if isinstance(v[0], dict):
                        print(f"      First item keys: {list(v[0].keys())}")
                        print(f"      First item: {json.dumps(v[0], indent=4, default=str)[:500]}")
                    else:
                        print(f"      First item: {v[0]}")
            else:
                print(f"    '{k}': {str(v)[:100]}")

# Also check orders (which works) for comparison
print(f"\n  GET /portfolio/orders?limit=5&status=resting (for comparison)")
data, raw = authed_get("/portfolio/orders?limit=5&status=resting")
if data.get("error"):
    print(f"    ERROR: {data.get('error')}")
else:
    print(f"    Response keys: {list(data.keys())}")
    orders = data.get("orders", [])
    print(f"    Orders: {len(orders)}")
    if orders:
        print(f"    First order keys: {list(orders[0].keys())}")
        tickers = [o.get("ticker", "?") for o in orders]
        print(f"    Tickers: {tickers}")

print()
