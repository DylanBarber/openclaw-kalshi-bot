#!/usr/bin/env python3
"""Deep dive into crypto event markets and find 15-minute tickers."""
import os, sys, json
from pathlib import Path

env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from runner import _fetch_json_raw

HOST = "https://api.elections.kalshi.com/trade-api/v2"

# ── 1. Get CURRENT/UPCOMING BTC hourly events and their markets ──
print("=" * 70)
print("  Current KXBTC events and their markets")
print("=" * 70)

data = _fetch_json_raw(f"{HOST}/events?series_ticker=KXBTC&limit=5")
if data:
    for ev in data.get("events", [])[:3]:
        et = ev.get("event_ticker", "")
        title = ev.get("title", "")
        print(f"\n  Event: {et}")
        print(f"  Title: {title}")
        
        # Fetch full event with markets
        ev_data = _fetch_json_raw(f"{HOST}/events/{et}")
        if ev_data:
            markets = ev_data.get("markets", [])
            print(f"  Markets: {len(markets)}")
            for m in markets[:8]:
                ticker = m.get("ticker", "")
                mtitle = m.get("title", "")[:50]
                yb = m.get("yes_bid", 0) or 0
                ya = m.get("yes_ask", 0) or 0
                vol = m.get("volume", 0) or 0
                status = m.get("status", "")
                print(f"    {ticker:<45s} bid={yb:>2d} ask={ya:>3d} vol={vol:>6d} [{status}] {mtitle}")

# ── 2. Search for 15-minute specific series ──
print("\n" + "=" * 70)
print("  Searching for 15-minute series tickers")
print("=" * 70)

fifteen_min_series = [
    "KXBTC15", "KXBTC-15", "KXBTC15M", "KXBTC-15M",
    "KXBTCUD", "KXBTC-UD", "KXBTCUPDOWN",
    "KXBTC15MIN", "KXBTC-15MIN",
    "KXBTCPM", "KXBTC-PM",  # price movement?
    "KXBTCSHORT", "KXBTC-SHORT",
    "BTCUD", "BTC15", "BTCUPDOWN",
    "KXBTCD", "KXBTCF", "KXBTCQ",  # daily/fifteen/quarter?
    "KXBTCM15",
    "KXETH15", "KXSOL15", "KXXRP15",
    "KXBTCUD15", "KXBTCUD-15",
]

for st in fifteen_min_series:
    data = _fetch_json_raw(f"{HOST}/series/{st}")
    if data and data.get("series"):
        s = data["series"]
        print(f"  FOUND: {st}")
        print(f"    Title: {s.get('title')}, Freq: {s.get('frequency')}, Cat: {s.get('category')}")
    
    # Also try as events filter
    data2 = _fetch_json_raw(f"{HOST}/events?series_ticker={st}&limit=3")
    if data2 and data2.get("events"):
        evs = data2["events"]
        if evs:
            print(f"  EVENTS for {st}: {len(evs)}")
            for ev in evs[:2]:
                print(f"    {ev.get('event_ticker'):<40s} {ev.get('title','')[:50]}")

# ── 3. Check the first BTC event for orderbook data ──
print("\n" + "=" * 70)
print("  Checking orderbook for current BTC event markets")
print("=" * 70)

data = _fetch_json_raw(f"{HOST}/events?series_ticker=KXBTC&limit=2")
if data and data.get("events"):
    ev = data["events"][0]
    et = ev.get("event_ticker", "")
    ev_data = _fetch_json_raw(f"{HOST}/events/{et}")
    if ev_data:
        markets = ev_data.get("markets", [])
        for m in markets[:3]:
            ticker = m.get("ticker", "")
            ob = _fetch_json_raw(f"{HOST}/markets/{ticker}/orderbook?depth=5")
            if ob:
                book = ob.get("orderbook", {})
                yes = book.get("yes") or []
                no = book.get("no") or []
                print(f"  {ticker}")
                print(f"    YES levels: {len(yes)}  NO levels: {len(no)}")
                if yes:
                    print(f"    Best YES: {yes[-1] if yes else 'none'}")
                if no:
                    print(f"    Best NO:  {no[-1] if no else 'none'}")

# ── 4. Try fetching the Kalshi API docs for market structure ──
print("\n" + "=" * 70)
print("  Trying /series listing filtered by crypto")
print("=" * 70)

# There's no direct crypto filter, but let's try category
for cat_try in ["Crypto", "crypto"]:
    data = _fetch_json_raw(f"{HOST}/series?category={cat_try}&limit=50")
    if data:
        series_list = data.get("series", [])
        if isinstance(series_list, list) and series_list:
            print(f"  Found {len(series_list)} series for category={cat_try}")
            for s in series_list[:20]:
                if isinstance(s, dict):
                    print(f"    {s.get('ticker',''):<25s} freq={s.get('frequency',''):<10s} {s.get('title','')[:40]}")

print("\nDone.")
