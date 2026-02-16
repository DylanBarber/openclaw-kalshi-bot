#!/usr/bin/env python3
"""
Deep L2 diagnostic: search harder for markets with orderbook data.
"""

import json
import urllib.request
import urllib.error

HOST = "https://api.elections.kalshi.com/trade-api/v2"


def fetch_json(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def check_ob(ticker):
    data = fetch_json(f"{HOST}/markets/{ticker}/orderbook?depth=5")
    ob = data.get("orderbook", {})
    yes = ob.get("yes") or []
    no = ob.get("no") or []
    return len(yes), len(no)


def search_markets(query="", limit=50, cursor=None, status=None):
    url = f"{HOST}/markets?limit={limit}"
    if query:
        url += f"&ticker={query}"
    if cursor:
        url += f"&cursor={cursor}"
    if status:
        url += f"&status={status}"
    return fetch_json(url)


print("=" * 70)
print("  Deep L2 Orderbook Search")
print("=" * 70)

# Strategy 1: Paginate through markets looking for non-multivariate ones
print("\n  [1] Paginating through all markets (looking for non-MV tickers)...")
cursor = None
all_tickers = []
pages = 0
while pages < 10:
    data = search_markets(limit=100, cursor=cursor)
    markets = data.get("markets", [])
    if not markets:
        break
    for m in markets:
        t = m.get("ticker", "")
        all_tickers.append({
            "ticker": t,
            "status": m.get("status", ""),
            "volume": m.get("volume", 0) or 0,
            "prefix": t.split("-")[0] if t else "?",
            "yes_bid": m.get("yes_bid", 0),
            "no_bid": m.get("no_bid", 0),
        })
    cursor = data.get("cursor")
    pages += 1
    if not cursor:
        break

print(f"  Found {len(all_tickers)} total markets across {pages} pages")

# Group by prefix
from collections import Counter
prefix_counts = Counter(t["prefix"] for t in all_tickers)
print(f"  Prefix distribution: {dict(prefix_counts.most_common(20))}")

# Find non-KXMV tickers
non_mv = [t for t in all_tickers if not t["prefix"].startswith("KXMV")]
print(f"  Non-multivariate tickers: {len(non_mv)}")

# Strategy 2: Try known event families
print("\n  [2] Trying event-based searches...")
families = ["KXBTC", "KXETH", "KXINX", "KXNASDAQ", "KXDEELRIP", "KXIPO", "KXGOLD",
            "KXTRUMP", "KXFED", "KXCPI", "KXGDP", "KXJOBS", "KXSP500"]
for fam in families:
    data = fetch_json(f"{HOST}/markets?limit=5&ticker={fam}")
    markets = data.get("markets", [])
    count = len(markets)
    if count > 0:
        tickers = [m["ticker"] for m in markets]
        print(f"  {fam:<20s} -> {count} results: {tickers[0]}")
        # Test first one
        yes, no = check_ob(tickers[0])
        marker = "L2 OK" if (yes or no) else "EMPTY"
        print(f"  {' ' * 20}    orderbook: yes={yes} no={no} [{marker}]")
    else:
        print(f"  {fam:<20s} -> 0 results")

# Strategy 3: Try the user's known working ticker family
print("\n  [3] Trying KXDEELRIP variants...")
data = fetch_json(f"{HOST}/markets?limit=20&ticker=KXDEELRIP")
markets = data.get("markets", [])
print(f"  Found {len(markets)} KXDEELRIP markets")
for m in markets[:5]:
    t = m["ticker"]
    vol = m.get("volume", 0) or 0
    yes, no = check_ob(t)
    marker = "L2 OK" if (yes or no) else "EMPTY"
    print(f"  {t:<50s} vol={vol:>6d}  yes={yes} no={no} [{marker}]")

# Strategy 4: Look for markets with actual bid/ask in their summary
print("\n  [4] Markets with non-zero yes_bid from API listing...")
with_bids = [t for t in all_tickers if t.get("yes_bid", 0) > 0]
print(f"  Found {len(with_bids)} markets with yes_bid > 0 out of {len(all_tickers)}")
for t in with_bids[:10]:
    ticker = t["ticker"]
    yes, no = check_ob(ticker)
    marker = "L2 OK" if (yes or no) else "EMPTY"
    print(f"  {ticker:<50s} bid={t['yes_bid']:>3d}  yes={yes} no={no} [{marker}]")

print("\n" + "=" * 70)
print("  Done.")
print("=" * 70)
