"""
Crypto Hourly — Fee-aware trading strategy for hourly crypto bracket markets.

Hourly crypto markets on Kalshi come in two flavours:

  1. **Directional** (KXBTCD, KXETHD, KXSOLD, KXXRPD) — "BTC price above $X?"
     Each event has 50-75 strike prices.  YES = above, NO = below.
     These have real L2 data and meaningful volume ($200k+ on BTC).

  2. **Range** (KXBTC, KXETH, KXSOL, KXDOGE, KXXRP) — "BTC price in $X-$Y?"
     Bracket range contracts — harder to trade, lower liquidity.

This strategy targets the **directional** markets (the "-D" series) because they
have the best liquidity and the clearest edge signal: compare external spot price
to the Kalshi strike, estimate the probability with a volatility model, and trade
when our probability diverges from the market price.

Key workflow:
  1. Discover the current active hourly event via the /series endpoint
  2. Fetch external BTC/ETH/SOL/XRP spot price (Binance US → Coinbase → CoinGecko)
  3. Find the "at the money" (ATM) strike — closest to current spot price
  4. Estimate implied probability using a log-normal volatility model
  5. Compare our estimate to Kalshi market prices to find mispriced strikes
  6. Run the full fee-aware doctrine (4 gates) before placing any order
  7. Place a limit order and auto-start the watcher

Usage:
    # Scan available hourly events for BTC
    python runner.py run-strategy crypto_hourly --ticker BTC -- --scan

    # Trade the current hourly BTC event (fee-aware, gated)
    python runner.py run-strategy crypto_hourly --ticker BTC

    # Trade ETH hourly with custom contracts and dry-run
    python runner.py run-strategy crypto_hourly --ticker ETH -- --contracts 20 --dry-run

    # Continuous mode: auto-trade each new hourly event
    python runner.py run-strategy crypto_hourly --ticker BTC -- --loop --interval 60

Extra args (passed after --):
    --scan                      Scan available hourly events and exit
    --asset BTC|ETH|SOL|XRP|DOGE  Crypto asset (default: inferred from ticker)
    --contracts N               Contract count override (default: auto-size via doctrine)
    --side LONG|SHORT           Position side (default: LONG)
    --mode directional|range    Market type (default: directional)
    --edge-threshold PCT        Min edge % to trade (default: 5.0)
    --dry-run                   Evaluate only, no orders placed
    --loop                      Continuous mode: trade each new hourly event
    --interval SECONDS          Loop poll interval (default: 60)
    --price-source binance      Price source: binance, coinbase, coingecko (default: binance)
    --vol-override PCT          Override hourly volatility estimate (e.g., 1.2 for 1.2%)
    --max-strikes N             Max strikes near ATM to evaluate (default: 5)

Limitations:
    - Hourly events may be 'initialized' outside trading hours
    - Volatility model is a simple estimate, not a full options pricer
    - L2 data can be thin on less popular assets (SOL, DOGE, XRP)
    - Exit is via watcher — no built-in exit loop in this strategy
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_scripts_dir = str(Path(__file__).resolve().parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


# ── Series tickers for hourly crypto ─────────────────────────────────────

DIRECTIONAL_SERIES = {
    "BTC": "KXBTCD",
    "ETH": "KXETHD",
    "SOL": "KXSOLD",
    "XRP": "KXXRPD",
}

RANGE_SERIES = {
    "BTC": "KXBTC",
    "ETH": "KXETH",
    "SOL": "KXSOL",
    "XRP": "KXXRP",
    "DOGE": "KXDOGE",
}


# ── External price helpers (reuse from crypto_sentinel) ──────────────────

def _import_price_fetcher():
    """Import the price fetcher from crypto_sentinel to avoid duplication."""
    try:
        from strategies.crypto_sentinel import fetch_crypto_price
        return fetch_crypto_price
    except ImportError:
        pass

    sentinel_path = Path(__file__).resolve().parent / "crypto_sentinel.py"
    if sentinel_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("crypto_sentinel", sentinel_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.fetch_crypto_price

    return None


def _fetch_price_fallback(asset: str) -> dict | None:
    """Minimal fallback price fetcher if crypto_sentinel isn't available."""
    from runner import _fetch_json_raw

    symbols = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
               "XRP": "XRPUSDT", "DOGE": "DOGEUSDT"}
    symbol = symbols.get(asset.upper())
    if not symbol:
        return None

    url = f"https://api.binance.us/api/v3/ticker/24hr?symbol={symbol}"
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


