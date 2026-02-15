#!/usr/bin/env python3
"""
Test 3: Orderbook — the problem endpoint
─────────────────────────────────────────
Fetches the orderbook at multiple levels of abstraction:
  1) Raw HTTP request (bypasses SDK entirely)
  2) SDK get_market_orderbook (so you can see the deserialized object)
  3) Our _extract_ob_levels / _level_to_cents helpers

This lets you pinpoint exactly where the data goes missing.

Usage:
    python testing/test_orderbook.py TICKER
    python testing/test_orderbook.py KXBTC-26FEB14-T50050
    python testing/test_orderbook.py KXBTC-26FEB14-T50050 --depth 10
"""

import argparse
import json
import os
import sys
from datetime import datetime

from _common import make_client, pp, section, DEFAULT_HOST

parser = argparse.ArgumentParser(description="Test Kalshi orderbook endpoint")
parser.add_argument("ticker", help="Market ticker to fetch orderbook for")
parser.add_argument("--depth", type=int, default=5, help="Orderbook depth (default: 5)")
args = parser.parse_args()

section(f"TEST: Orderbook for {args.ticker}")


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 1: Raw HTTP — bypass the SDK entirely
# ═══════════════════════════════════════════════════════════════════════════
print("  [Layer 1] Raw HTTP request (no SDK)...")
host = os.environ.get("KALSHI_HOST", DEFAULT_HOST)
url = f"{host}/markets/{args.ticker}/orderbook?depth={args.depth}"
print(f"  GET {url}")

try:
    import requests
    raw_resp = requests.get(url)
    print(f"  HTTP {raw_resp.status_code}  Content-Length: {len(raw_resp.content)}")
    print(f"  Headers: Content-Type={raw_resp.headers.get('Content-Type')}")

    try:
        raw_json = raw_resp.json()
        print(f"\n  Raw JSON response:")
        print(json.dumps(raw_json, indent=2, default=str))

        # Check what keys are in the orderbook
        ob = raw_json.get("orderbook", raw_json)
        print(f"\n  Orderbook keys: {list(ob.keys()) if isinstance(ob, dict) else type(ob).__name__}")
        yes_data = ob.get("yes") or ob.get("true") or ob.get("var_true")
        no_data = ob.get("no") or ob.get("false") or ob.get("var_false")
        print(f"  YES levels: {len(yes_data) if yes_data else 0}")
        print(f"  NO  levels: {len(no_data) if no_data else 0}")

        if yes_data:
            print(f"  First YES level: {yes_data[0]}")
        if no_data:
            print(f"  First NO  level: {no_data[0]}")

    except json.JSONDecodeError:
        print(f"  Response is not JSON: {raw_resp.text[:500]}")

except ImportError:
    print("  SKIPPED — 'requests' not installed (pip install requests)")
except Exception as e:
    print(f"  FAILED: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 2: SDK get_market_orderbook
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n\n  [Layer 2] SDK get_market_orderbook('{args.ticker}', depth={args.depth})...")

client = make_client()

try:
    resp = client.get_market_orderbook(args.ticker, depth=args.depth)

    # Print the response object type
    print(f"  Response type: {type(resp).__name__}")

    # Try to get the inner orderbook
    ob = resp.orderbook if hasattr(resp, "orderbook") else resp
    print(f"  Orderbook type: {type(ob).__name__}")

    # Print all attributes on the orderbook object
    if hasattr(ob, "__dict__"):
        print(f"  Orderbook __dict__ keys: {list(ob.__dict__.keys())}")
        for k, v in ob.__dict__.items():
            val_preview = repr(v)[:200] if v is not None else "None"
            print(f"    .{k} = {val_preview}")

    # Check specific attributes
    for attr in ["var_true", "var_false", "yes", "no", "true", "false"]:
        val = getattr(ob, attr, "MISSING")
        if val != "MISSING":
            if val is None:
                print(f"  ob.{attr} = None")
            elif isinstance(val, list):
                print(f"  ob.{attr} = list[{len(val)}]")
                if val:
                    item = val[0]
                    print(f"    [0] type={type(item).__name__}")
                    if hasattr(item, "__dict__"):
                        print(f"    [0] __dict__={item.__dict__}")
                    else:
                        print(f"    [0] value={item}")

    # to_dict fallback
    if hasattr(ob, "to_dict"):
        d = ob.to_dict()
        print(f"\n  ob.to_dict() keys: {list(d.keys())}")
        print(f"  ob.to_dict():")
        print(json.dumps(d, indent=2, default=str))

except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 3: Our parsing helpers
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n\n  [Layer 3] Our _extract_ob_levels + _level_to_cents helpers...")

# Import from runner.py
sys.path.insert(0, str((sys.path[0] and __import__("pathlib").Path(sys.path[0]) or __import__("pathlib").Path(__file__).parent).parent / "scripts"))
try:
    from runner import _extract_ob_levels, _level_to_cents

    resp = client.get_market_orderbook(args.ticker, depth=args.depth)
    ob = resp.orderbook if hasattr(resp, "orderbook") else resp

    yes_raw, no_raw = _extract_ob_levels(ob)
    print(f"  _extract_ob_levels → YES: {len(yes_raw)}, NO: {len(no_raw)}")

    if yes_raw:
        yes_cents = [_level_to_cents(l) for l in yes_raw]
        yes_cents.sort(key=lambda x: x[0], reverse=True)
        print(f"\n  YES levels (cents, qty):")
        for p, q in yes_cents[:10]:
            print(f"    {p}¢ x {q}")
    else:
        print("  YES: empty")

    if no_raw:
        no_cents = [_level_to_cents(l) for l in no_raw]
        no_cents.sort(key=lambda x: x[0], reverse=True)
        print(f"\n  NO levels (cents, qty):")
        for p, q in no_cents[:10]:
            print(f"    {p}¢ x {q}")

        # Derived YES asks
        yes_asks = sorted([(100 - p, q) for p, q in no_cents], key=lambda x: x[0])
        print(f"\n  Derived YES asks (100 - NO bid):")
        for p, q in yes_asks[:10]:
            print(f"    {p}¢ x {q}")
    else:
        print("  NO: empty")

    if yes_raw and no_raw:
        best_bid = max(p for p, _ in [_level_to_cents(l) for l in yes_raw])
        best_ask = min(100 - p for p, _ in [_level_to_cents(l) for l in no_raw])
        spread = best_ask - best_bid
        print(f"\n  Best YES bid: {best_bid}¢")
        print(f"  Best YES ask: {best_ask}¢")
        print(f"  Spread: {spread}¢")

except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()


print(f"\n{'='*60}")
print("  DONE")
print(f"{'='*60}")
