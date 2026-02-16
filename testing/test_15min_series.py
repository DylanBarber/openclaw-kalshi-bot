#!/usr/bin/env python3
"""Explore the /series endpoint for crypto 15-minute markets."""
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

# ── 1. Explore /series/KXBTC ──
print("=" * 70)
print("  /series/KXBTC")
print("=" * 70)
data = _fetch_json_raw(f"{HOST}/series/KXBTC")
if data:
    print(json.dumps(data, indent=2, default=str)[:3000])

# ── 2. Try other crypto series tickers ──
print("\n" + "=" * 70)
print("  Trying various series tickers")
print("=" * 70)
series_tickers = [
    "KXBTC", "KXETH", "KXSOL", "KXDOGE", "KXXRP",
    "KXBTCUD", "KXETHUD", "KXSOLUD", "KXXRPUD",
    "KXBTC15", "KXETH15", "KXSOL15",
    "KXBTCUPDOWN", "KXBTC-15MIN",
    "BTCUD", "ETHUD", "SOLUD",
    "KXBTC-S", "KXBTC-15",
    "KXBTCUD15",
]

for st in series_tickers:
    data = _fetch_json_raw(f"{HOST}/series/{st}")
    if data and data.get("series"):
        s = data["series"]
        title = s.get("title", "")
        freq = s.get("frequency", "")
        cat = s.get("category", "")
        tags = s.get("tags", [])
        print(f"  FOUND: {st}")
        print(f"    Title:     {title}")
        print(f"    Frequency: {freq}")
        print(f"    Category:  {cat}")
        print(f"    Tags:      {tags}")

# ── 3. If KXBTC series has child events, list them ──
print("\n" + "=" * 70)
print("  KXBTC series child events")
print("=" * 70)
data = _fetch_json_raw(f"{HOST}/series/KXBTC")
if data and data.get("series"):
    series = data["series"]
    # Check for event tickers within the series
    print(f"  Series keys: {list(series.keys())}")
    print(f"  Full series data:")
    print(json.dumps(series, indent=2, default=str)[:2000])

# ── 4. Try events with series_ticker filter ──
print("\n" + "=" * 70)
print("  Events with series_ticker=KXBTC")
print("=" * 70)
data = _fetch_json_raw(f"{HOST}/events?series_ticker=KXBTC&limit=20")
if data:
    events = data.get("events", [])
    print(f"  Found {len(events)} events")
    for ev in events[:10]:
        et = ev.get("event_ticker", "")
        title = ev.get("title", "")[:60]
        cat = ev.get("category", "")
        status = ev.get("status", "")
        print(f"    {et:<40s} [{cat}] [{status}] {title}")

# ── 5. Also try events with series_ticker for the UD variants ──
for st in ["KXBTCUD", "KXBTC15", "KXBTCUPDOWN", "KXETH", "KXSOL"]:
    data = _fetch_json_raw(f"{HOST}/events?series_ticker={st}&limit=5")
    if data and data.get("events"):
        events = data["events"]
        print(f"\n  Events for series={st}: {len(events)}")
        for ev in events[:3]:
            et = ev.get("event_ticker", "")
            title = ev.get("title", "")[:55]
            print(f"    {et:<40s} {title}")

# ── 6. List ALL series tickers ──
print("\n" + "=" * 70)
print("  Listing all series (if endpoint exists)")
print("=" * 70)
data = _fetch_json_raw(f"{HOST}/series?limit=100")
if data:
    if isinstance(data, dict):
        print(f"  Keys: {list(data.keys())}")
        series_list = data.get("series", [])
        if isinstance(series_list, list):
            for s in series_list[:20]:
                st = s.get("ticker", "") if isinstance(s, dict) else str(s)
                title = s.get("title", "") if isinstance(s, dict) else ""
                print(f"    {st:<30s} {title[:50]}")
        else:
            print(f"  series type: {type(series_list)}")
            print(f"  {json.dumps(series_list, indent=2, default=str)[:500]}")
    else:
        print(f"  Response type: {type(data)}")
else:
    print("  /series listing not available")

print("\nDone.")
