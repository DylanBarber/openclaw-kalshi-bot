#!/usr/bin/env python3
"""Full scope: how many markets have L2 depth on elections host?"""

import json
import urllib.request
from collections import Counter

HOST = "https://api.elections.kalshi.com/trade-api/v2"


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


# 1. Get all events
print("Fetching all events...")
all_events = []
cursor = None
for _ in range(50):
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

print(f"Total events: {len(all_events)}")

# 2. For each event, get its markets
all_markets = []
for ev in all_events:
    et = ev.get("event_ticker", "")
    data = fetch(f"{HOST}/events/{et}")
    mkts = data.get("markets", [])
    for m in mkts:
        m["_event_category"] = ev.get("category", "?")
    all_markets.extend(mkts)

print(f"Total markets from events: {len(all_markets)}")

# 3. Count active ones
active = [m for m in all_markets if m.get("status") == "active"]
with_volume = [m for m in active if (m.get("volume", 0) or 0) > 0]
with_bids = [m for m in active if (m.get("yes_bid", 0) or 0) > 0]
print(f"Active markets: {len(active)}")
print(f"Active with volume > 0: {len(with_volume)}")
print(f"Active with yes_bid > 0: {len(with_bids)}")

# 4. Category breakdown
cats = Counter(m.get("_event_category", "?") for m in active)
print(f"\nActive markets by category:")
for c, n in cats.most_common(20):
    print(f"  {c:<30s} {n:>4d}")

# 5. Test L2 on the top-volume markets
print(f"\nL2 check on top-volume active markets:")
with_volume.sort(key=lambda x: -(x.get("volume", 0) or 0))
l2_ok = 0
l2_empty = 0
for m in with_volume[:30]:
    t = m["ticker"]
    vol = m.get("volume", 0) or 0
    bid = m.get("yes_bid", 0)
    ask = m.get("yes_ask", 0)
    cat = m.get("_event_category", "?")

    ob = fetch(f"{HOST}/markets/{t}/orderbook?depth=5")
    obd = ob.get("orderbook", {})
    yes_lvl = len(obd.get("yes") or [])
    no_lvl = len(obd.get("no") or [])
    has_l2 = yes_lvl > 0 or no_lvl > 0
    if has_l2:
        l2_ok += 1
    else:
        l2_empty += 1
    tag = "L2" if has_l2 else "--"
    print(f"  [{tag:>2s}] {t:<50s} vol={vol:>5d} bid={bid:>2d} ask={ask:>3d} [{cat}]")

print(f"\n  L2 available: {l2_ok}/{l2_ok + l2_empty}")
print()
