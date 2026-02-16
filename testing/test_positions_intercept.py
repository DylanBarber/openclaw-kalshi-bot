#!/usr/bin/env python3
"""Intercept the SDK's actual HTTP request/response for positions."""

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
print("  SDK Positions Intercept")
print("=" * 70)

# Monkey-patch the api_client to log requests
original = client.api_client.call_api

def logging_call_api(*args, **kwargs):
    print(f"\n  [SDK CALL]")
    print(f"    args: {args[:3]}")  # method, url, etc
    if "header_params" in kwargs:
        print(f"    headers: {list(kwargs['header_params'].keys())}")
    if "query_params" in kwargs:
        print(f"    query: {kwargs['query_params']}")
    resp = original(*args, **kwargs)
    print(f"    response type: {type(resp).__name__}")
    print(f"    response status: {getattr(resp, 'status', '?')}")
    raw = getattr(resp, 'data', None) or getattr(resp, 'body', None)
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode()
        print(f"    response body ({len(raw)} chars): {raw[:1000]}")
    else:
        print(f"    response body: (empty/none)")
    return resp

client.api_client.call_api = logging_call_api

# Test 1: get_positions
print("\n  --- get_positions(limit=100) ---")
try:
    resp = client.get_positions(limit=100)
    print(f"\n  SDK result:")
    print(f"    type: {type(resp).__name__}")
    print(f"    .positions: {resp.positions}")
    print(f"    .cursor: {resp.cursor}")
    if hasattr(resp, "to_dict"):
        print(f"    .to_dict(): {resp.to_dict()}")
except Exception as e:
    print(f"    ERROR: {e}")

# Test 2: get_orders (for comparison since that works)
print("\n  --- get_orders(status='resting', limit=5) ---")
try:
    resp2 = client.get_orders(status="resting", limit=5)
    orders = getattr(resp2, "orders", []) or []
    print(f"\n  SDK result:")
    print(f"    type: {type(resp2).__name__}")
    print(f"    .orders: {len(orders)} items")
    if orders:
        o = orders[0]
        print(f"    First order ticker: {getattr(o, 'ticker', '?')}")
except Exception as e:
    print(f"    ERROR: {e}")

# Restore
client.api_client.call_api = original
print()
