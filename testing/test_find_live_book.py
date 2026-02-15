#!/usr/bin/env python3
"""
Test 5: Find a market with an ACTIVE orderbook
───────────────────────────────────────────────
Searches for non-combo markets with actual volume, then fetches
the orderbook for the most liquid one.  This tells you whether
the API can return real depth at all.

Usage:
    python testing/test_find_live_book.py
    python testing/test_find_live_book.py --series KXBTC
    python testing/test_find_live_book.py --series KXHIGHNY
"""

import argparse
import json
from _common import make_client, pp, section

parser = argparse.ArgumentParser()
parser.add_argument("--series", default=None,
                    help="Series ticker to search (e.g. KXBTC, KXHIGHNY, INX)")
parser.add_argument("--limit", type=int, default=100,
                    help="How many markets to scan (default: 100)")
parser.add_argument("--depth", type=int, default=10,
                    help="Orderbook depth to request")
args = parser.parse_args()

section("Find a market with a live orderbook")

client = make_client()

# ── Step 1: Get markets, filter out combos and zero-volume ────────────────
print("  Scanning for non-combo markets with volume > 0...")

kwargs = {"limit": args.limit, "status": "open"}
if args.series:
    kwargs["series_ticker"] = args.series

try:
    resp = client.get_markets(**kwargs)
except Exception as e:
    print(f"  get_markets failed: {e}")
    print("  Trying without status filter...")
    del kwargs["status"]
    resp = client.get_markets(**kwargs)

markets = resp.markets or []
print(f"  Total returned: {len(markets)}")

# Filter: skip MVE/combo markets, require some volume
candidates = []
for m in markets:
    ticker = getattr(m, "ticker", "")
    volume = getattr(m, "volume", 0) or 0
    volume_24h = getattr(m, "volume_24h", 0) or 0
    status = getattr(m, "status", "")
    yes_bid = getattr(m, "yes_bid", 0) or 0
    yes_ask = getattr(m, "yes_ask", 0) or 0
    title = getattr(m, "title", "")

    # Skip multivariate / combo markets
    if "MVE" in ticker.upper() or "MULTIGAME" in ticker.upper():
        continue

    # Skip markets with zero bid/ask (completely empty)
    if yes_bid == 0 and yes_ask == 0:
        continue

    candidates.append({
        "ticker": ticker,
        "title": title,
        "status": status,
        "volume": volume,
        "volume_24h": volume_24h,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
    })

# Sort by volume descending
candidates.sort(key=lambda x: x["volume_24h"], reverse=True)

print(f"  Non-combo markets with bid/ask > 0: {len(candidates)}")

if not candidates:
    print("\n  No live markets found. Try:")
    print("    python testing/test_find_live_book.py --series KXBTC")
    print("    python testing/test_find_live_book.py --series INX")
    print("    python testing/test_find_live_book.py --series KXHIGHNY")
    exit(0)

print(f"\n  Top 10 by 24h volume:")
for i, c in enumerate(candidates[:10]):
    print(f"    [{i+1}] {c['ticker']:<45s}  bid={c['yes_bid']}  ask={c['yes_ask']}  "
          f"vol24h={c['volume_24h']}  [{c['status']}]")
    print(f"         {c['title'][:80]}")

# ── Step 2: Fetch orderbook for the most liquid market ────────────────────
best = candidates[0]
ticker = best["ticker"]

print(f"\n\n  Fetching orderbook for most liquid market: {ticker}")
print(f"  depth={args.depth}")

try:
    import requests as req_lib
    host = "https://api.elections.kalshi.com/trade-api/v2"
    url = f"{host}/markets/{ticker}/orderbook?depth={args.depth}"
    print(f"\n  [Raw HTTP] GET {url}")
    raw = req_lib.get(url)
    raw_json = raw.json()
    print(f"  HTTP {raw.status_code}")
    print(json.dumps(raw_json, indent=2, default=str))

    ob = raw_json.get("orderbook", {})
    yes_data = ob.get("yes")
    no_data = ob.get("no")

    if yes_data or no_data:
        print(f"\n  SUCCESS — orderbook has data!")
        print(f"  YES levels: {len(yes_data or [])}")
        print(f"  NO  levels: {len(no_data or [])}")
        if yes_data:
            print(f"  Best YES bid: {yes_data[-1]} (last = highest)")
        if no_data:
            print(f"  Best NO  bid: {no_data[-1]} (last = highest)")
            best_no = no_data[-1]
            price = best_no[0] if isinstance(best_no, list) else best_no
            print(f"  Implied YES ask: {100 - int(price)}c")
    else:
        print(f"\n  Orderbook is STILL null/empty for this market.")
        print(f"  This confirms the API does not return depth for this market type.")

        # Try the _dollars variants
        yes_dollars = ob.get("yes_dollars")
        no_dollars = ob.get("no_dollars")
        if yes_dollars or no_dollars:
            print(f"\n  BUT: yes_dollars/no_dollars ARE present!")
            print(f"  yes_dollars: {yes_dollars}")
            print(f"  no_dollars: {no_dollars}")

        # Check orderbook_fp
        ob_fp = raw_json.get("orderbook_fp", {})
        if ob_fp:
            print(f"\n  orderbook_fp: {json.dumps(ob_fp, indent=2, default=str)}")

except ImportError:
    print("  SKIPPED — requests not installed")
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()

# ── Step 3: Also try SDK ─────────────────────────────────────────────────
print(f"\n\n  [SDK] get_market_orderbook('{ticker}', depth={args.depth})...")
try:
    resp = client.get_market_orderbook(ticker, depth=args.depth)
    ob = resp.orderbook if hasattr(resp, "orderbook") else resp

    vt = getattr(ob, "var_true", "MISSING")
    vf = getattr(ob, "var_false", "MISSING")

    if vt and vt != "MISSING":
        print(f"  var_true: {len(vt)} level(s)")
        print(f"    [0] = {vt[0].__dict__ if hasattr(vt[0], '__dict__') else vt[0]}")
    else:
        print(f"  var_true: {vt}")

    if vf and vf != "MISSING":
        print(f"  var_false: {len(vf)} level(s)")
        print(f"    [0] = {vf[0].__dict__ if hasattr(vf[0], '__dict__') else vf[0]}")
    else:
        print(f"  var_false: {vf}")

except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()

print(f"\n{'='*60}")
print("  DONE")
print(f"{'='*60}")
