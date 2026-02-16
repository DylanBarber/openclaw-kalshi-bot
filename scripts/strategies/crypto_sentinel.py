"""
Crypto Sentinel — External-price-triggered position manager for crypto markets.

The daily crypto bracket series (KXBTC-*, KXETH-*) are not reliably available
on the elections API host, and when they are, L2 orderbook data is often thin
or empty.  This strategy takes a different approach:

  1. Monitors REAL crypto prices via CoinGecko (free, no API key)
  2. Manages existing Kalshi crypto positions using external price as the
     signal source — NOT the Kalshi orderbook
  3. Executes stop-loss and take-profit exits on Kalshi when the external
     price crosses configured thresholds
  4. Can also watch for and evaluate the few crypto/financials events that
     exist on the platform

Key idea: the external spot price is the "truth" for triggering exits.  The
Kalshi orderbook is only used for execution (placing the exit order), and even
that falls back to market-price estimates if the book is empty.

Usage:
    # Watch BTC with stop-loss at $66,000 and take-profit at $72,000
    python runner.py run-strategy crypto_sentinel --ticker BTC -- --stop 66000 --tp 72000

    # Watch ETH with defaults, auto-managing any KXETH positions
    python runner.py run-strategy crypto_sentinel --ticker ETH

    # Watch a specific Kalshi crypto ticker, using external price for triggers
    python runner.py run-strategy crypto_sentinel --ticker KXBTC-26FEB15-B68375 -- --asset BTC --strike 68375

    # Dry-run: just print prices and analysis, don't execute
    python runner.py run-strategy crypto_sentinel --ticker BTC -- --dry-run

    # Scan for crypto-related events on Kalshi
    python runner.py run-strategy crypto_sentinel --ticker BTC -- --scan-events

Extra args (passed after --):
    --asset BTC|ETH|SOL          Crypto asset to track (default: inferred from ticker)
    --stop PRICE_USD             Stop-loss trigger in USD (exit if price drops below)
    --tp PRICE_USD               Take-profit trigger in USD (exit if price rises above)
    --strike PRICE_USD           Bracket strike price (for KXBTC-* tickers)
    --side LONG|SHORT            Position side (default: LONG)
    --contracts N                Number of contracts held (default: from positions API)
    --kalshi-ticker TICKER       Specific Kalshi ticker to exit on trigger
    --interval SECONDS           Poll interval (default: 10)
    --dry-run                    Monitor only, do not execute exits
    --scan-events                Scan for crypto/financials events and exit
    --price-source binance       Price source: binance (default) or coingecko

Limitations:
    - Daily series tickers (KXBTC-*, KXETH-*) may not resolve on the elections host
    - L2 orderbook data for crypto markets is often empty
    - Exit orders use limit orders at estimated fair value; fills are not guaranteed
    - CoinGecko free tier has rate limits (~10-30 calls/min)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_scripts_dir = str(Path(__file__).resolve().parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


# ── CoinGecko price feed ─────────────────────────────────────────────────

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "LINK": "chainlink",
}

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# Binance public API — higher rate limits than CoinGecko, no key needed
BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
    "ADA": "ADAUSDT",
    "AVAX": "AVAXUSDT",
    "MATIC": "MATICUSDT",
    "DOT": "DOTUSDT",
    "LINK": "LINKUSDT",
}

# Binance US is used because Binance.com returns HTTP 451 (geo-blocked) in the US
BINANCE_TICKER_URL = "https://api.binance.us/api/v3/ticker/24hr"

# Coinbase — reliable US-accessible fallback, no key needed
COINBASE_SYMBOLS = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "XRP": "XRP-USD",
    "DOGE": "DOGE-USD", "ADA": "ADA-USD", "AVAX": "AVAX-USD",
    "MATIC": "MATIC-USD", "DOT": "DOT-USD", "LINK": "LINK-USD",
}


def fetch_crypto_price_binance(asset: str) -> dict | None:
    """Fetch price from Binance US public API (no key needed)."""
    symbol = BINANCE_SYMBOLS.get(asset.upper())
    if not symbol:
        return None

    url = f"{BINANCE_TICKER_URL}?symbol={symbol}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        price = float(data.get("lastPrice", 0))
        change_pct = float(data.get("priceChangePercent", 0))
        if price > 0:
            return {"usd": price, "usd_24h_change": change_pct}
    except Exception:
        pass
    return None


def fetch_crypto_price_coinbase(asset: str) -> dict | None:
    """Fetch price from Coinbase public API (no key needed)."""
    cb_pair = COINBASE_SYMBOLS.get(asset.upper())
    if not cb_pair:
        return None

    url = f"https://api.coinbase.com/v2/prices/{cb_pair}/spot"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        amount = float(data.get("data", {}).get("amount", 0))
        if amount > 0:
            return {"usd": amount, "usd_24h_change": 0.0}
    except Exception:
        pass
    return None


def fetch_crypto_price_coingecko(asset: str) -> dict | None:
    """Fetch price from CoinGecko (free, rate-limited ~10-30 req/min)."""
    cg_id = COINGECKO_IDS.get(asset.upper())
    if not cg_id:
        return None

    url = f"{COINGECKO_URL}?ids={cg_id}&vs_currencies=usd&include_24hr_change=true"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "kalshi-bot/1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get(cg_id)
    except Exception:
        return None


def fetch_crypto_price(asset: str, source: str = "binance") -> dict | None:
    """Fetch current price + 24h change.

    Tries Binance US first, falls back to Coinbase, then CoinGecko.
    Returns {"usd": float, "usd_24h_change": float} or None on failure.
    """
    fetchers = {
        "binance": [fetch_crypto_price_binance, fetch_crypto_price_coinbase, fetch_crypto_price_coingecko],
        "coinbase": [fetch_crypto_price_coinbase, fetch_crypto_price_binance, fetch_crypto_price_coingecko],
        "coingecko": [fetch_crypto_price_coingecko, fetch_crypto_price_binance, fetch_crypto_price_coinbase],
    }

    chain = fetchers.get(source, fetchers["binance"])
    for fn in chain:
        result = fn(asset)
        if result is not None:
            return result

    supported = set(COINGECKO_IDS.keys()) | set(BINANCE_SYMBOLS.keys()) | set(COINBASE_SYMBOLS.keys())
    print(f"  All price sources failed for {asset}. Supported: {', '.join(sorted(supported))}", file=sys.stderr)
    return None


# ── Kalshi position/order helpers ─────────────────────────────────────────

def _fetch_authed(cfg: dict, host: str, path: str) -> dict | None:
    """Authenticated raw HTTP GET (reuses runner's signing)."""
    from runner import _fetch_authed_json
    return _fetch_authed_json(cfg, host, path)


def find_crypto_positions(cfg: dict, host: str, asset: str) -> list[dict]:
    """Find all positions with tickers matching a crypto asset."""
    data = _fetch_authed(cfg, host, "/portfolio/positions?limit=200")
    if not data:
        return []

    market_positions = data.get("market_positions", []) or []
    results = []
    asset_upper = asset.upper()

    for p in market_positions:
        ticker = p.get("ticker", "")
        pos = p.get("position", 0)
        if pos == 0:
            continue

        ticker_upper = ticker.upper()
        if (f"KX{asset_upper}" in ticker_upper or
                f"K{asset_upper}" in ticker_upper or
                asset_upper in ticker_upper):
            results.append({
                "ticker": ticker,
                "position": pos,
                "side": "LONG" if pos > 0 else "SHORT",
                "contracts": abs(pos),
                "market_exposure_dollars": p.get("market_exposure_dollars", "0.00"),
                "fees_paid_dollars": p.get("fees_paid_dollars", "0.00"),
            })
    return results


def find_crypto_orders(cfg: dict, host: str, asset: str) -> list[dict]:
    """Find resting orders for crypto tickers."""
    data = _fetch_authed(cfg, host, "/portfolio/orders?status=resting&limit=100")
    if not data:
        return []

    orders = data.get("orders", []) or []
    results = []
    asset_upper = asset.upper()

    for o in orders:
        ticker = o.get("ticker", "")
        if asset_upper in ticker.upper():
            results.append({
                "order_id": o.get("order_id"),
                "ticker": ticker,
                "side": o.get("side"),
                "action": o.get("action"),
                "yes_price": o.get("yes_price"),
                "count": o.get("remaining_count") or o.get("count"),
            })
    return results


def parse_bracket_strike(ticker: str) -> int | None:
    """Extract the strike price from a KXBTC-*-B{strike} ticker.

    Returns the strike in USD or None if the ticker isn't a bracket.
    Examples:
        KXBTC-26FEB15-B68375 → 68375
        KXBTC-26FEB15-T97000 → 97000
    """
    parts = ticker.upper().split("-")
    for p in parts:
        if p.startswith("B") or p.startswith("T"):
            try:
                return int(p[1:])
            except ValueError:
                pass
    return None


def infer_asset(ticker: str) -> str | None:
    """Infer the crypto asset from a Kalshi ticker."""
    upper = ticker.upper()
    if "BTC" in upper or "BITCOIN" in upper:
        return "BTC"
    if "ETH" in upper or "ETHEREUM" in upper:
        return "ETH"
    if "SOL" in upper or "SOLANA" in upper:
        return "SOL"
    if "XRP" in upper:
        return "XRP"
    if "DOGE" in upper:
        return "DOGE"
    return None


# ── Event scanner ─────────────────────────────────────────────────────────

def scan_crypto_events(host: str) -> list[dict]:
    """Find crypto/financials events on Kalshi via the events endpoint."""
    from runner import _fetch_json_raw
    import re

    # Use word-boundary-aware patterns to avoid false positives
    # ("eth" would otherwise match "releaseTHElastofus")
    patterns = [
        re.compile(r"\bbitcoin\b", re.I),
        re.compile(r"\bbtc\b", re.I),
        re.compile(r"\bcrypto\b", re.I),
        re.compile(r"\bethereum\b", re.I),
        re.compile(r"\bsolana\b", re.I),
        re.compile(r"\bdefi\b", re.I),
        re.compile(r"\bblockchain\b", re.I),
        re.compile(r"\bxrp\b", re.I),
        re.compile(r"\bdogecoin\b", re.I),
    ]
    # Ticker prefix patterns (no word boundary needed)
    ticker_prefixes = ["kxbtc", "kxeth", "kxsol", "btceth", "kxcrypto"]
    crypto_cats = {"Crypto"}

    results = []
    cursor = None
    for _ in range(30):
        url = f"{host}/events?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        data = _fetch_json_raw(url)
        if not data:
            break
        for ev in data.get("events", []):
            title = ev.get("title", "")
            et = ev.get("event_ticker", "")
            cat = ev.get("category", "")

            is_crypto = cat in crypto_cats
            if not is_crypto:
                is_crypto = any(p.search(title) for p in patterns)
            if not is_crypto:
                is_crypto = any(et.lower().startswith(pfx) for pfx in ticker_prefixes)

            if is_crypto:
                results.append({
                    "event_ticker": et,
                    "title": title,
                    "category": cat,
                    "sub_title": ev.get("sub_title", ""),
                })
        cursor = data.get("cursor")
        if not cursor:
            break

    # Fetch markets for each event
    for ev in results:
        et = ev["event_ticker"]
        ev_data = _fetch_json_raw(f"{host}/events/{et}")
        if ev_data:
            markets = ev_data.get("markets", [])
            ev["markets"] = [{
                "ticker": m.get("ticker"),
                "title": m.get("title"),
                "yes_bid": m.get("yes_bid", 0) or 0,
                "yes_ask": m.get("yes_ask", 0) or 0,
                "volume": m.get("volume", 0) or 0,
                "status": m.get("status"),
            } for m in markets]
        else:
            ev["markets"] = []

    return results


# ── 15-minute market discovery ────────────────────────────────────────────

SERIES_15M = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
}


