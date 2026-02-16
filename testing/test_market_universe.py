#!/usr/bin/env python3
"""Map the full market universe visible from the elections API host."""

import json
import urllib.request
import urllib.error
from collections import Counter

HOST = "https://api.elections.kalshi.com/trade-api/v2"


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


# ── 1. Paginate ALL events ──
print("=" * 70)
print("  Market Universe on api.elections.kalshi.com")
print("=" * 70)

print("\n  [1] Fetching ALL events...")
all_events = []
cursor = None
for page in range(20):
    url = f"{HOST}/events?limit=100"
    if cursor:
        url += f"&cursor={cursor}"
    data = fetch(url)
    evts = data.get("events", [])
    if not evts:
        break
    all_events.extend(evts)
    cursor = data.get("cursor")
    if not cursor:
        break

print(f"  Total events: {len(all_events)}")

# Categorize
prefix_counts = Counter()
prefix_examples = {}
for e in all_events:
    et = e.get("event_ticker", "?")
    prefix = et.split("-")[0]
    prefix_counts[prefix] += 1
    if prefix not in prefix_examples:
        title = e.get("title", "?")[:55]
        prefix_examples[prefix] = f"{et} - {title}"

print(f"  Event prefix distribution:")
for p, c in prefix_counts.most_common(30):
    print(f"    {p:<40s} {c:>4d}  (e.g. {prefix_examples[p]})")


# ── 2. Try to find actual crypto/finance markets ──
print("\n  [2] Direct-lookup probes for popular market families...")

probes = [
    # Current BTC brackets (Sunday Feb 15 evening)
    "KXBTC-26FEB15-B97000",
    "KXBTC-26FEB15-B97500",
    "KXBTC-26FEB16-B97000",
    "KXBTC-26FEB17-B97000",
    # ETH
    "KXETH-26FEB15-B2700",
    "KXETH-26FEB16-B2700",
    # S&P / NASDAQ
    "KXINX-26FEB18",
    "KXINX-26FEB18-T6120",
    "KXNASDAQ100-26FEB18",
    # Fed rate
    "KXFED-26MAR19-T425",
    "KXFED-26MAR19",
    # IPO / long-dated
    "KXDEELRIP-40-DEEL",
    "KXIPO-CORZ-26",
    "KXIPO-REDDIT-26",
    # Politics
    "KXTRUMP-IMP",
    "KXELONMARS-99",
    # Weather
    "KXNYCTEMPHI-26FEB16",
]

for t in probes:
    data = fetch(f"{HOST}/markets/{t}")
    m = data.get("market", data)
    if m.get("error"):
        err = str(m["error"])[:50]
        print(f"  {t:<45s}  404/ERR: {err}")
    else:
        status = m.get("status", "?")
        vol = m.get("volume", 0) or 0
        # Check orderbook
        ob = fetch(f"{HOST}/markets/{t}/orderbook?depth=5")
        obd = ob.get("orderbook", {})
        yes = obd.get("yes") or []
        no = obd.get("no") or []
        tag = "L2" if (yes or no) else "no-L2"
        bid = m.get("yes_bid", 0)
        ask = m.get("yes_ask", 0)
        print(f"  {t:<45s}  {status:<10s} vol={vol:>6d} bid={bid:>3d} ask={ask:>3d}  {tag} (yes={len(yes)} no={len(no)})")


# ── 3. Search for markets with volume ──
print("\n  [3] Markets with highest volume (from listing)...")
cursor = None
high_vol = []
for page in range(10):
    url = f"{HOST}/markets?limit=100"
    if cursor:
        url += f"&cursor={cursor}"
    data = fetch(url)
    markets = data.get("markets", [])
    if not markets:
        break
    for m in markets:
        vol = m.get("volume", 0) or 0
        if vol > 0:
            high_vol.append(m)
    cursor = data.get("cursor")
    if not cursor:
        break

high_vol.sort(key=lambda x: -(x.get("volume", 0) or 0))
print(f"  Markets with volume > 0: {len(high_vol)}")
for m in high_vol[:15]:
    t = m["ticker"]
    vol = m.get("volume", 0)
    bid = m.get("yes_bid", 0)
    ask = m.get("yes_ask", 0)
    title = m.get("title", "?")[:40]
    print(f"    {t:<55s} vol={vol:>6d} bid={bid:>3d} ask={ask:>3d}  {title}")

print()
