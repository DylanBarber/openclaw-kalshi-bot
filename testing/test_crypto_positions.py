#!/usr/bin/env python3
"""Check if we have any crypto-related positions or if KXBTC tickers resolve."""
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
from runner import _fetch_json_raw, _fetch_authed_json, load_config, DEFAULT_HOST

cfg = load_config()
host = cfg.get("host", DEFAULT_HOST)

# Check positions for crypto tickers
data = _fetch_authed_json(cfg, host, "/portfolio/positions?limit=200")
if data:
    for p in data.get("market_positions", []):
        t = p.get("ticker", "")
        if any(kw in t.upper() for kw in ["BTC", "ETH", "CRYPTO", "SOL", "XRP"]):
            print(f"  CRYPTO POS: {t} pos={p.get('position')} exp=${p.get('market_exposure_dollars')}")

# Check fills for crypto
fills = _fetch_authed_json(cfg, host, "/portfolio/fills?limit=50")
if fills:
    for f in fills.get("fills", []):
        t = f.get("ticker", "")
        if any(kw in t.upper() for kw in ["BTC", "ETH", "CRYPTO", "SOL", "XRP"]):
            print(f"  CRYPTO FILL: {t} {f.get('action')} {f.get('count')}x {f.get('side')} @ {f.get('yes_price')}c")

# Try to resolve a known KXBTC series ticker pattern
import datetime
today = datetime.date.today()
for delta in range(-2, 3):
    d = today + datetime.timedelta(days=delta)
    ds = d.strftime("%y%b%d").upper()
    # Try a few near-money strikes (BTC around 68k)
    for strike in [67000, 67500, 68000, 68500, 69000, 95000, 96000, 97000]:
        ticker = f"KXBTC-{ds}-B{strike}"
        m = _fetch_json_raw(f"{host}/markets/{ticker}")
        if m and m.get("market"):
            mkt = m["market"]
            print(f"  FOUND: {ticker} status={mkt.get('status')} vol={mkt.get('volume',0)} bid={mkt.get('yes_bid',0)} ask={mkt.get('yes_ask',0)}")

# Check Financials category events for crypto-adjacent stuff
cursor = None
found = []
for _ in range(30):
    url = f"{host}/events?limit=100"
    if cursor:
        url += f"&cursor={cursor}"
    data = _fetch_json_raw(url)
    if not data:
        break
    for ev in data.get("events", []):
        cat = ev.get("category", "")
        if cat in ("Crypto", "Financials"):
            found.append(ev)
    cursor = data.get("cursor")
    if not cursor:
        break

print(f"\n  Crypto/Financials events: {len(found)}")
for ev in found[:15]:
    print(f"    {ev.get('event_ticker'):<40s} [{ev.get('category')}] {ev.get('title','')[:55]}")