def find_active_15m_market(host: str, asset: str) -> dict | None:
    """Find the NEAREST-expiry active 15-minute market for a crypto asset.

    Uses the ``status=open`` filter on the /events endpoint so the API returns
    only events that are currently tradeable.  Without this filter the API
    returns events furthest-out first and the active near-term events are
    invisible past the default pagination limit.

    Returns {"event_ticker", "market_ticker", "title", "status", "close_time",
             "yes_bid", "yes_ask", "volume"} or None.
    """
    from runner import _fetch_json_raw

    series = SERIES_15M.get(asset.upper())
    if not series:
        return None

    # status=open returns ONLY active/tradeable events — fast and reliable
    data = _fetch_json_raw(f"{host}/events?series_ticker={series}&status=open&limit=50")
    if not data:
        return None

    events = data.get("events", [])

    active_markets = []

    for ev in events:
        et = ev.get("event_ticker", "")
        ev_data = _fetch_json_raw(f"{host}/events/{et}")
        if not ev_data:
            continue

        markets = ev_data.get("markets", [])
        for m in markets:
            status = m.get("status", "")
            if status in ("active", "open"):
                active_markets.append({
                    "event_ticker": et,
                    "market_ticker": m.get("ticker", ""),
                    "title": m.get("title", ""),
                    "subtitle": m.get("subtitle", ""),
                    "status": status,
                    "close_time": m.get("close_time", ""),
                    "yes_bid": m.get("yes_bid", 0) or 0,
                    "yes_ask": m.get("yes_ask", 0) or 0,
                    "volume": m.get("volume", 0) or 0,
                })

    if active_markets:
        # Sort by close_time ascending — nearest expiry first
        active_markets.sort(key=lambda m: m.get("close_time", "z"))
        return active_markets[0]

    # No open events — fall back to nearest initialized event
    data = _fetch_json_raw(f"{host}/events?series_ticker={series}&limit=10")
    if not data:
        return None

    events = data.get("events", [])
    best_initialized = None

    for ev in events:
        et = ev.get("event_ticker", "")
        ev_data = _fetch_json_raw(f"{host}/events/{et}")
        if not ev_data:
            continue

        markets = ev_data.get("markets", [])
        for m in markets:
            status = m.get("status", "")
            if status == "initialized":
                candidate = {
                    "event_ticker": et,
                    "market_ticker": m.get("ticker", ""),
                    "title": m.get("title", ""),
                    "subtitle": m.get("subtitle", ""),
                    "status": status,
                    "close_time": m.get("close_time", ""),
                    "yes_bid": m.get("yes_bid", 0) or 0,
                    "yes_ask": m.get("yes_ask", 0) or 0,
                    "volume": m.get("volume", 0) or 0,
                }
                if best_initialized is None or m.get("close_time", "z") < best_initialized.get("close_time", "z"):
                    best_initialized = candidate

    return best_initialized