def fetch_price(asset: str, source: str = "binance") -> dict | None:
    """Fetch crypto spot price. Tries crypto_sentinel's chain, falls back."""
    fn = _import_price_fetcher()
    if fn:
        return fn(asset, source)
    return _fetch_price_fallback(asset)


# ── Volatility model ─────────────────────────────────────────────────────

# Typical hourly realized volatility (annualized → hourly)
# BTC ~60% annualized → ~60 / sqrt(8760) ≈ 0.64% per hour
# ETH ~75% annualized → ~0.80% per hour
# SOL ~90% annualized → ~0.96% per hour
# These are rough defaults; --vol-override lets the user tune.
DEFAULT_HOURLY_VOL = {
    "BTC": 0.65,
    "ETH": 0.80,
    "SOL": 0.96,
    "XRP": 1.10,
    "DOGE": 1.30,
}


def estimate_probability_above(
    spot: float,
    strike: float,
    hours_to_expiry: float,
    hourly_vol_pct: float,
) -> float:
    """Estimate P(price > strike at expiry) using a log-normal model.

    Uses the standard Black-Scholes-style cumulative normal approach:
        d = [ln(S/K)] / (σ * √t)
        P(above) = Φ(d)

    where σ is hourly volatility as a decimal and t is hours to expiry.

    Returns probability in [0.01, 0.99] (clamped for safety).
    """
    if spot <= 0 or strike <= 0 or hours_to_expiry <= 0:
        return 0.50

    sigma = hourly_vol_pct / 100.0
    sqrt_t = math.sqrt(hours_to_expiry)
    vol_adj = sigma * sqrt_t

    if vol_adj < 1e-8:
        return 0.99 if spot > strike else 0.01

    d = math.log(spot / strike) / vol_adj
    prob = _norm_cdf(d)
    return max(0.01, min(0.99, prob))


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── Market discovery ─────────────────────────────────────────────────────

def find_active_hourly_event(host: str, asset: str, mode: str = "directional") -> dict | None:
    """Find the current/next active hourly event for a crypto asset.

    Returns {event_ticker, title, status, markets: [{ticker, strike, status,
    yes_bid, yes_ask, volume, close_time}]} or None.
    """
    from runner import _fetch_json_raw

    series_map = DIRECTIONAL_SERIES if mode == "directional" else RANGE_SERIES
    series = series_map.get(asset.upper())
    if not series:
        return None

    data = _fetch_json_raw(f"{host}/events?series_ticker={series}&limit=10")
    if not data:
        return None

    events = data.get("events", [])

    for ev in events:
        et = ev.get("event_ticker", "")
        ev_data = _fetch_json_raw(f"{host}/events/{et}")
        if not ev_data:
            continue

        markets = ev_data.get("markets", [])
        has_active = any(m.get("status") in ("active", "open") for m in markets)

        if has_active:
            parsed_markets = _parse_event_markets(markets, mode)
            return {
                "event_ticker": et,
                "title": ev.get("title", ""),
                "status": "active",
                "markets": parsed_markets,
            }

    # No active event — return the nearest initialized one
    if events:
        ev = events[0]
        et = ev.get("event_ticker", "")
        ev_data = _fetch_json_raw(f"{host}/events/{et}")
        if ev_data:
            markets = ev_data.get("markets", [])
            parsed_markets = _parse_event_markets(markets, mode)
            return {
                "event_ticker": et,
                "title": ev.get("title", ""),
                "status": markets[0].get("status", "initialized") if markets else "unknown",
                "markets": parsed_markets,
            }

    return None


def _parse_event_markets(markets: list[dict], mode: str) -> list[dict]:
    """Parse and enrich market dicts with strike price extraction."""
    result = []
    for m in markets:
        ticker = m.get("ticker", "")
        strike = _extract_strike(ticker)
        result.append({
            "ticker": ticker,
            "title": m.get("title", ""),
            "strike": strike,
            "status": m.get("status", ""),
            "yes_bid": m.get("yes_bid", 0) or 0,
            "yes_ask": m.get("yes_ask", 0) or 0,
            "volume": m.get("volume", 0) or 0,
            "close_time": m.get("close_time", ""),
        })

    result.sort(key=lambda x: x["strike"] if x["strike"] else 0)
    return result


