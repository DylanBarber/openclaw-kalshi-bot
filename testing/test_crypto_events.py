#!/usr/bin/env python3
"""Find all crypto-related events on Kalshi."""
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
KEYWORDS = ["bitcoin", "btc", "crypto", "ethereum", "eth", "solana", "sol",
            "xrp", "dogecoin", "doge", "coin", "defi", "nft"]

cursor = None
crypto_events = []
for _ in range(30):
    url = f"{HOST}/events?limit=100"
    if cursor:
        url += f"&cursor={cursor}"
    data = _fetch_json_raw(url)
    if not data:
        break
    for ev in data.get("events", []):
        t = ev.get("title", "").lower()
        et = ev.get("event_ticker", "").lower()
        cat = ev.get("category", "")
        if any(kw in t or kw in et for kw in KEYWORDS):
            crypto_events.append({
                "event_ticker": ev.get("event_ticker"),
                "title": ev.get("title"),
                "category": cat,
            })
    cursor = data.get("cursor")
    if not cursor:
        break

print(f"Found {len(crypto_events)} crypto-related events:\n")
for e in crypto_events[:30]:
    et = e["event_ticker"]
    cat = e["category"]
    title = e["title"][:65]
    print(f"  {et:<40s} [{cat:<15s}] {title}")

# For the first few, also fetch the markets
print("\n\nMarkets in first 3 events:")
for e in crypto_events[:3]:
    et = e["event_ticker"]
    ev_data = _fetch_json_raw(f"{HOST}/events/{et}")
    if not ev_data:
        continue
    markets = ev_data.get("markets", [])
    print(f"\n  {et} ({len(markets)} markets):")
    for m in markets[:5]:
        ticker = m.get("ticker", "?")
        title = m.get("title", "")[:50]
        yb = m.get("yes_bid", 0) or 0
        ya = m.get("yes_ask", 0) or 0
        vol = m.get("volume", 0) or 0
        status = m.get("status", "")
        print(f"    {ticker:<45s} bid={yb:>2d} ask={ya:>3d} vol={vol:>6d} [{status}] {title}")