def list_15m_series(host: str) -> list[dict]:
    """List all available 15-minute crypto series with current status."""
    from runner import _fetch_json_raw

    results = []
    for asset, series in SERIES_15M.items():
        data = _fetch_json_raw(f"{host}/series/{series}")
        if not data or not data.get("series"):
            continue

        s = data["series"]

        # Count active events
        ev_data = _fetch_json_raw(f"{host}/events?series_ticker={series}&limit=5")
        n_events = len(ev_data.get("events", [])) if ev_data else 0

        # Check if any market is active
        active_market = find_active_15m_market(host, asset)
        status = "no markets"
        if active_market:
            status = active_market["status"]
            if status == "active":
                status = f"ACTIVE (bid={active_market['yes_bid']} ask={active_market['yes_ask']})"

        results.append({
            "asset": asset,
            "series": series,
            "title": s.get("title", ""),
            "events": n_events,
            "status": status,
            "active_market": active_market,
        })

    return results


def run_15min_mode(asset: str, host: str, cfg: dict, opts, dry_run: bool = False) -> None:
    """Monitor and trade 15-minute crypto up/down markets.

    Polls external price to determine direction, then trades the binary
    YES (up) or NO (down) market on Kalshi.
    """
    print(f"\n  Crypto Sentinel — 15-Minute Mode")
    print(f"  {'=' * 60}")
    print(f"  Asset:        {asset}")
    print(f"  Series:       {SERIES_15M.get(asset.upper(), '?')}")
    print(f"  Dry-run:      {dry_run}")
    print(f"  Interval:     {opts.interval}s")
    print(f"  Source:       {opts.price_source}")

    contracts = opts.contracts or 10
    print(f"  Contracts:    {contracts}")

    # Get initial price
    initial_price_data = fetch_crypto_price(asset, opts.price_source)
    if not initial_price_data:
        print(f"\n  Cannot fetch {asset} price. Check network.")
        return
    initial_spot = initial_price_data["usd"]
    print(f"  Current {asset}: ${initial_spot:,.2f}")

    # Find current/next 15-minute market (nearest expiry first)
    print(f"\n  Looking for active 15-minute market (nearest expiry)...")
    market = find_active_15m_market(host, asset)
    if not market:
        print(f"  No 15-minute {asset} markets found on Kalshi.")
        print(f"  These markets may not yet be open for this time slot.")
        print(f"  Use 'runner.py series {SERIES_15M.get(asset.upper(), '?')} --events' to check.")
        return

    ticker = market["market_ticker"]
    status = market["status"]
    close_time = market["close_time"]

    print(f"  Market:       {ticker}  (nearest expiry)")
    print(f"  Title:        {market['title']}")
    print(f"  Status:       {status}")
    print(f"  Close time:   {close_time}")
    print(f"  YES bid/ask:  {market['yes_bid']}/{market['yes_ask']}")
    print(f"  Volume:       {market['volume']}")

    if status == "initialized":
        print(f"\n  Market is initialized (not yet active).")
        print(f"  Waiting for it to open... (Ctrl-C to stop)")
        print(f"  15-minute markets activate closer to their time slot.")

    # Determine trading direction based on momentum
    print(f"\n  Collecting price samples to determine direction...")
    prices = []
    sample_count = min(3, max(1, int(30 / opts.interval)))

    for i in range(sample_count):
        pd = fetch_crypto_price(asset, opts.price_source)
        if pd:
            prices.append(pd["usd"])
            if i < sample_count - 1:
                time.sleep(opts.interval)

    if len(prices) < 2:
        print(f"  Insufficient price data. Using last known direction.")
        direction = "UP"
    else:
        delta = prices[-1] - prices[0]
        direction = "UP" if delta >= 0 else "DOWN"
        pct = (delta / prices[0]) * 100 if prices[0] > 0 else 0
        print(f"  Price movement: ${prices[0]:,.2f} -> ${prices[-1]:,.2f} ({pct:+.4f}%)")

    print(f"  Predicted direction: {direction}")

    # For "BTC price up in next 15 mins?":
    #   YES = price goes up
    #   NO = price goes down
    if direction == "UP":
        side = "yes"
        action = "buy"
        # Try to get a reasonable price from the book
        entry_cents = market["yes_bid"] if market["yes_bid"] > 0 else 50
    else:
        side = "no"
        action = "buy"
        # NO bid = 100 - yes_ask
        no_bid = (100 - market["yes_ask"]) if market["yes_ask"] > 0 else 50
        entry_cents = no_bid if no_bid > 0 else 50

    # Fetch L2 for better pricing
    from runner import _fetch_json_raw
    ob_data = _fetch_json_raw(f"{host}/markets/{ticker}/orderbook?depth=5")
    if ob_data:
        book = ob_data.get("orderbook", {})
        yes_levels = book.get("yes") or []
        no_levels = book.get("no") or []

        if direction == "UP" and yes_levels:
            # Buy YES: post at best bid + 1
            best_bid = max(lvl[0] for lvl in yes_levels)
            entry_cents = min(99, best_bid + 1)
            print(f"  L2 YES best bid: {best_bid}c -> posting at {entry_cents}c")
        elif direction == "DOWN" and no_levels:
            # Buy NO: post at best NO bid + 1
            best_no_bid = max(lvl[0] for lvl in no_levels)
            entry_cents = min(99, best_no_bid + 1)
            print(f"  L2 NO best bid: {best_no_bid}c -> posting at {entry_cents}c")

    print(f"\n  {'[DRY-RUN] ' if dry_run else ''}ORDER:")
    print(f"    Market:    {ticker}")
    print(f"    Direction: {direction}")
    print(f"    Side:      {side}")
    print(f"    Action:    {action}")
    print(f"    Count:     {contracts}")
    print(f"    Price:     {entry_cents}c")

    if status != "active":
        print(f"\n  Market is not active ({status}). Cannot place order.")
        print(f"  Market is not yet open for this time slot.")
        return

    if dry_run:
        print(f"\n  (dry-run: order NOT placed)")
        return

    # Place the order
    try:
        from runner import build_client
        from kalshi_python.models.create_order_request import CreateOrderRequest

        client = build_client(cfg)
        req = CreateOrderRequest(
            ticker=ticker,
            side=side,
            action=action,
            count=contracts,
            type="limit",
            yes_price=entry_cents if side == "yes" else None,
            no_price=entry_cents if side == "no" else None,
        )
        resp = client.create_order(**req.to_dict())
        order = resp.order
        oid = getattr(order, "order_id", "?")
        print(f"\n  Order placed: {oid}")
        print(f"  {action} {contracts}x {side} @ {entry_cents}c")

        # Start a watcher for this position
        from watcher import add_watcher
        store_path = Path(__file__).resolve().parent.parent / "watcher_store.json"
        add_watcher(
            store_path=store_path,
            ticker=ticker,
            entry_cents=entry_cents,
            side="LONG",
            contracts=contracts,
            stop_cents=max(1, entry_cents - 10),
            take_profit_cents=min(99, entry_cents + 10),
            title=market["title"],
            auto_exit=True,
        )
        print(f"  Watcher started for {ticker}")

    except Exception as e:
        print(f"  ORDER FAILED: {e}", file=sys.stderr)