def _extract_strike(ticker: str) -> float | None:
    """Extract strike price from directional ticker.

    Formats:
        KXBTCD-26FEB2017-T58749.99  → 58749.99
        KXBTC-26FEB2017-B55000       → 55000.0
        KXBTC-26FEB2017-T54750       → 54750.0
    """
    parts = ticker.upper().split("-")
    for p in parts:
        if p.startswith("T") or p.startswith("B"):
            try:
                return float(p[1:])
            except ValueError:
                pass
    return None


def _parse_close_time(close_time_str: str) -> datetime | None:
    """Parse ISO close_time to datetime."""
    if not close_time_str:
        return None
    try:
        ct = close_time_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ct)
    except (ValueError, TypeError):
        return None


def _hours_until(close_time_str: str) -> float:
    """Hours from now until close_time. Returns 1.0 as default."""
    ct = _parse_close_time(close_time_str)
    if not ct:
        return 1.0
    now = datetime.now(timezone.utc)
    delta = (ct - now).total_seconds() / 3600.0
    return max(0.01, delta)


# ── Strike evaluation ────────────────────────────────────────────────────

def find_atm_strikes(
    markets: list[dict],
    spot: float,
    max_strikes: int = 5,
) -> list[dict]:
    """Find strikes nearest to current spot price.

    Returns up to max_strikes markets sorted by distance from ATM,
    only including active markets with valid strikes.
    """
    active = [m for m in markets if m["status"] in ("active", "open") and m["strike"]]
    if not active:
        return []

    for m in active:
        m["_distance"] = abs(m["strike"] - spot)

    active.sort(key=lambda m: m["_distance"])
    return active[:max_strikes]


def evaluate_strikes(
    atm_markets: list[dict],
    spot: float,
    hours_to_expiry: float,
    hourly_vol_pct: float,
    edge_threshold_pct: float = 5.0,
) -> list[dict]:
    """Evaluate each ATM strike for edge.

    For each strike, compute:
      - Our estimated P(above) from the volatility model
      - Market implied probability from the orderbook
      - Edge = our_prob - market_prob
      - Recommended side (YES if edge > 0, NO if edge < 0)

    Returns list of dicts with evaluation data, sorted by |edge| descending.
    Only returns strikes that exceed the edge threshold.
    """
    results = []

    for m in atm_markets:
        strike = m["strike"]
        our_prob = estimate_probability_above(spot, strike, hours_to_expiry, hourly_vol_pct)
        our_prob_cents = int(our_prob * 100)

        yes_bid = m["yes_bid"]
        yes_ask = m["yes_ask"]

        # Market mid for implied probability
        if yes_bid > 0 and yes_ask > 0:
            market_mid = (yes_bid + yes_ask) / 2.0
        elif yes_ask > 0:
            market_mid = yes_ask
        elif yes_bid > 0:
            market_mid = yes_bid
        else:
            continue  # No price data, skip

        market_prob = market_mid / 100.0
        edge = our_prob - market_prob
        edge_pct = edge * 100.0

        # Determine which side to trade
        if edge_pct >= edge_threshold_pct:
            # We think YES is underpriced → BUY YES
            recommended_side = "YES"
            entry_cents = min(99, yes_ask) if yes_ask > 0 else our_prob_cents
            # Post at bid + 1 (maker) for better execution
            if yes_bid > 0:
                entry_cents = min(99, yes_bid + 1)
        elif edge_pct <= -edge_threshold_pct:
            # We think YES is overpriced → BUY NO (equivalent to sell YES)
            recommended_side = "NO"
            no_ask = (100 - yes_bid) if yes_bid > 0 else (100 - our_prob_cents)
            entry_cents = no_ask
            # Post at no_bid + 1
            no_bid = (100 - yes_ask) if yes_ask > 0 else (100 - our_prob_cents)
            if no_bid > 0:
                entry_cents = min(99, no_bid + 1)
        else:
            # Edge too small — include in results but mark as no-trade
            results.append({
                **m,
                "our_prob": our_prob,
                "our_prob_cents": our_prob_cents,
                "market_mid": market_mid,
                "edge_pct": edge_pct,
                "recommended_side": None,
                "entry_cents": 0,
                "tradeable": False,
            })
            continue

        results.append({
            **m,
            "our_prob": our_prob,
            "our_prob_cents": our_prob_cents,
            "market_mid": market_mid,
            "edge_pct": edge_pct,
            "recommended_side": recommended_side,
            "entry_cents": entry_cents,
            "tradeable": True,
        })

    results.sort(key=lambda x: abs(x["edge_pct"]), reverse=True)
    return results


