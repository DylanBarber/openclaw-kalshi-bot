#!/usr/bin/env python3
"""
Test 4: Orders, Positions & Fills
──────────────────────────────────
Tests the portfolio endpoints — orders, positions, fills, balance.
Does NOT place any orders.

Usage:
    python testing/test_orders.py
    python testing/test_orders.py --ticker KXBTC-26FEB14-T50050
"""

import argparse
from _common import make_client, pp, section

parser = argparse.ArgumentParser(description="Test Kalshi portfolio endpoints")
parser.add_argument("--ticker", default=None, help="Filter by market ticker")
args = parser.parse_args()

section("TEST: Portfolio Endpoints")

client = make_client()

# ── Balance ───────────────────────────────────────────────────────────────
print("  Fetching balance...")
try:
    resp = client.get_balance()
    pp(resp, "Balance")
except Exception as e:
    print(f"  FAILED: {e}")

# ── Orders ────────────────────────────────────────────────────────────────
print("\n  Fetching orders...")
try:
    kwargs = {"limit": 10}
    if args.ticker:
        kwargs["ticker"] = args.ticker
    resp = client.get_orders(**kwargs)
    orders = resp.orders or []
    print(f"  Found {len(orders)} order(s)")
    for o in orders[:5]:
        oid = getattr(o, "order_id", "?")
        ticker = getattr(o, "ticker", "?")
        status = getattr(o, "status", "?")
        side = getattr(o, "side", "?")
        action = getattr(o, "action", "?")
        price = getattr(o, "yes_price", None) or getattr(o, "no_price", None)
        count = getattr(o, "remaining_count", "?")
        print(f"    {oid[:12]}...  {ticker}  {action} {side}  {count}x @{price}¢  [{status}]")
    if orders:
        pp(orders[0], f"Full detail of first order")
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()

# ── Positions ─────────────────────────────────────────────────────────────
print("\n  Fetching positions...")
try:
    kwargs = {"limit": 20}
    if args.ticker:
        kwargs["ticker"] = args.ticker
    resp = client.get_positions(**kwargs)
    positions = getattr(resp, "market_positions", None) or getattr(resp, "positions", None) or []
    print(f"  Found {len(positions)} position(s)")
    for p in positions[:10]:
        ticker = getattr(p, "ticker", getattr(p, "market_ticker", "?"))
        qty = getattr(p, "total_traded", getattr(p, "position", "?"))
        side = getattr(p, "side", "?")
        print(f"    {ticker}  {side}  qty={qty}")
    if positions:
        pp(positions[0], "Full detail of first position")
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()

# ── Fills ─────────────────────────────────────────────────────────────────
print("\n  Fetching recent fills...")
try:
    kwargs = {"limit": 10}
    if args.ticker:
        kwargs["ticker"] = args.ticker
    resp = client.get_fills(**kwargs)
    fills = resp.fills or []
    print(f"  Found {len(fills)} fill(s)")
    for f in fills[:5]:
        ticker = getattr(f, "ticker", "?")
        side = getattr(f, "side", "?")
        action = getattr(f, "action", "?")
        price = getattr(f, "yes_price", None) or getattr(f, "no_price", None)
        count = getattr(f, "count", "?")
        ts = getattr(f, "created_time", "?")
        print(f"    {ticker}  {action} {side}  {count}x @{price}¢  {ts}")
    if fills:
        pp(fills[0], "Full detail of first fill")
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback; traceback.print_exc()

print("\n  Done.")