# ── Exit execution ────────────────────────────────────────────────────────

def execute_exit(
    kalshi_ticker: str,
    side: str,
    contracts: int,
    exit_price_cents: int,
    reason: str,
    dry_run: bool = False,
) -> str | None:
    """Place an exit order on Kalshi.

    Returns the order_id on success, or None on failure / dry-run.
    """
    if side == "LONG":
        action = "sell"
        sdk_side = "yes"
    else:
        action = "buy"
        sdk_side = "yes"

    print(f"\n  {'[DRY-RUN] ' if dry_run else ''}EXIT TRIGGER ({reason}):")
    print(f"    Ticker:    {kalshi_ticker}")
    print(f"    Action:    {action} {contracts}x {sdk_side} @ {exit_price_cents}c")
    print(f"    Reason:    {reason}")

    if dry_run:
        print(f"    (dry-run: order NOT placed)")
        return None

    try:
        from runner import load_config, build_client
        from kalshi_python.models.create_order_request import CreateOrderRequest

        cfg = load_config()
        client = build_client(cfg)

        req = CreateOrderRequest(
            ticker=kalshi_ticker,
            side=sdk_side,
            action=action,
            count=contracts,
            type="limit",
            yes_price=exit_price_cents,
        )
        resp = client.create_order(**req.to_dict())
        order = resp.order
        oid = getattr(order, "order_id", "?")
        print(f"    Order placed: {oid}")
        return oid
    except Exception as e:
        print(f"    EXIT FAILED: {e}", file=sys.stderr)
        return None


