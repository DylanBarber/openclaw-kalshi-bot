#!/usr/bin/env python3
"""
Test 2: Market Search & Detail
──────────────────────────────
Tests get_markets (with and without status filters) and get_market on a
specific ticker.  Prints the raw response so you can see exactly what
the API returns.

Usage:
    python testing/test_markets.py
    python testing/test_markets.py --ticker KXBTC-26FEB14-T50050
    python testing/test_markets.py --query bitcoin
    python testing/test_markets.py --status open
"""

import argparse
from _common import make_client, pp, section

parser = argparse.ArgumentParser(description="Test Kalshi markets endpoints")
parser.add_argument("--ticker", default=None, help="Specific market ticker to fetch")
parser.add_argument("--query", default=None, help="Series ticker to search")
parser.add_argument("--status", default=None,
                    help="Status filter: unopened, open, paused, closed, settled")
parser.add_argument("--limit", type=int, default=5, help="Max markets to return")
args = parser.parse_args()

section("TEST: Markets API")

client = make_client()

# ── get_markets ───────────────────────────────────────────────────────────
print("\n  Testing get_markets()...")

kwargs = {"limit": args.limit}
if args.query:
    kwargs["series_ticker"] = args.query
if args.status:
    kwargs["status"] = args.status

print(f"  Request kwargs: {kwargs}")

try:
    resp = client.get_markets(**kwargs)
    markets = resp.markets or []
    print(f"  Returned {len(markets)} market(s)")

    for i, m in enumerate(markets):
        ticker = getattr(m, "ticker", "?")
        title = getattr(m, "title", "")
        status = getattr(m, "status", "?")
        print(f"\n  [{i+1}] {ticker}  [{status}]  {title}")

    if markets:
        pp(markets[0], f"Full detail of first market: {getattr(markets[0], 'ticker', '?')}")
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()

# ── get_market (single) ──────────────────────────────────────────────────
ticker = args.ticker
if not ticker and 'markets' in dir() and markets:
    ticker = getattr(markets[0], "ticker", None)

if ticker:
    print(f"\n  Testing get_market('{ticker}')...")
    try:
        resp = client.get_market(ticker)
        pp(resp, f"Single market: {ticker}")
    except Exception as e:
        print(f"  FAILED: {e}")
        import traceback; traceback.print_exc()

# ── Test bad status filter to see what error looks like ───────────────────
print("\n  Testing get_markets(status='active') — expected to FAIL...")
try:
    resp = client.get_markets(status="active", limit=1)
    print(f"  Unexpectedly succeeded! Returned {len(resp.markets or [])} market(s)")
except Exception as e:
    err_body = getattr(e, "body", None)
    err_status = getattr(e, "status", None)
    print(f"  Expected error: HTTP {err_status}")
    print(f"  Body: {err_body}")

print("\n  Done.")