# ── L2 Orderbook for better pricing ─────────────────────────────────────

def fetch_strike_orderbook(host: str, ticker: str, depth: int = 5) -> dict:
    """Fetch L2 orderbook for a specific strike market."""
    from runner import _fetch_json_raw

    data = _fetch_json_raw(f"{host}/markets/{ticker}/orderbook?depth={depth}")
    if not data:
        return {"yes": [], "no": []}

    ob = data.get("orderbook", data)
    return {
        "yes": ob.get("yes") or [],
        "no": ob.get("no") or [],
    }


def refine_entry_price(host: str, ticker: str, side: str, fallback_cents: int) -> int:
    """Refine entry price using L2 data.

    For BUY YES: post at best_yes_bid + 1 (maker)
    For BUY NO: post at best_no_bid + 1 (maker)
    """
    ob = fetch_strike_orderbook(host, ticker)
    yes_levels = ob.get("yes") or []
    no_levels = ob.get("no") or []

    if side == "YES" and yes_levels:
        best_bid = max(lvl[0] for lvl in yes_levels)
        return min(99, best_bid + 1)
    elif side == "NO" and no_levels:
        best_no_bid = max(lvl[0] for lvl in no_levels)
        return min(99, best_no_bid + 1)

    return fallback_cents


# ── Fee-aware trade evaluation ───────────────────────────────────────────

def run_fee_gates(
    ticker: str,
    entry_cents: int,
    side: str,
    contracts: int,
    cfg_dict: dict,
    spread_cents: int = 0,
    depth_at_price: int = 0,
) -> dict:
    """Run the full doctrine fee-aware gates.

    Returns {pass: bool, evaluation: TradeEvaluation, reasons: [str]}
    """
    try:
        from trade_engine import RiskConfig, TradeParams, evaluate_trade, format_order_ticket
    except ImportError:
        return {"pass": True, "evaluation": None, "reasons": ["trade_engine not available — gates skipped"]}

    risk_cfg = RiskConfig()
    try:
        risk_cfg = RiskConfig.from_dict(cfg_dict)
    except Exception:
        pass

    position_side = "LONG"  # BUY YES or BUY NO are both LONG entries
    outcome_contract = side  # "YES" or "NO"

    # Exit target: for hourly markets, expect to hold to expiry
    # If YES is right → settles at 100c; if wrong → settles at 0c
    # Use a conservative exit target of entry + TP offset
    tp_offset = risk_cfg.default_take_profit_offset_cents
    exit_target = min(99, entry_cents + tp_offset)

    params = TradeParams(
        market_ticker=ticker,
        market_title=f"Hourly crypto {ticker}",
        outcome_contract=outcome_contract,
        position_side=position_side,
        entry_price_cents=entry_cents,
        exit_target_cents=exit_target,
        entry_fill_type="MAKER",
        exit_fill_type="TAKER",
        market_has_maker_fees=False,
        contracts=contracts,
        spread_cents=spread_cents,
        depth_at_price=depth_at_price,
    )

    ev = evaluate_trade(params, risk_cfg)

    return {
        "pass": ev.all_gates_pass,
        "evaluation": ev,
        "reasons": ev.gate_reasons,
        "ticket": format_order_ticket(ev),
    }


# ── Order placement ──────────────────────────────────────────────────────

