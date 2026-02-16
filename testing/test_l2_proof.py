#!/usr/bin/env python3
"""Prove L2 depth works across ALL categories, not just IPO races."""

import json
import urllib.request

HOST = "https://api.elections.kalshi.com/trade-api/v2"


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


samples = [
    ("KXFEDCHAIRNOM-29-KW",   "Politics",     "Trump Fed Chair nominee (Kevin Warsh)"),
    ("KXDJTVOSTARIFFS",       "Politics",     "Trump tariffs"),
    ("CONTROLH-2026-D",       "Politics",     "House control 2026 (Dem)"),
    ("KXGREENLAND-29",        "Politics",     "Greenland deal"),
    ("KXBALANCE-29",          "Politics",     "Trump balance budget"),
    ("KXPRESNOMD-28-GN",     "Politics",     "2028 Dem nominee (Newsom)"),
    ("KXFEDDECISION-26MAR-T425", "Economics", "Fed March rate decision"),
    ("KXIPOAIRTABLE-28JAN01", "Economics",    "Airtable IPO"),
    ("KXOAIANTH-40-OAI",      "Financials",   "OpenAI vs Anthropic IPO"),
    ("KXDEELRIP-40-DEEL",     "Financials",   "Deel vs Rippling IPO"),
    ("KXRAMPBREX-40-RAMP",    "Financials",   "Ramp vs Brex IPO"),
    ("KXELONMARS-99",         "Sci/Tech",     "Elon visits Mars"),
    ("KXNEWPOPE-70-PC",       "World",        "Next Pope"),
]

header = f"  {'TICKER':<35s} {'CAT':<12s} {'BID':>4s} {'ASK':>4s} {'VOLUME':>10s}  {'YES':>3s} {'NO':>3s}  L2?"
print(header)
print("  " + "-" * 90)

ok = 0
fail = 0

for ticker, cat, desc in samples:
    m = fetch(f"{HOST}/markets/{ticker}")
    if not m or m.get("error"):
        print(f"  {ticker:<35s} {cat:<12s}  -- 404 / not found --")
        fail += 1
        continue

    mkt = m.get("market", m)
    bid = mkt.get("yes_bid", 0) or 0
    ask = mkt.get("yes_ask", 0) or 0
    vol = mkt.get("volume", 0) or 0

    ob = fetch(f"{HOST}/markets/{ticker}/orderbook?depth=5")
    obd = ob.get("orderbook", {}) if ob else {}
    yes = len(obd.get("yes") or [])
    no = len(obd.get("no") or [])
    has = "YES" if (yes or no) else "NO"
    if yes or no:
        ok += 1
    else:
        fail += 1

    print(f"  {ticker:<35s} {cat:<12s} {bid:>4d} {ask:>4d} {vol:>10d}  {yes:>3d} {no:>3d}  {has}  {desc}")

print("  " + "-" * 90)
print(f"  L2 available: {ok}/{ok + fail} markets tested")
