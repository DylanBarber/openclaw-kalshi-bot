#!/usr/bin/env python3
"""
Diagnostic: Which markets have usable L2 orderbook data?

Samples tickers across categories and reports which return real depth.
"""

import json
import urllib.request
import urllib.error
import sys

HOST = "https://api.elections.kalshi.com/trade-api/v2"


def fetch_json(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def check_orderbook(ticker):
    data = fetch_json(f"{HOST}/markets/{ticker}/orderbook?depth=5")
    ob = data.get("orderbook", {})
    yes = ob.get("yes") or []
    no = ob.get("no") or []
    return len(yes), len(no)


def main():
    print("\n" + "=" * 70)
    print("  L2 Orderbook Availability Diagnostic")
    print("=" * 70)
    print(f"  Host: {HOST}\n")

    # Step 1: Fetch a broad sample of markets
    print("  Fetching markets (limit=100, no filter)...")
    data = fetch_json(f"{HOST}/markets?limit=100")
    markets = data.get("markets", [])
    print(f"  Got {len(markets)} markets\n")

    if not markets:
        print("  ERROR: No markets returned.")
        return

    # Categorize by ticker prefix
    categories = {}
    for m in markets:
        ticker = m.get("ticker", "")
        # Extract prefix (e.g., KXBTC, KXDEELRIP, KXMV, etc.)
        parts = ticker.split("-")
        prefix = parts[0] if parts else "UNKNOWN"
        if prefix not in categories:
            categories[prefix] = []
        categories[prefix].append({
            "ticker": ticker,
            "title": m.get("title", "")[:60],
            "status": m.get("status", ""),
            "volume": m.get("volume", 0),
            "yes_bid": m.get("yes_bid", 0),
            "yes_ask": m.get("yes_ask", 0),
        })

    print(f"  Found {len(categories)} ticker prefixes: {', '.join(sorted(categories.keys()))}\n")

    # Step 2: Test orderbook for a sample from each category
    print("-" * 70)
    print(f"  {'TICKER':<50s}  {'YES':>3s}  {'NO':>3s}  {'STATUS':<8s}  VOL")
    print("-" * 70)

    has_data = 0
    no_data = 0
    tested = 0

    for prefix in sorted(categories.keys()):
        tickers_in_cat = categories[prefix]
        # Pick up to 3 from each category, prefer ones with volume
        tickers_in_cat.sort(key=lambda x: -(x.get("volume") or 0))
        sample = tickers_in_cat[:3]

        for m in sample:
            ticker = m["ticker"]
            tested += 1
            yes_count, no_count = check_orderbook(ticker)
            has = yes_count > 0 or no_count > 0
            marker = "OK" if has else "--"
            if has:
                has_data += 1
            else:
                no_data += 1

            vol = m.get("volume", 0) or 0
            status = m.get("status", "?")
            print(f"  {ticker:<50s}  {yes_count:>3d}  {no_count:>3d}  {status:<8s}  {vol:>6d}  [{marker}]")

    print("-" * 70)
    print(f"\n  SUMMARY: {tested} tested, {has_data} with L2 data, {no_data} empty")
    print(f"  Data rate: {has_data}/{tested} = {has_data/max(tested,1)*100:.0f}%\n")

    # Step 3: Also try some well-known ticker patterns
    print("  Testing specific well-known tickers...")
    known = [
        "KXBTC-26FEB16-B97500",
        "KXBTC-26FEB16-B98000",
        "KXETH-26FEB16-B2700",
        "KXINX-26FEB18",
        "KXNASDAQ100-26FEB18",
    ]
    for ticker in known:
        yes_count, no_count = check_orderbook(ticker)
        has = yes_count > 0 or no_count > 0
        marker = "OK" if has else "--"
        print(f"  {ticker:<50s}  {yes_count:>3d}  {no_count:>3d}  [{marker}]")

    print()


if __name__ == "__main__":
    main()