# ── Bracket moneyness estimation ──────────────────────────────────────────

def estimate_contract_value(
    spot_usd: float,
    strike_usd: int,
    side: str = "LONG",
    contract_type: str = "above",
) -> int:
    """Estimate the YES contract value in cents given external spot price.

    For "above" brackets (e.g., BTC above $68,375):
      - If spot >> strike → YES ≈ 90-99c (deep in the money)
      - If spot ≈ strike → YES ≈ 40-60c (near the money)
      - If spot << strike → YES ≈ 1-10c (deep out of the money)

    This is a rough sigmoid estimate, NOT a precise fair value.
    """
    if strike_usd <= 0:
        return 50

    # Distance as percentage of strike
    pct_diff = (spot_usd - strike_usd) / strike_usd * 100

    # Rough sigmoid mapping: ±5% from strike maps to ~5c-95c
    # This is a heuristic; real pricing depends on time-to-expiry and volatility
    import math
    try:
        sigmoid_val = 1.0 / (1.0 + math.exp(-pct_diff * 1.5))
    except OverflowError:
        sigmoid_val = 1.0 if pct_diff > 0 else 0.0

    cents = max(1, min(99, int(sigmoid_val * 100)))
    return cents


# ── Main strategy ─────────────────────────────────────────────────────────

