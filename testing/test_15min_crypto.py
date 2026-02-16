#!/usr/bin/env python3
"""Find 15-minute crypto markets on Kalshi."""
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

# ── 1. Search ALL events for crypto / up-down / 15-minute keywords ──
print("=" * 70)
print("  Searching all events for 15-minute / up-down / crypto keywords")
print("=" * 70)

KEYWORDS = ["15 min", "fifteen", "up or down", "updown", "btcud", "ethud",
            "solud", "xrpud", "btc up", "eth up", "kxbtc15", "minute",
            "kxbtcud", "short-term", "crypto"]
cursor = None
found = []
total_events = 0
for _ in range(30):
    url = f"{HOST}/events?limit=100"
    if cursor:
        url += f"&cursor={cursor}"
    data = _fetch_json_raw(url)
    if not data:
        break
    events = data.get("events", [])
    total_events += len(events)
    for ev in events:
        t = (ev.get("title", "") + " " + ev.get("event_ticker", "")).lower()
        cat = ev.get("category", "")
        if any(kw in t for kw in KEYWORDS) or cat == "Crypto":
            found.append(ev)
    cursor = data.get("cursor")
    if not cursor:
        break

print(f"  Scanned {total_events} events total, found {len(found)} matching\n")
for ev in found:
    et = ev.get("event_ticker", "")
    cat = ev.get("category", "")
    title = ev.get("title", "")[:65]
    print(f"  {et:<45s} [{cat:<12s}] {title}")

# ── 2. Try common ticker patterns for 15-min BTC ──
print("\n" + "=" * 70)
print("  Trying common ticker patterns for 15-min BTC markets")
print("=" * 70)

import datetime
now = datetime.datetime.now(datetime.timezone.utc)
today = now.strftime("%y%b%d").upper()

patterns = [
    # Various possible ticker formats
    f"KXBTCUD-{today}",
    f"KXBTC-UD-{today}",
    f"KXBTC15-{today}",
    f"KXBTCUPDOWN-{today}",
    "KXBTCUD",
    "KXBTC-UD",
    "BTCUD",
    "BTCUPDOWN",
    "KXBTC15MIN",
    f"KXBTCUD-26FEB17",
    f"KXBTCUD-26FEB18",
]

for pat in patterns:
    # Try as event
    ev_data = _fetch_json_raw(f"{HOST}/events/{pat}")
    if ev_data and ev_data.get("event"):
        print(f"  EVENT FOUND: {pat}")
        print(f"    {json.dumps(ev_data['event'], indent=2, default=str)[:200]}")
    elif ev_data and ev_data.get("markets"):
        print(f"  EVENT FOUND: {pat} ({len(ev_data.get('markets',[]))} markets)")
    
    # Try as market
    m_data = _fetch_json_raw(f"{HOST}/markets/{pat}")
    if m_data and m_data.get("market"):
        mkt = m_data["market"]
        print(f"  MARKET FOUND: {pat}")
        print(f"    status={mkt.get('status')} bid={mkt.get('yes_bid')} ask={mkt.get('yes_ask')} vol={mkt.get('volume')}")

# ── 3. Try the /markets endpoint with a text search ──
print("\n" + "=" * 70)
print("  Trying /markets listing (first 200)")
print("=" * 70)

cursor = None
crypto_markets = []
for _ in range(2):
    url = f"{HOST}/markets?limit=100"
    if cursor:
        url += f"&cursor={cursor}"
    data = _fetch_json_raw(url)
    if not data:
        break
    for m in data.get("markets", []):
        t = m.get("ticker", "").upper()
        title = m.get("title", "").lower()
        if any(kw in t or kw in title.upper() for kw in ["BTC", "ETH", "SOL", "XRP", "CRYPTO", "DOGE", "UPDOWN", "15MIN"]):
            crypto_markets.append(m)
    cursor = data.get("cursor")
    if not cursor:
        break

print(f"  Found {len(crypto_markets)} crypto-like markets in /markets listing")
for m in crypto_markets[:10]:
    t = m.get("ticker", "")
    title = m.get("title", "")[:50]
    print(f"  {t:<50s} {title}")

# ── 4. Try the Kalshi trading API v3 or alternative endpoints ──
print("\n" + "=" * 70)
print("  Testing alternative API paths")
print("=" * 70)

alt_urls = [
    f"{HOST}/series/KXBTCUD",
    f"{HOST}/series/KXBTC",
    "https://trading-api.kalshi.com/trade-api/v2/events?limit=5",
    "https://api.kalshi.com/trade-api/v2/events?limit=5",
]

for url in alt_urls:
    data = _fetch_json_raw(url)
    if data:
        print(f"  OK: {url}")
        print(f"    Keys: {list(data.keys())[:5]}")
    else:
        print(f"  FAIL: {url}")

print("\nDone.")