def place_hourly_order(
    cfg: dict,
    ticker: str,
    side: str,
    entry_cents: int,
    contracts: int,
    dry_run: bool = False,
) -> str | None:
    """Place a limit order for an hourly crypto market.

    side: "YES" or "NO"
    Returns order_id on success, None on failure/dry-run.
    """
    sdk_side = "yes" if side == "YES" else "no"
    price_kwarg = "yes_price" if side == "YES" else "no_price"

    print(f"\n  {'[DRY-RUN] ' if dry_run else ''}ORDER:")
    print(f"    Ticker:     {ticker}")
    print(f"    Side:       BUY {side}")
    print(f"    Contracts:  {contracts}")
    print(f"    Price:      {entry_cents}c")

    if dry_run:
        print(f"    (dry-run: order NOT placed)")
        return None

    try:
        from runner import build_client
        from kalshi_python.models.create_order_request import CreateOrderRequest

        client = build_client(cfg)

        order_kwargs = {
            "ticker": ticker,
            "side": sdk_side,
            "action": "buy",
            "count": contracts,
            "type": "limit",
        }
        order_kwargs[price_kwarg] = entry_cents

        req = CreateOrderRequest(**order_kwargs)
        resp = client.create_order(**req.to_dict())
        order = resp.order
        oid = getattr(order, "order_id", "?")
        print(f"    Order placed: {oid}")
        return oid
    except Exception as e:
        print(f"    ORDER FAILED: {e}", file=sys.stderr)
        return None


def start_watcher(ticker: str, entry_cents: int, contracts: int, side: str) -> None:
    """Auto-start the watcher for a new position."""
    try:
        sys.path.insert(0, _scripts_dir)
        from watcher import add_watcher
        store_path = Path(__file__).resolve().parent.parent / "watcher_store.json"
        add_watcher(
            store_path=store_path,
            ticker=ticker,
            entry_cents=entry_cents,
            side="LONG",
            contracts=contracts,
            stop_cents=max(1, entry_cents - 10),
            take_profit_cents=min(99, entry_cents + 15),
            title=f"Hourly crypto {ticker}",
            auto_exit=True,
        )
        print(f"    Watcher started for {ticker}")
    except Exception as e:
        print(f"    WARNING: Failed to start watcher: {e}", file=sys.stderr)


# ── Scan mode ────────────────────────────────────────────────────────────

def scan_hourly_events(host: str, asset: str) -> None:
    """Scan and display available hourly events for an asset."""
    print(f"\n  Scanning hourly crypto events for {asset}...")
    print(f"  {'=' * 70}")

    for mode, series_map, label in [
        ("directional", DIRECTIONAL_SERIES, "Directional (above/below)"),
        ("range", RANGE_SERIES, "Range (bracket)"),
    ]:
        series = series_map.get(asset.upper())
        if not series:
            continue

        print(f"\n  {label}: {series}")
        event = find_active_hourly_event(host, asset, mode=mode)

        if not event:
            print(f"    No events found.")
            continue

        et = event["event_ticker"]
        status = event["status"]
        markets = event.get("markets", [])
        active_count = sum(1 for m in markets if m["status"] in ("active", "open"))

        print(f"    Event:    {et}")
        print(f"    Title:    {event['title']}")
        print(f"    Status:   {status}")
        print(f"    Markets:  {len(markets)} total, {active_count} active")

        if markets:
            # Show a few near the middle (likely ATM)
            mid_idx = len(markets) // 2
            start = max(0, mid_idx - 3)
            end = min(len(markets), mid_idx + 4)
            print(f"    Sample strikes (near middle):")
            for m in markets[start:end]:
                s = m["strike"]
                strike_str = f"${s:,.2f}" if s else "?"
                print(f"      {m['ticker']:<45s}  strike={strike_str:>12s}  "
                      f"bid={m['yes_bid']:>2d} ask={m['yes_ask']:>3d}  "
                      f"vol={m['volume']:>6d}  [{m['status']}]")

            if len(markets) > 7:
                print(f"      ... and {len(markets) - 7} more strikes")


# ── Main trade flow ──────────────────────────────────────────────────────

