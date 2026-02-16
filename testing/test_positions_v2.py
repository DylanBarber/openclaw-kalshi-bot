#!/usr/bin/env python3
"""Intercept at the REST client level to see raw response body."""

import json
import os
import sys
from pathlib import Path

scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, scripts_dir)

env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from runner import load_config, build_client
cfg = load_config()
client = build_client(cfg)

print("=" * 70)
print("  REST-level Intercept")
print("=" * 70)

# Patch at the rest_client.request level
rest = client.api_client.rest_client
original_request = rest.request

def logging_request(method, url, **kwargs):
    print(f"\n  >>> {method} {url}")
    resp = original_request(method, url, **kwargs)
    # RESTResponse wraps urllib3 response
    raw_data = resp.data
    if isinstance(raw_data, bytes):
        raw_data = raw_data.decode("utf-8", errors="replace")
    print(f"  <<< Status: {resp.status}")
    print(f"  <<< Body ({len(raw_data)} chars): {raw_data[:2000]}")
    return resp

rest.request = logging_request

# Test 1: get_positions
print("\n  === get_positions(limit=100) ===")
try:
    resp = client.get_positions(limit=100)
    print(f"  Result: positions={resp.positions}, cursor='{resp.cursor}'")
except Exception as e:
    print(f"  ERROR: {e}")

# Test 2: get_orders (for comparison)
print("\n  === get_orders(status='resting', limit=5) ===")
try:
    resp2 = client.get_orders(status="resting", limit=5)
    orders = getattr(resp2, "orders", []) or []
    print(f"  Result: {len(orders)} orders")
    if orders:
        for o in orders[:3]:
            print(f"    {getattr(o, 'ticker', '?')} {getattr(o, 'side', '?')} {getattr(o, 'action', '?')} {getattr(o, 'yes_price', '?')}c x{getattr(o, 'remaining_count', '?')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Test 3: get_positions with event_ticker (if you know one)
# First get a ticker from orders
print("\n  === Looking for known tickers from fills ===")
try:
    fills_resp = client.get_fills(limit=5)
    fills = getattr(fills_resp, "fills", []) or []
    print(f"  Found {len(fills)} fills")
    tickers = set()
    for f in fills:
        t = getattr(f, "ticker", None)
        if t:
            tickers.add(t)
            print(f"    Fill: {t} {getattr(f, 'side', '?')} {getattr(f, 'action', '?')} {getattr(f, 'count', '?')}x @ {getattr(f, 'yes_price', '?')}c")
except Exception as e:
    print(f"  ERROR: {e}")

# If we found tickers, try fetching positions for them
if tickers:
    for t in list(tickers)[:2]:
        print(f"\n  === get_positions(ticker='{t}') ===")
        try:
            resp3 = client.get_positions(ticker=t)
            print(f"  Result: positions={resp3.positions}, cursor='{resp3.cursor}'")
        except Exception as e:
            print(f"  ERROR: {e}")

rest.request = original_request
print()
