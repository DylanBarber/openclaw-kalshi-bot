#!/usr/bin/env python3
"""Direct ticker + event lookups to test API visibility."""

import json
import urllib.request

HOST = "https://api.elections.kalshi.com/trade-api/v2"


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


print("=" * 70)
print("  Direct Market Lookups")
print("=" * 70)

tickers = [
    "KXDEELRIP-40-DEEL",
    "KXBTC-26FEB16-B97000",
    "KXBTC-26FEB16-B97500",
    "KXBTC-26FEB16-B98000",
    "KXETH-26FEB16-B2700",
    "KXINX-26FEB18-T6120",
    "KXFED-26MAR19-T425",
]

for t in tickers:
    mkt = fetch(f"{HOST}/markets/{t}")
    m = mkt.get("market", mkt)
    err = m.get("error", "")
    if err:
        print(f"  {t:<35s}  ERROR: {err}")
        continue
    status = m.get("status", "?")
    vol = m.get("volume", "?")

    ob = fetch(f"{HOST}/markets/{t}/orderbook?depth=5")
    ob_data = ob.get("orderbook", {})
    yes = ob_data.get("yes") or []
    no = ob_data.get("no") or []
    tag = "L2 OK" if (yes or no) else "EMPTY"

    print(f"  {t:<35s}  status={status:<10s}  vol={str(vol):>6s}  yes={len(yes)} no={len(no)} [{tag}]")

print()
print("=" * 70)
print("  Event Search")
print("=" * 70)

for q in ["KXBTC", "KXDEELRIP", "KXINX", "KXFED", "bitcoin", "IPO"]:
    data = fetch(f"{HOST}/events?limit=5&search={q}")
    events = data.get("events", [])
    print(f"\n  search='{q}': {len(events)} events")
    for ev in events[:3]:
        et = ev.get("event_ticker", "?")
        title = ev.get("title", "?")[:55]
        mcount = ev.get("markets_count", "?")
        print(f"    {et}  ({mcount} markets)  {title}")

print()