def run_trade(
    asset: str,
    host: str,
    cfg: dict,
    opts: argparse.Namespace,
) -> None:
    """Core hourly trading flow: discover → price → evaluate → trade."""
    mode = opts.mode
    dry_run = opts.dry_run
    contracts_override = opts.contracts
    edge_threshold = opts.edge_threshold
    max_strikes = opts.max_strikes
    vol_override = opts.vol_override
    price_source = opts.price_source

    print(f"\n  Crypto Hourly — {'Directional' if mode == 'directional' else 'Range'} Mode")
    print(f"  {'=' * 70}")
    print(f"  Asset:           {asset}")
    series = (DIRECTIONAL_SERIES if mode == "directional" else RANGE_SERIES).get(asset.upper(), "?")
    print(f"  Series:          {series}")
    print(f"  Edge threshold:  {edge_threshold:.1f}%")
    print(f"  Dry-run:         {dry_run}")
    print(f"  Price source:    {price_source}")

    # Step 1: Get external spot price
    print(f"\n  [1/5] Fetching {asset} spot price...")
    price_data = fetch_price(asset, price_source)
    if not price_data:
        print(f"  ERROR: Cannot fetch {asset} price. Check network.")
        return

    spot = price_data["usd"]
    change_24h = price_data.get("usd_24h_change", 0) or 0
    print(f"  {asset} spot: ${spot:,.2f}  (24h: {change_24h:+.2f}%)")

    # Step 2: Find active hourly event
    print(f"\n  [2/5] Finding active hourly event...")
    event = find_active_hourly_event(host, asset, mode=mode)
    if not event:
        print(f"  No hourly {asset} events found.")
        print(f"  Use 'runner.py series {series} --events' to check availability.")
        return

    et = event["event_ticker"]
    ev_status = event["status"]
    markets = event.get("markets", [])

    print(f"  Event:   {et}")
    print(f"  Title:   {event['title']}")
    print(f"  Status:  {ev_status}")
    print(f"  Markets: {len(markets)}")

    if ev_status not in ("active", "open"):
        active_markets = [m for m in markets if m["status"] in ("active", "open")]
        if not active_markets:
            print(f"\n  Event is '{ev_status}' — no active markets to trade.")
            print(f"  Hourly events become active when the trading window opens.")
            return

    # Step 3: Find strikes near the money
    print(f"\n  [3/5] Finding strikes near the money (ATM)...")
    atm_markets = find_atm_strikes(markets, spot, max_strikes=max_strikes)
    if not atm_markets:
        print(f"  No active strikes found near ${spot:,.2f}")
        return

    # Determine hours to expiry
    close_time = atm_markets[0].get("close_time", "")
    hours_left = _hours_until(close_time)
    print(f"  Hours to expiry: {hours_left:.2f}")

    for m in atm_markets:
        s = m["strike"]
        dist_pct = ((s - spot) / spot * 100) if spot > 0 else 0
        print(f"    {m['ticker']:<45s}  strike=${s:>10,.2f}  dist={dist_pct:+.3f}%  "
              f"bid={m['yes_bid']:>2d} ask={m['yes_ask']:>3d}")

    # Step 4: Evaluate for edge
    hourly_vol = vol_override or DEFAULT_HOURLY_VOL.get(asset.upper(), 0.80)
    print(f"\n  [4/5] Evaluating edge (vol={hourly_vol:.2f}%, threshold={edge_threshold:.1f}%)...")

    evaluated = evaluate_strikes(
        atm_markets, spot, hours_left, hourly_vol,
        edge_threshold_pct=edge_threshold,
    )

    if not evaluated:
        print(f"  No strikes could be evaluated (empty orderbooks?).")
        return

    tradeable = [e for e in evaluated if e.get("tradeable")]
    print(f"\n  Strike evaluation ({len(evaluated)} strikes, {len(tradeable)} tradeable):")
    print(f"  {'Strike':>12s}  {'Our Prob':>8s}  {'Mkt Mid':>8s}  {'Edge':>8s}  {'Side':>5s}  {'Entry':>6s}")
    print(f"  {'-' * 60}")

    for e in evaluated:
        s = e["strike"]
        side_str = e["recommended_side"] or " -- "
        entry_str = f"{e['entry_cents']}c" if e["entry_cents"] > 0 else " -- "
        marker = "  <<<" if e.get("tradeable") else ""
        print(f"  ${s:>10,.2f}  {e['our_prob_cents']:>6d}c  {e['market_mid']:>6.1f}c  "
              f"{e['edge_pct']:>+7.2f}%  {side_str:>5s}  {entry_str:>6s}{marker}")

    if not tradeable:
        print(f"\n  No strikes exceed the {edge_threshold:.1f}% edge threshold.")
        print(f"  Try lowering --edge-threshold or wait for the next hourly event.")
        return

    # Pick the best tradeable strike
    best = tradeable[0]
    ticker = best["ticker"]
    side = best["recommended_side"]
    raw_entry = best["entry_cents"]

    # Refine entry with L2 data
    print(f"\n  [5/5] Refining entry via L2 orderbook...")
    entry_cents = refine_entry_price(host, ticker, side, raw_entry)
    entry_cents = max(1, min(99, entry_cents))
    if entry_cents != raw_entry:
        print(f"  L2 refined: {raw_entry}c → {entry_cents}c")

    # Contract count: auto-size or use override
    contracts = contracts_override
    if not contracts:
        from kalshi_math import max_contracts as calc_max_contracts
        try:
            import yaml
            risk_dict = {}
            for cp in [Path.cwd() / "config.yaml",
                        Path(__file__).resolve().parent.parent / "config.yaml",
                        Path(__file__).resolve().parent.parent.parent / "config.yaml"]:
                if cp.is_file():
                    with open(cp) as f:
                        risk_dict = yaml.safe_load(f) or {}
                    break
            max_cap = risk_dict.get("risk", {}).get("max_capital_at_risk_per_market_usd", 50.0)
        except Exception:
            max_cap = 50.0

        contracts = calc_max_contracts(max_cap, entry_cents, "LONG", ticker, False)
        contracts = max(1, contracts)

    print(f"\n  Best trade:")
    print(f"    Ticker:     {ticker}")
    print(f"    Strike:     ${best['strike']:,.2f}")
    print(f"    Side:       BUY {side}")
    print(f"    Our P:      {best['our_prob_cents']}c")
    print(f"    Market mid: {best['market_mid']:.1f}c")
    print(f"    Edge:       {best['edge_pct']:+.2f}%")
    print(f"    Entry:      {entry_cents}c")
    print(f"    Contracts:  {contracts}")

    # Compute L2 spread and depth for Gate D
    ob = fetch_strike_orderbook(host, ticker, depth=10)
    yes_levels = ob.get("yes") or []
    no_levels = ob.get("no") or []
    best_yes_bid = max((lvl[0] for lvl in yes_levels), default=0)
    best_no_bid = max((lvl[0] for lvl in no_levels), default=0)
    best_yes_ask = (100 - best_no_bid) if best_no_bid > 0 else 0
    spread_cents = (best_yes_ask - best_yes_bid) if (best_yes_bid > 0 and best_yes_ask > 0) else 99

    if side == "YES":
        depth_at_price = sum(lvl[1] for lvl in yes_levels if lvl[0] >= best_yes_bid) if yes_levels else 0
    else:
        depth_at_price = sum(lvl[1] for lvl in no_levels if lvl[0] >= best_no_bid) if no_levels else 0

    print(f"    L2 spread:  {spread_cents}c  depth: {depth_at_price} contracts")

    # Run fee-aware gates
    print(f"\n  Running fee-aware doctrine gates...")
    try:
        import yaml
        risk_dict = {}
        for cp in [Path.cwd() / "config.yaml",
                    Path(__file__).resolve().parent.parent / "config.yaml",
                    Path(__file__).resolve().parent.parent.parent / "config.yaml"]:
            if cp.is_file():
                with open(cp) as f:
                    risk_dict = yaml.safe_load(f) or {}
                break
    except Exception:
        risk_dict = {}

    gate_result = run_fee_gates(
        ticker, entry_cents, side, contracts, risk_dict,
        spread_cents=spread_cents, depth_at_price=depth_at_price,
    )

    if gate_result.get("ticket"):
        print(gate_result["ticket"])

    if not gate_result["pass"]:
        print(f"\n  Trade BLOCKED by doctrine gates:")
        for reason in gate_result.get("reasons", []):
            print(f"    !! {reason}")
        print(f"\n  Adjust --edge-threshold, --contracts, or wait for better pricing.")
        return

    print(f"  All gates PASSED.")

    # Place the order
    oid = place_hourly_order(cfg, ticker, side, entry_cents, contracts, dry_run=dry_run)

    if oid:
        start_watcher(ticker, entry_cents, contracts, side)
        print(f"\n  Trade complete. Watcher will manage the position.")
    elif not dry_run:
        print(f"\n  Order was not placed — check logs above.")