def run(client: Any, args: Any) -> None:
    """Crypto Sentinel: external-price-triggered position manager."""
    from runner import load_config, DEFAULT_HOST

    extra = getattr(args, "extra", [])

    # argparse.REMAINDER in runner.py may absorb --ticker into extra;
    # parse it from both locations so all invocation styles work.
    p = argparse.ArgumentParser(description="Crypto Sentinel options")
    p.add_argument("--ticker", type=str, default=None, help="Crypto asset or Kalshi ticker")
    p.add_argument("--asset", type=str, default=None, help="Crypto asset (BTC, ETH, SOL)")
    p.add_argument("--stop", type=float, default=None, help="Stop-loss USD price")
    p.add_argument("--tp", type=float, default=None, help="Take-profit USD price")
    p.add_argument("--strike", type=int, default=None, help="Bracket strike price USD")
    p.add_argument("--side", type=str, default="LONG", choices=["LONG", "SHORT"])
    p.add_argument("--contracts", type=int, default=None, help="Contracts held")
    p.add_argument("--kalshi-ticker", type=str, default=None, help="Kalshi ticker for exits")
    p.add_argument("--interval", type=float, default=10.0, help="Poll interval seconds")
    p.add_argument("--dry-run", action="store_true", help="Monitor only")
    p.add_argument("--scan-events", action="store_true", help="Scan for crypto events")
    p.add_argument("--scan-series", action="store_true", help="Scan crypto series (15min, hourly, etc.)")
    p.add_argument("--mode", default="watch", choices=["watch", "15min"],
                   help="Mode: watch (price monitor) or 15min (trade 15-min markets)")
    p.add_argument("--price-source", default="binance", help="Price source (binance or coingecko)")
    opts, _ = p.parse_known_args([a for a in extra if a != "--"])

    # Ticker from top-level args (if argparse didn't eat it) or from extra
    ticker_arg = getattr(args, "ticker", None) or opts.ticker
    if not ticker_arg:
        print("ERROR: --ticker is required. Pass a crypto symbol (BTC, ETH, SOL)")
        print("       or a Kalshi ticker (KXBTC-26FEB15-B68375).")
        return

    cfg = load_config()
    host = cfg.get("host", DEFAULT_HOST)

    # Resolve asset
    asset = opts.asset
    if not asset:
        asset = infer_asset(ticker_arg)
    if not asset:
        # Treat the ticker itself as an asset symbol
        if ticker_arg.upper() in COINGECKO_IDS:
            asset = ticker_arg.upper()
        else:
            print(f"  Cannot determine crypto asset from '{ticker_arg}'.")
            print(f"  Pass --asset BTC|ETH|SOL or use a recognized ticker.")
            return

    # Handle --scan-events
    if opts.scan_events:
        print(f"\n  Scanning for crypto/financials events on Kalshi...\n")
        events = scan_crypto_events(host)
        if not events:
            print("  No crypto/financials events found.")
        else:
            for ev in events:
                et = ev["event_ticker"]
                cat = ev["category"]
                title = ev["title"]
                mkts = ev.get("markets", [])
                print(f"  {et}")
                print(f"    Category: {cat}")
                print(f"    Title:    {title}")
                if mkts:
                    for m in mkts[:5]:
                        mt = m["ticker"]
                        yb = m["yes_bid"]
                        ya = m["yes_ask"]
                        vol = m["volume"]
                        st = m["status"]
                        print(f"    {mt:<45s} bid={yb:>2d} ask={ya:>3d} vol={vol:>6d} [{st}]")
                else:
                    print(f"    (no markets)")
                print()
        return

    # Handle --scan-series
    if opts.scan_series:
        print(f"\n  Scanning 15-minute crypto series on Kalshi...\n")
        series_list = list_15m_series(host)
        if not series_list:
            print("  No 15-minute crypto series found.")
        else:
            for s in series_list:
                print(f"  {s['asset']:<5s} {s['series']:<15s} {s['title']:<30s} events={s['events']}  {s['status']}")
        print(f"\n  Use --mode 15min to trade these markets.")
        return

    # Handle --mode 15min
    if opts.mode == "15min":
        run_15min_mode(asset, host, cfg, opts, dry_run=opts.dry_run)
        return

    # Initial price check
    print(f"\n  Crypto Sentinel")
    print(f"  {'=' * 60}")
    print(f"  Asset:        {asset}")
    print(f"  Side:         {opts.side}")
    print(f"  Stop-loss:    ${opts.stop:,.0f}" if opts.stop else "  Stop-loss:    (none)")
    print(f"  Take-profit:  ${opts.tp:,.0f}" if opts.tp else "  Take-profit:  (none)")
    print(f"  Dry-run:      {opts.dry_run}")
    print(f"  Interval:     {opts.interval}s")
    print(f"  Source:       {opts.price_source}")

    # Try to resolve bracket strike
    strike = opts.strike
    if not strike and ticker_arg.upper().startswith("KX"):
        strike = parse_bracket_strike(ticker_arg)
    if strike:
        print(f"  Strike:       ${strike:,}")

    # Find crypto positions on Kalshi
    kalshi_ticker = opts.kalshi_ticker
    contracts = opts.contracts
    side = opts.side

    print(f"\n  Checking Kalshi positions for {asset}...")
    positions = find_crypto_positions(cfg, host, asset)
    if positions:
        print(f"  Found {len(positions)} {asset} position(s):")
        for pos in positions:
            print(f"    {pos['ticker']:<40s} pos={pos['position']:>+4d} exposure=${pos['market_exposure_dollars']}")
            if not kalshi_ticker:
                kalshi_ticker = pos["ticker"]
                contracts = pos["contracts"]
                side = pos["side"]
    else:
        print(f"  No {asset} positions found on Kalshi.")

    # Also check resting orders
    orders = find_crypto_orders(cfg, host, asset)
    if orders:
        print(f"  Found {len(orders)} resting {asset} order(s):")
        for o in orders:
            print(f"    {o['ticker']:<40s} {o['action']}/{o['side']} {o['count']}x @ {o['yes_price']}c")
            if not kalshi_ticker:
                kalshi_ticker = o["ticker"]

    if not kalshi_ticker:
        if ticker_arg.upper() in COINGECKO_IDS:
            print(f"\n  No Kalshi {asset} positions or orders found.")
            print(f"  Will monitor {asset} price only (no exits to execute).")
        else:
            kalshi_ticker = ticker_arg

    if kalshi_ticker and not strike:
        strike = parse_bracket_strike(kalshi_ticker)

    # Validate we have something useful
    if not opts.stop and not opts.tp:
        current = fetch_crypto_price(asset, opts.price_source)
        if current:
            spot = current.get("usd", 0)
            print(f"\n  WARNING: No --stop or --tp set. Will monitor prices but cannot trigger exits.")
            print(f"  Current {asset} price: ${spot:,.0f}")
            print(f"  Suggested:  -- --stop {int(spot * 0.95)} --tp {int(spot * 1.05)}")
        else:
            print(f"\n  WARNING: No --stop or --tp set and price fetch failed.")

    contracts = contracts or 0

    print(f"\n  Kalshi ticker: {kalshi_ticker or '(none)'}")
    print(f"  Contracts:     {contracts or '(unknown)'}")
    print(f"\n  Monitoring {asset} price...  (Ctrl-C to stop)\n")
    print(f"  {'Time':<12s} {'Price':>12s} {'24h Chg':>10s} {'Est. Value':>10s} {'Status':<20s}")
    print(f"  {'-' * 70}")

    # State
    triggered_stop = False
    triggered_tp = False
    last_price = None
    consecutive_errors = 0
    MAX_ERRORS = 5

    try:
        while True:
            price_data = fetch_crypto_price(asset, opts.price_source)

            if price_data is None:
                consecutive_errors += 1
                if consecutive_errors >= MAX_ERRORS:
                    print(f"\n  {MAX_ERRORS} consecutive price fetch failures. Check network or rate limits.")
                    print(f"  CoinGecko free tier allows ~10-30 calls/min. Try increasing --interval.")
                time.sleep(opts.interval)
                continue

            consecutive_errors = 0
            spot = price_data.get("usd", 0)
            change_24h = price_data.get("usd_24h_change", 0) or 0
            now_str = datetime.now().strftime("%H:%M:%S")

            # Estimate contract value if we have a strike
            est_val_str = "--"
            if strike:
                est_cents = estimate_contract_value(spot, strike)
                est_val_str = f"{est_cents}c"

            # Direction indicator
            direction = ""
            if last_price is not None:
                if spot > last_price:
                    direction = " ^"
                elif spot < last_price:
                    direction = " v"

            status = "monitoring"

            # Check stop-loss (price drops below threshold)
            if opts.stop and not triggered_stop:
                if opts.side == "LONG" and spot <= opts.stop:
                    status = "STOP HIT"
                    triggered_stop = True
                elif opts.side == "SHORT" and spot >= opts.stop:
                    status = "STOP HIT"
                    triggered_stop = True

            # Check take-profit (price rises above threshold)
            if opts.tp and not triggered_tp:
                if opts.side == "LONG" and spot >= opts.tp:
                    status = "TP HIT"
                    triggered_tp = True
                elif opts.side == "SHORT" and spot <= opts.tp:
                    status = "TP HIT"
                    triggered_tp = True

            change_str = f"{change_24h:+.2f}%"
            print(f"  {now_str:<12s} ${spot:>10,.0f}{direction} {change_str:>10s} {est_val_str:>10s} {status:<20s}")

            # Execute exit if triggered
            if (triggered_stop or triggered_tp) and kalshi_ticker and contracts > 0:
                reason = "STOP-LOSS" if triggered_stop else "TAKE-PROFIT"

                # Estimate exit price in cents
                if strike:
                    exit_cents = estimate_contract_value(spot, strike)
                else:
                    # Without a strike, we can't estimate; use a conservative value
                    exit_cents = 50
                    print(f"  WARNING: No bracket strike known. Using {exit_cents}c as exit price.")
                    print(f"  For better execution, pass --strike <USD_PRICE>")

                oid = execute_exit(
                    kalshi_ticker=kalshi_ticker,
                    side=side,
                    contracts=contracts,
                    exit_price_cents=exit_cents,
                    reason=f"{reason}: {asset} @ ${spot:,.0f}",
                    dry_run=opts.dry_run,
                )

                if oid:
                    print(f"\n  Exit order placed: {oid}")
                    print(f"  Continuing to monitor... (order may need time to fill)")

                # Reset so we don't re-trigger on the same condition
                if triggered_stop:
                    triggered_stop = "executed"
                if triggered_tp:
                    triggered_tp = "executed"

            elif (triggered_stop or triggered_tp) and not kalshi_ticker:
                reason = "STOP-LOSS" if triggered_stop else "TAKE-PROFIT"
                print(f"\n  ALERT: {reason} triggered at ${spot:,.0f}")
                print(f"  No Kalshi ticker configured for auto-exit.")
                print(f"  Manually exit your position or pass --kalshi-ticker <TICKER>")
                if triggered_stop:
                    triggered_stop = "alerted"
                if triggered_tp:
                    triggered_tp = "alerted"

            last_price = spot
            time.sleep(opts.interval)

    except KeyboardInterrupt:
        print(f"\n\n  Sentinel stopped.")
        if last_price:
            print(f"  Last {asset} price: ${last_price:,.0f}")
        if triggered_stop and triggered_stop != "executed":
            print(f"  WARNING: Stop was triggered but exit was not executed!")
        if triggered_tp and triggered_tp != "executed":
            print(f"  WARNING: TP was triggered but exit was not executed!")
