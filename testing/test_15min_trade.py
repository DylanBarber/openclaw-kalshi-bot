#!/usr/bin/env python3
"""Check if 15-minute crypto markets are tradeable (have L2, can place orders)."""
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

# ── 1. Find ALL 15-minute crypto series ──
print("=" * 70)
print("  15-Minute Crypto Series")
print("=" * 70)

fifteen_series = []
data = _fetch_json_raw(f"{HOST}/series?category=Crypto&limit=200")
if data:
    for s in data.get("series", []):
        if isinstance(s, dict) and s.get("frequency") == "fifteen_min":
            fifteen_series.append(s)
            print(f"  {s['ticker']:<20s} {s.get('title','')}")

# ── 2. Get events for each 15-minute series ──
print("\n" + "=" * 70)
print("  Events for 15-minute series")
print("=" * 70)

for s in fifteen_series:
    st = s["ticker"]
    data = _fetch_json_raw(f"{HOST}/events?series_ticker={st}&limit=10")
    if data:
        events = data.get("events", [])
        print(f"\n  {st}: {len(events)} event(s)")
        for ev in events[:5]:
            et = ev.get("event_ticker", "")
            title = ev.get("title", "")
            status = ev.get("status", "")
            print(f"    {et:<40s} [{status}] {title}")

# ── 3. Deep dive into BTC 15M events - get the actual markets ──
print("\n" + "=" * 70)
print("  KXBTC15M event markets detail")
print("=" * 70)

data = _fetch_json_raw(f"{HOST}/events?series_ticker=KXBTC15M&limit=5")
if data:
    for ev in data.get("events", [])[:3]:
        et = ev.get("event_ticker", "")
        print(f"\n  Event: {et} - {ev.get('title','')}")
        
        ev_data = _fetch_json_raw(f"{HOST}/events/{et}")
        if ev_data:
            markets = ev_data.get("markets", [])
            print(f"  Markets: {len(markets)}")
            for m in markets:
                ticker = m.get("ticker", "")
                title = m.get("title", "")[:50]
                yb = m.get("yes_bid", 0) or 0
                ya = m.get("yes_ask", 0) or 0
                vol = m.get("volume", 0) or 0
                status = m.get("status", "")
                subtitle = m.get("subtitle", "")[:30]
                close_time = m.get("close_time", "")
                print(f"    {ticker:<40s} bid={yb:>2d} ask={ya:>3d} vol={vol:>6d} [{status}] {title}")
                
                # Check orderbook
                ob_data = _fetch_json_raw(f"{HOST}/markets/{ticker}/orderbook?depth=5")
                if ob_data:
                    book = ob_data.get("orderbook", {})
                    yes = book.get("yes") or []
                    no = book.get("no") or []
                    if yes or no:
                        print(f"      L2: YES={len(yes)} levels, NO={len(no)} levels")
                        if yes:
                            print(f"      Best YES bid: {yes[-1]}")
                        if no:
                            print(f"      Best NO bid: {no[-1]}")
                    else:
                        print(f"      L2: empty")

# ── 4. Also check other 15-min series (ETH, SOL, XRP) ──
print("\n" + "=" * 70)
print("  Other 15-minute series events")  
print("=" * 70)

for series_check in ["KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]:
    data = _fetch_json_raw(f"{HOST}/series/{series_check}")
    if data and data.get("series"):
        s = data["series"]
        print(f"\n  {series_check}: {s.get('title')} (freq={s.get('frequency')})")
        ev_data = _fetch_json_raw(f"{HOST}/events?series_ticker={series_check}&limit=3")
        if ev_data:
            events = ev_data.get("events", [])
            print(f"    Events: {len(events)}")
            for ev in events[:2]:
                et = ev.get("event_ticker", "")
                print(f"    {et:<40s} {ev.get('title','')[:50]}")
    else:
        data2 = _fetch_json_raw(f"{HOST}/events?series_ticker={series_check}&limit=3")
        if data2 and data2.get("events"):
            print(f"\n  {series_check}: (no series info, but has events)")
            for ev in data2["events"][:2]:
                print(f"    {ev.get('event_ticker'):<40s} {ev.get('title','')[:50]}")

# ── 5. Summary of ALL crypto series by frequency ──
print("\n" + "=" * 70)
print("  All crypto series by frequency")
print("=" * 70)

freq_map = {}
data = _fetch_json_raw(f"{HOST}/series?category=Crypto&limit=300")
if data:
    for s in data.get("series", []):
        if isinstance(s, dict):
            f = s.get("frequency", "unknown")
            if f not in freq_map:
                freq_map[f] = []
            freq_map[f].append(s.get("ticker", "") + " - " + s.get("title", ""))

for freq in sorted(freq_map.keys()):
    items = freq_map[freq]
    print(f"\n  {freq} ({len(items)}):")
    for item in items[:8]:
        print(f"    {item}")
    if len(items) > 8:
        print(f"    ... and {len(items)-8} more")

print("\nDone.")