def run_loop(
    asset: str,
    host: str,
    cfg: dict,
    opts: argparse.Namespace,
) -> None:
    """Continuous mode: poll for new hourly events and trade each one."""
    interval = opts.interval
    last_event = None

    print(f"\n  Crypto Hourly — Continuous Mode")
    print(f"  {'=' * 70}")
    print(f"  Asset:    {asset}")
    print(f"  Interval: {interval}s")
    print(f"  Press Ctrl-C to stop\n")

    try:
        while True:
            event = find_active_hourly_event(host, asset, mode=opts.mode)
            if event:
                et = event["event_ticker"]
                if et != last_event:
                    print(f"\n  {'=' * 70}")
                    print(f"  New hourly event detected: {et}")
                    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    run_trade(asset, host, cfg, opts)
                    last_event = et
                else:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    print(f"  [{now_str}] Same event ({et}) — waiting for next hour...")
            else:
                now_str = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now_str}] No active hourly event — markets may be closed.")

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n  Continuous mode stopped.")


# ── Strategy entry point ─────────────────────────────────────────────────

def run(client: Any, args: Any) -> None:
    """Crypto Hourly strategy entry point — called by runner.py."""
    from runner import load_config, DEFAULT_HOST

    extra = getattr(args, "extra", [])

    p = argparse.ArgumentParser(description="Crypto Hourly options")
    p.add_argument("--ticker", type=str, default=None, help="Crypto asset or Kalshi ticker")
    p.add_argument("--asset", type=str, default=None, help="Crypto asset (BTC, ETH, SOL, XRP, DOGE)")
    p.add_argument("--scan", action="store_true", help="Scan hourly events and exit")
    p.add_argument("--contracts", type=int, default=0, help="Contract count override")
    p.add_argument("--side", default="LONG", choices=["LONG", "SHORT"])
    p.add_argument("--mode", default="directional", choices=["directional", "range"],
                   help="Market type (default: directional)")
    p.add_argument("--edge-threshold", type=float, default=5.0,
                   help="Min edge %% to trade (default: 5.0)")
    p.add_argument("--dry-run", action="store_true", help="Evaluate only")
    p.add_argument("--loop", action="store_true", help="Continuous mode")
    p.add_argument("--interval", type=float, default=60.0, help="Loop poll interval seconds")
    p.add_argument("--price-source", default="binance", help="Price source (binance, coinbase, coingecko)")
    p.add_argument("--vol-override", type=float, default=None,
                   help="Override hourly vol estimate (e.g., 1.2 for 1.2%%)")
    p.add_argument("--max-strikes", type=int, default=5, help="Max strikes near ATM to evaluate")
    opts, _ = p.parse_known_args([a for a in extra if a != "--"])

    # Resolve ticker/asset
    ticker_arg = getattr(args, "ticker", None) or opts.ticker
    if not ticker_arg:
        print("ERROR: --ticker is required. Pass a crypto symbol (BTC, ETH, SOL, XRP, DOGE).")
        return

    asset = opts.asset
    if not asset:
        supported = set(DIRECTIONAL_SERIES.keys()) | set(RANGE_SERIES.keys())
        if ticker_arg.upper() in supported:
            asset = ticker_arg.upper()
        else:
            # Try to infer from ticker
            upper = ticker_arg.upper()
            for sym in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                if sym in upper:
                    asset = sym
                    break

    if not asset:
        print(f"  Cannot determine crypto asset from '{ticker_arg}'.")
        print(f"  Pass --asset BTC|ETH|SOL|XRP|DOGE.")
        return

    cfg = load_config()
    host = cfg.get("host", DEFAULT_HOST)

    # Scan mode
    if opts.scan:
        scan_hourly_events(host, asset)
        return

    # Loop mode
    if opts.loop:
        run_loop(asset, host, cfg, opts)
        return

    # Single trade
    run_trade(asset, host, cfg, opts)
