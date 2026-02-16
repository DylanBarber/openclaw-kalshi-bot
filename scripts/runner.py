#!/usr/bin/env python3
"""
Kalshi Bot CLI – trade prediction markets from the command line.

Usage:
    python runner.py events [query] [--category Politics] [--limit 50]
    python runner.py markets search <query> [--category Economics] [--limit 20]
    python runner.py markets search --event KXDEELRIP-40
    python runner.py markets get <ticker>
    python runner.py orderbook <ticker> [--depth 10]
    python runner.py buy <ticker> <count> <price> [--side yes]
    python runner.py sell <ticker> <count> <price> [--side yes]
    python runner.py cancel <order_id>
    python runner.py orders [--status resting] [--ticker TICKER]
    python runner.py positions [--ticker TICKER] [--event EVENT]
    python runner.py balance
    python runner.py fills [--ticker TICKER] [--limit 20]
    python runner.py series [--category Crypto] [--frequency fifteen_min]
    python runner.py series KXBTC15M [--events]
    python runner.py run-strategy <strategy_name> [--ticker TICKER] [-- ...]

Market discovery uses the /events endpoint (not /markets, which only returns
esports combo tickers).  The `events`, `markets search`, and `series` commands
use raw HTTP and do NOT require Kalshi SDK auth.

Credentials are loaded from config.yaml (or KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH env vars).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

DEFAULT_HOST = "https://api.elections.kalshi.com/trade-api/v2"
CONFIG_FILENAME = "config.yaml"


def _find_config() -> Path | None:
    """Walk up from cwd looking for config.yaml, fall back to script dir."""
    candidates = [
        Path.cwd() / CONFIG_FILENAME,
        Path(__file__).resolve().parent / CONFIG_FILENAME,
        Path(__file__).resolve().parent.parent / CONFIG_FILENAME,
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def load_config() -> dict[str, Any]:
    """Return merged config from file + env vars. Env vars take precedence."""
    cfg: dict[str, Any] = {}

    config_path = _find_config()
    if config_path:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}

    # Env-var overrides
    if os.getenv("KALSHI_API_KEY_ID"):
        cfg["api_key_id"] = os.environ["KALSHI_API_KEY_ID"]
    if os.getenv("KALSHI_PRIVATE_KEY_PATH"):
        cfg["private_key_path"] = os.environ["KALSHI_PRIVATE_KEY_PATH"]
    if os.getenv("KALSHI_HOST"):
        cfg["host"] = os.environ["KALSHI_HOST"]

    return cfg


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def build_client(cfg: dict[str, Any]):
    """Instantiate and return a configured KalshiClient."""
    try:
        import kalshi_python
    except ImportError:
        print("ERROR: kalshi-python is not installed. Run:\n  pip install kalshi-python", file=sys.stderr)
        sys.exit(1)

    host = cfg.get("host", DEFAULT_HOST)
    configuration = kalshi_python.Configuration(host=host)

    api_key_id = cfg.get("api_key_id")
    private_key_path = cfg.get("private_key_path")
    private_key_pem = cfg.get("private_key_pem")

    if not api_key_id:
        print("ERROR: api_key_id not set. Add it to config.yaml or set KALSHI_API_KEY_ID.", file=sys.stderr)
        sys.exit(1)

    configuration.api_key_id = api_key_id

    if private_key_pem:
        configuration.private_key_pem = private_key_pem
    elif private_key_path:
        key_file = Path(private_key_path).expanduser()
        if not key_file.is_file():
            print(f"ERROR: Private key file not found: {key_file}", file=sys.stderr)
            sys.exit(1)
        configuration.private_key_pem = key_file.read_text()
    else:
        print("ERROR: No private key configured. Set private_key_path in config.yaml or KALSHI_PRIVATE_KEY_PATH.", file=sys.stderr)
        sys.exit(1)

    return kalshi_python.KalshiClient(configuration)


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------


def _cents_to_dollars(cents: int | None) -> str:
    if cents is None:
        return "N/A"
    return f"${cents / 100:.2f}"


def _pp(obj: Any) -> None:
    """Pretty-print an SDK response object (handles datetime, etc.)."""
    try:
        if hasattr(obj, "to_dict"):
            print(json.dumps(obj.to_dict(), indent=2, default=str))
        elif hasattr(obj, "__dict__"):
            print(json.dumps(obj.__dict__, indent=2, default=str))
        else:
            print(json.dumps(obj, indent=2, default=str))
    except (TypeError, ValueError):
        from pprint import pprint
        pprint(obj)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_markets_search(_client, args):
    """Search / list markets via events-based discovery.

    The /markets listing on api.elections.kalshi.com only returns multivariate
    esports combo markets.  Real markets (Politics, Economics, Sports, IPO races,
    etc.) are only discoverable through the /events endpoint.  This command
    paginates events → fetches markets per event → filters by text query.
    """
    cfg = load_config()
    host = cfg.get("host", DEFAULT_HOST)

    # ── If --event flag, fetch a single event's markets directly ──
    if args.event and args.query:
        data = _fetch_json_raw(f"{host}/events/{args.query}")
        if data is None or data.get("error"):
            print(f"  Event not found: {args.query}")
            return
        markets = data.get("markets", [])
        if not markets:
            print(f"  Event {args.query} has no markets.")
            return
        _print_market_table(markets[:args.limit])
        return

    # ── Full events-based search ──
    query = (args.query or "").lower()
    category_filter = (args.category or "").lower() if hasattr(args, "category") else ""

    all_markets: list[dict] = []
    cursor = None
    events_scanned = 0
    max_event_pages = 20  # up to 2000 events

    print(f"  Searching markets via events (query={args.query or '*'})...\n")

    for _ in range(max_event_pages):
        url = f"{host}/events?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        data = _fetch_json_raw(url)
        if data is None:
            break
        events = data.get("events", [])
        if not events:
            break
        cursor = data.get("cursor")

        for ev in events:
            et = ev.get("event_ticker", "")
            ev_title = ev.get("title", "")
            ev_category = ev.get("category", "")
            events_scanned += 1

            # Category filter
            if category_filter and category_filter not in ev_category.lower():
                continue

            # Quick pre-filter: if query doesn't match event title/ticker, skip
            if query and query not in et.lower() and query not in ev_title.lower():
                # Still need to check individual market titles, so fetch markets
                pass

            # Fetch markets for this event
            ev_data = _fetch_json_raw(f"{host}/events/{et}")
            if ev_data is None:
                continue
            markets = ev_data.get("markets", [])

            for m in markets:
                # Apply text filter across ticker + title
                if query:
                    m_ticker = m.get("ticker", "").lower()
                    m_title = m.get("title", "").lower()
                    m_subtitle = m.get("subtitle", "").lower()
                    if (query not in m_ticker and query not in m_title
                            and query not in m_subtitle and query not in et.lower()
                            and query not in ev_title.lower()):
                        continue

                m["_category"] = ev_category
                all_markets.append(m)

            if len(all_markets) >= args.limit:
                break

        if len(all_markets) >= args.limit or not cursor:
            break

    if not all_markets:
        print(f"  No markets found (scanned {events_scanned} events).")
        return

    # Sort by volume descending, take limit
    all_markets.sort(key=lambda m: -(m.get("volume", 0) or 0))
    all_markets = all_markets[:args.limit]

    print(f"  Found {len(all_markets)} markets (scanned {events_scanned} events)\n")
    _print_market_table(all_markets)


def _print_market_table(markets: list[dict]) -> None:
    """Pretty-print a list of market dicts."""
    for m in markets:
        ticker = m.get("ticker", "?")
        title = m.get("title", "")[:50]
        status = m.get("status", "")
        yes_bid = m.get("yes_bid", 0) or 0
        yes_ask = m.get("yes_ask", 0) or 0
        volume = m.get("volume", 0) or 0
        category = m.get("_category", "")
        cat_tag = f" [{category}]" if category else ""
        print(f"  {ticker:<45s}  bid={yes_bid:>2d}  ask={yes_ask:>3d}  vol={volume:>8d}  [{status}]{cat_tag}  {title}")


def _fetch_json_raw(url: str) -> dict | None:
    """Fetch JSON from a URL via raw HTTP (no SDK). Returns None on failure."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _fetch_authed_json(cfg: dict, host: str, path: str) -> dict | None:
    """Authenticated JSON GET via raw HTTP (bypasses SDK deserialization bugs).

    Uses RSA-PSS signing identical to the SDK's KalshiAuth class.
    Required for portfolio endpoints where the SDK's Pydantic models silently
    drop data (e.g. positions API returns 'market_positions' but SDK expects 'positions').
    """
    import base64
    import time
    import urllib.request
    import urllib.error
    from urllib.parse import urlparse

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        print("  ERROR: cryptography package required for auth.  pip install cryptography", file=sys.stderr)
        return None

    api_key_id = cfg.get("api_key_id") or os.environ.get("KALSHI_API_KEY_ID", "")
    private_key_pem = cfg.get("private_key_pem")
    private_key_path = cfg.get("private_key_path") or os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")

    if not private_key_pem and private_key_path:
        private_key_pem = Path(private_key_path).expanduser().read_text()

    if not api_key_id or not private_key_pem:
        print("  ERROR: Missing API key or private key for auth.", file=sys.stderr)
        return None

    url = f"{host}{path}"
    parsed = urlparse(url)
    sign_path = parsed.path  # sign only the path, not query string

    ts = str(int(time.time() * 1000))
    msg = f"{ts}GET{sign_path}".encode("utf-8")

    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    sig = private_key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )

    req = urllib.request.Request(url)
    req.add_header("KALSHI-ACCESS-KEY", api_key_id)
    req.add_header("KALSHI-ACCESS-SIGNATURE", base64.b64encode(sig).decode("utf-8"))
    req.add_header("KALSHI-ACCESS-TIMESTAMP", ts)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        print(f"  ERROR: HTTP {e.code} for {path}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return None


def cmd_events(_client, args):
    """List / search events (the correct way to discover markets)."""
    cfg = load_config()
    host = cfg.get("host", DEFAULT_HOST)
    query = (args.query or "").lower()
    category_filter = (args.category or "").lower() if hasattr(args, "category") else ""

    all_events: list[dict] = []
    cursor = None

    for _ in range(20):
        url = f"{host}/events?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        data = _fetch_json_raw(url)
        if data is None:
            break
        events = data.get("events", [])
        if not events:
            break
        cursor = data.get("cursor")

        for ev in events:
            et = ev.get("event_ticker", "")
            title = ev.get("title", "")
            category = ev.get("category", "")

            # Category filter
            if category_filter and category_filter not in category.lower():
                continue

            # Text filter
            if query and query not in et.lower() and query not in title.lower():
                continue

            all_events.append(ev)

        if not cursor:
            break

    if not all_events:
        print("  No events found.")
        return

    # Group by category for display
    if not query and not category_filter:
        from collections import Counter
        cats = Counter(e.get("category", "?") for e in all_events)
        print(f"  {len(all_events)} events across {len(cats)} categories:\n")
        for cat, count in cats.most_common(20):
            print(f"    {cat:<30s} {count:>4d} events")
        print(f"\n  Use --category <name> to filter, or provide a search query.")
        print(f"  Use 'markets search' to find individual markets within events.\n")
        return

    # Show matching events
    all_events = all_events[:args.limit]
    for ev in all_events:
        et = ev.get("event_ticker", "")
        title = ev.get("title", "")[:55]
        category = ev.get("category", "")
        sub = ev.get("sub_title", "")
        print(f"  {et:<40s}  [{category}]  {title}")
        if sub:
            print(f"  {'':40s}  {sub}")
    print(f"\n  {len(all_events)} event(s). Use 'markets search --event <EVENT_TICKER>' to see markets.")


def cmd_markets_get(client, args):
    """Get a single market by ticker."""
    resp = client.get_market(ticker=args.ticker)
    _pp(resp)


def fetch_orderbook_raw(host: str, ticker: str, depth: int = 10) -> dict:
    """Fetch orderbook via raw HTTP, bypassing the SDK.

    The kalshi-python SDK v2.1.4 has a bug: the Pydantic model aliases
    map var_true->'true' and var_false->'false', but the API returns
    'yes'/'no' keys.  The SDK silently drops the data.  This function
    hits the public endpoint directly and returns the raw JSON dict.

    Returns: {"yes": [[price_cents, qty], ...], "no": [[price_cents, qty], ...]}
    """
    import urllib.request
    import urllib.error

    url = f"{host}/markets/{ticker}/orderbook?depth={depth}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"Orderbook HTTP {e.code}: {body}") from e

    ob = data.get("orderbook", data)
    return {
        "yes": ob.get("yes") or [],
        "no": ob.get("no") or [],
    }


def _extract_ob_levels(ob_or_dict: Any) -> tuple[list, list]:
    """Extract YES and NO levels from an orderbook response.

    Accepts either a raw dict (from fetch_orderbook_raw) or an SDK
    response object (with fallback chain for the broken alias mapping).
    """
    # If it's already a plain dict (from fetch_orderbook_raw)
    if isinstance(ob_or_dict, dict):
        return (ob_or_dict.get("yes") or [], ob_or_dict.get("no") or [])

    ob = ob_or_dict

    # Try SDK model attributes
    yes_raw = getattr(ob, "var_true", None)
    no_raw = getattr(ob, "var_false", None)

    # Fallback: direct yes/no attributes
    if yes_raw is None:
        yes_raw = getattr(ob, "yes", None)
    if no_raw is None:
        no_raw = getattr(ob, "no", None)

    # Fallback: to_dict()
    if yes_raw is None and hasattr(ob, "to_dict"):
        d = ob.to_dict()
        yes_raw = d.get("yes") or d.get("var_true") or d.get("true") or []
        no_raw = d.get("no") or d.get("var_false") or d.get("false") or []

    return (yes_raw or [], no_raw or [])


def _level_to_cents(level: Any) -> tuple[int, int]:
    """Convert an OrderbookLevel to (price_cents, quantity).

    Handles: OrderbookLevel objects (.price/.count), [price, qty] lists,
    and dicts {"price": ..., "count"/"quantity": ...}.
    Price may be in dollars (float like 0.65) or cents (int like 65).
    """
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        p, q = level[0], level[1]
    elif isinstance(level, dict):
        p = level.get("price", 0)
        q = level.get("count", level.get("quantity", 0))
    elif hasattr(level, "price"):
        p = level.price if level.price is not None else 0
        q = getattr(level, "count", None) or getattr(level, "quantity", 0) or 0
    else:
        return (0, 0)

    # Detect dollars vs cents: if price < 1.0 it's likely dollars
    p_num = float(p) if p else 0.0
    if 0 < p_num < 1.0:
        price_cents = round(p_num * 100)
    else:
        price_cents = int(p_num)
    return (price_cents, int(q) if q else 0)


def cmd_orderbook(client, args):
    """Display the orderbook for a market."""
    # Use raw HTTP to bypass SDK deserialization bug (var_true/var_false alias mismatch)
    cfg = load_config()
    host = cfg.get("host", DEFAULT_HOST)
    try:
        ob_data = fetch_orderbook_raw(host, args.ticker, depth=args.depth)
    except Exception as e:
        print(f"  Raw HTTP fetch failed ({e}), falling back to SDK...")
        resp = client.get_market_orderbook(args.ticker, depth=args.depth)
        ob = resp.orderbook if hasattr(resp, "orderbook") else resp
        ob_data = None

    if ob_data is not None:
        yes_raw, no_raw = _extract_ob_levels(ob_data)
    else:
        yes_raw, no_raw = _extract_ob_levels(ob)

    if not yes_raw and not no_raw:
        print(f"\n  Orderbook: {args.ticker}  (depth={args.depth})")
        print(f"  ** EMPTY -- no YES or NO levels returned **")
        print(f"  Possible reasons:")
        print(f"    - Market has no resting orders (genuinely empty book)")
        print(f"    - Market is not open (check: runner.py markets get {args.ticker})")
        print(f"    - Ticker is a multivariate event / combo (no standalone book)")
        print()
        return

    yes_levels = [_level_to_cents(l) for l in yes_raw]
    no_levels = [_level_to_cents(l) for l in no_raw]

    # Sort: bids descending by price
    yes_levels.sort(key=lambda x: x[0], reverse=True)
    no_levels.sort(key=lambda x: x[0], reverse=True)

    print(f"\n  Orderbook: {args.ticker}  (depth={args.depth})")
    print(f"  {'YES bids (cents)':>25s}  |  {'NO bids (cents)':<25s}")
    print(f"  {'─' * 25}  |  {'─' * 25}")

    max_rows = max(len(yes_levels), len(no_levels))
    for i in range(max_rows):
        left = ""
        right = ""
        if i < len(yes_levels):
            p, q = yes_levels[i]
            left = f"{p}¢ x {q}"
        if i < len(no_levels):
            p, q = no_levels[i]
            right = f"{p}¢ x {q}"
        print(f"  {left:>25s}  |  {right:<25s}")
    print()


def cmd_buy(client, args):
    """Place a buy order."""
    from kalshi_python.models.create_order_request import CreateOrderRequest

    req = CreateOrderRequest(
        ticker=args.ticker,
        side=args.side,
        action="buy",
        count=int(args.count),
        type="limit",
        yes_price=int(args.price) if args.side == "yes" else None,
        no_price=int(args.price) if args.side == "no" else None,
    )
    resp = client.create_order(**req.to_dict())
    order = resp.order
    print(f"  BUY order placed: {order.order_id}")
    print(f"    ticker={order.ticker}  side={order.side}  count={order.initial_count}  "
          f"yes_price={order.yes_price}  status={order.status}")


def cmd_sell(client, args):
    """Place a sell order."""
    from kalshi_python.models.create_order_request import CreateOrderRequest

    req = CreateOrderRequest(
        ticker=args.ticker,
        side=args.side,
        action="sell",
        count=int(args.count),
        type="limit",
        yes_price=int(args.price) if args.side == "yes" else None,
        no_price=int(args.price) if args.side == "no" else None,
    )
    resp = client.create_order(**req.to_dict())
    order = resp.order
    print(f"  SELL order placed: {order.order_id}")
    print(f"    ticker={order.ticker}  side={order.side}  count={order.initial_count}  "
          f"yes_price={order.yes_price}  status={order.status}")


def cmd_cancel(client, args):
    """Cancel an order by ID."""
    resp = client.cancel_order(order_id=args.order_id)
    print(f"  Order {args.order_id} canceled.")
    if resp:
        _pp(resp)


def cmd_orders(client, args):
    """List open orders."""
    kwargs: dict[str, Any] = {"limit": args.limit}
    if args.ticker:
        kwargs["ticker"] = args.ticker
    if args.status:
        kwargs["status"] = args.status

    resp = client.get_orders(**kwargs)
    orders = resp.orders or []

    if not orders:
        print("  No orders found.")
        return

    for o in orders:
        print(f"  {o.order_id}  {o.ticker:<25s}  {o.action}/{o.side}  "
              f"count={o.initial_count}  remaining={o.remaining_count}  "
              f"yes_price={o.yes_price}  status={o.status}")


def cmd_positions(_client, args):
    """Show current positions via raw HTTP (SDK drops market_positions data).

    The SDK's GetPositionsResponse Pydantic model expects a 'positions' key,
    but the API returns 'market_positions' and 'event_positions'.  The SDK
    silently drops all position data.  We bypass it with authenticated raw HTTP.
    """
    cfg = load_config()
    host = cfg.get("host", DEFAULT_HOST)

    path = "/portfolio/positions?limit=200"
    if args.ticker:
        path += f"&ticker={args.ticker}"
    if args.event:
        path += f"&event_ticker={args.event}"

    data = _fetch_authed_json(cfg, host, path)
    if data is None:
        print("  ERROR: Failed to fetch positions (auth or network error).", file=sys.stderr)
        return

    market_positions = data.get("market_positions", []) or []
    event_positions = data.get("event_positions", []) or []

    # Filter to non-zero positions unless showing all
    active = [p for p in market_positions if p.get("position", 0) != 0]

    if not active and not event_positions:
        print("  No open positions.")
        return

    if active:
        print(f"\n  {'Ticker':<35s} {'Pos':>5s} {'Exposure':>10s} {'Fees':>8s} {'P&L':>8s} {'Resting':>7s}")
        print("  " + "-" * 80)
        for p in active:
            ticker = p.get("ticker", "?")
            pos = p.get("position", 0)
            exposure = p.get("market_exposure_dollars", "0.00")
            fees = p.get("fees_paid_dollars", "0.00")
            pnl = p.get("realized_pnl_dollars", "0.00")
            resting = p.get("resting_orders_count", 0)
            print(f"  {ticker:<35s} {pos:>5d} ${exposure:>8s} ${fees:>6s} ${pnl:>6s} {resting:>7d}")

    if event_positions:
        print(f"\n  Event-level aggregates:")
        print(f"  {'Event':<35s} {'Exposure':>10s} {'Cost':>10s} {'Fees':>8s} {'P&L':>8s}")
        print("  " + "-" * 75)
        for ep in event_positions:
            et = ep.get("event_ticker", "?")
            exp = ep.get("event_exposure_dollars", "0.00")
            cost = ep.get("total_cost_dollars", "0.00")
            fees = ep.get("fees_paid_dollars", "0.00")
            pnl = ep.get("realized_pnl_dollars", "0.00")
            print(f"  {et:<35s} ${exp:>8s} ${cost:>8s} ${fees:>6s} ${pnl:>6s}")


def cmd_balance(client, _args):
    """Show account balance."""
    resp = client.get_balance()
    balance = getattr(resp, "balance", 0)
    portfolio_value = getattr(resp, "portfolio_value", 0)
    print(f"  Balance:         {_cents_to_dollars(balance)}")
    print(f"  Portfolio value: {_cents_to_dollars(portfolio_value)}")


def cmd_fills(client, args):
    """Show recent fills."""
    kwargs: dict[str, Any] = {"limit": args.limit}
    if args.ticker:
        kwargs["ticker"] = args.ticker

    resp = client.get_fills(**kwargs)
    fills = resp.fills or []

    if not fills:
        print("  No fills found.")
        return

    for f in fills:
        print(f"  {f.trade_id}  {f.ticker:<25s}  {f.action}/{f.side}  "
              f"count={f.count}  price={f.yes_price}  ts={f.created_time}")


def cmd_watch(_client, args):
    """Start or manage position watchers."""
    from watcher import (
        run_watcher, list_watchers, remove_watcher,
        DEFAULT_HOST, DEFAULT_POLL_INTERVAL, DEFAULT_MAX_HISTORY, DEFAULT_STORE_PATH,
    )

    cfg = load_config()
    watcher_cfg = cfg.get("watcher", {})
    host = cfg.get("host", DEFAULT_HOST)
    poll_interval = args.interval or watcher_cfg.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL)
    max_history = watcher_cfg.get("max_history_points", DEFAULT_MAX_HISTORY)
    store_path = Path(watcher_cfg.get("store_path", DEFAULT_STORE_PATH))
    if not store_path.is_absolute():
        store_path = Path(__file__).resolve().parent / store_path

    if args.watch_list:
        watchers = list_watchers(store_path)
        if not watchers:
            print("  No active watchers.")
        else:
            for t, w in watchers.items():
                cur = w.get("current", {})
                bid = cur.get("yes_bid", "?")
                pts = len(w.get("history", []))
                print(f"  {t:<45s}  bid={bid}c  status={w.get('status', '?')}  history={pts}pts")
        return

    if args.remove:
        if remove_watcher(store_path, args.remove):
            print(f"  Removed watcher: {args.remove}")
        else:
            print(f"  Watcher not found: {args.remove}")
        return

    if not args.ticker:
        print("ERROR: ticker is required. Use: runner.py watch <TICKER>", file=sys.stderr)
        sys.exit(1)

    auto_exit = not getattr(args, "no_auto_exit", False)
    run_watcher(
        ticker=args.ticker,
        host=host,
        poll_interval=poll_interval,
        max_history=max_history,
        store_path=store_path,
        entry_cents=args.entry,
        side=args.side,
        contracts=args.contracts,
        stop_cents=args.stop,
        take_profit_cents=args.tp,
        auto_exit=auto_exit,
    )


def cmd_run_strategy(client, args):
    """Dynamically load and run a strategy module."""
    strategy_name = args.strategy_name

    # Look for strategies/ directory next to this script, or in cwd
    strategy_dirs = [
        Path(__file__).resolve().parent / "strategies",
        Path(__file__).resolve().parent.parent / "strategies",
        Path.cwd() / "strategies",
    ]

    module_path = None
    for d in strategy_dirs:
        candidate = d / f"{strategy_name}.py"
        if candidate.is_file():
            module_path = candidate
            break

    if not module_path:
        print(f"ERROR: Strategy '{strategy_name}' not found.", file=sys.stderr)
        print(f"  Looked in: {[str(d) for d in strategy_dirs]}", file=sys.stderr)
        print(f"  Create a file strategies/{strategy_name}.py with a run(client, args) function.", file=sys.stderr)
        sys.exit(1)

    # Dynamic import
    spec = importlib.util.spec_from_file_location(strategy_name, module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "run"):
        print(f"ERROR: Strategy '{strategy_name}' has no run(client, args) function.", file=sys.stderr)
        sys.exit(1)

    print(f"  Running strategy: {strategy_name}")
    mod.run(client, args)


# ---------------------------------------------------------------------------
# Series discovery
# ---------------------------------------------------------------------------


def cmd_series(_client, args):
    """List/search series and their events (crypto, daily, etc.)."""
    cfg = load_config()
    host = cfg.get("host", DEFAULT_HOST)

    series_ticker = getattr(args, "series_ticker", None)
    category = getattr(args, "category", None)
    frequency = getattr(args, "frequency", None)
    show_events = getattr(args, "show_events", False)

    # ── Single series detail ──
    if series_ticker:
        # Fetch series info
        data = _fetch_json_raw(f"{host}/series/{series_ticker}")
        if data and data.get("series"):
            s = data["series"]
            print(f"\n  Series: {s.get('ticker', '')}")
            print(f"  Title:     {s.get('title', '')}")
            print(f"  Category:  {s.get('category', '')}")
            print(f"  Frequency: {s.get('frequency', '')}")
            print(f"  Fee type:  {s.get('fee_type', '')}")
            tags = s.get("tags") or []
            if tags:
                print(f"  Tags:      {', '.join(tags)}")
            sources = s.get("settlement_sources") or []
            for src in sources:
                print(f"  Source:    {src.get('name', '')} ({src.get('url', '')})")
        else:
            print(f"  Series '{series_ticker}' not found.")
            return

        # Fetch events for this series — show active (open) events first,
        # then remaining events up to the limit.
        limit = getattr(args, "limit", 20)

        # First: get ONLY open/active events (the ones you can actually trade)
        open_data = _fetch_json_raw(f"{host}/events?series_ticker={series_ticker}&status=open&limit={limit}")
        open_events = (open_data.get("events", []) if open_data else [])
        open_tickers = {ev.get("event_ticker") for ev in open_events}

        # Second: get all events (includes initialized, settled, etc.)
        all_data = _fetch_json_raw(f"{host}/events?series_ticker={series_ticker}&limit={limit}")
        all_events = (all_data.get("events", []) if all_data else [])

        # Merge: open events first (sorted by nearest expiry), then the rest
        other_events = [ev for ev in all_events if ev.get("event_ticker") not in open_tickers]
        ordered_events = open_events + other_events

        if ordered_events:
            n_open = len(open_events)
            print(f"\n  Events ({len(ordered_events)} total, {n_open} open/active):")
            if n_open > 0:
                print(f"  --- ACTIVE (tradeable) ---")
            for i, ev in enumerate(ordered_events):
                et = ev.get("event_ticker", "")
                title = ev.get("title", "")[:55]
                status = ev.get("status", "")
                if i == n_open and n_open > 0:
                    print(f"  --- OTHER (initialized / settled) ---")
                print(f"    {et:<45s} [{status or '?'}]  {title}")

                # If --events flag, also show markets within each event
                if show_events:
                    ev_detail = _fetch_json_raw(f"{host}/events/{et}")
                    if ev_detail:
                        markets = ev_detail.get("markets", [])
                        for m in markets[:10]:
                            mt = m.get("ticker", "")
                            yb = m.get("yes_bid", 0) or 0
                            ya = m.get("yes_ask", 0) or 0
                            vol = m.get("volume", 0) or 0
                            st = m.get("status", "")
                            mtitle = m.get("title", "")[:40]
                            print(f"      {mt:<42s} bid={yb:>2d} ask={ya:>3d} vol={vol:>6d} [{st}] {mtitle}")
                        if len(markets) > 10:
                            print(f"      ... and {len(markets) - 10} more markets")
        else:
            print(f"\n  No events found for series '{series_ticker}'.")
        return

    # ── List series (optionally filtered by category / frequency) ──
    url = f"{host}/series?limit=200"
    if category:
        url += f"&category={category}"
    data = _fetch_json_raw(url)
    if not data or not data.get("series"):
        print("  No series found.")
        return

    series_list = data.get("series", [])
    if not isinstance(series_list, list):
        print("  Unexpected series response format.")
        return

    # Filter by frequency if specified
    if frequency:
        series_list = [s for s in series_list
                       if isinstance(s, dict) and frequency.lower() in (s.get("frequency", "")).lower()]

    if not series_list:
        print("  No series found matching filters.")
        return

    # Group by frequency for display
    freq_groups: dict[str, list] = {}
    for s in series_list:
        if not isinstance(s, dict):
            continue
        f = s.get("frequency", "unknown")
        freq_groups.setdefault(f, []).append(s)

    total = sum(len(v) for v in freq_groups.values())
    cat_label = f" [{category}]" if category else ""
    freq_label = f" frequency={frequency}" if frequency else ""
    print(f"\n  {total} series{cat_label}{freq_label}:\n")

    for freq in sorted(freq_groups.keys()):
        items = freq_groups[freq]
        print(f"  {freq} ({len(items)}):")
        for s in items:
            ticker = s.get("ticker", "")
            title = s.get("title", "")[:45]
            print(f"    {ticker:<25s} {title}")
        print()

    print(f"  Use 'series <TICKER>' for detail, 'series <TICKER> --events' for markets.")


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runner",
        description="Kalshi Bot – trade prediction markets from the CLI.",
    )
    parser.add_argument("--config", help="Path to config.yaml (auto-detected by default)")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── events (primary market discovery) ────────────────────────────────
    events_p = sub.add_parser("events", help="List/search events (primary market discovery)")
    events_p.add_argument("query", nargs="?", default=None, help="Search query (matches event ticker or title)")
    events_p.add_argument("--category", default=None, help="Filter by category (e.g., Politics, Economics, Sports)")
    events_p.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")

    # ── markets ────────────────────────────────────────────────────────────
    markets_p = sub.add_parser("markets", help="Market data commands")
    markets_sub = markets_p.add_subparsers(dest="markets_cmd", required=True)

    search_p = markets_sub.add_parser("search", help="Search markets (via events-based discovery)")
    search_p.add_argument("query", nargs="?", default=None, help="Free-text search query")
    search_p.add_argument("--category", default=None, help="Filter by category (e.g., Politics, Economics, Financials)")
    search_p.add_argument("--status", default=None, help="Market status filter: unopened, open, paused, closed, settled")
    search_p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    search_p.add_argument("--series", action="store_true", help="Treat query as series_ticker (SDK fallback)")
    search_p.add_argument("--event", action="store_true", help="Treat query as event_ticker (fetches that event's markets)")
    search_p.add_argument("--tickers", action="store_true", help="Treat query as comma-separated tickers (SDK fallback)")

    get_p = markets_sub.add_parser("get", help="Get a single market")
    get_p.add_argument("ticker", help="Market ticker")

    # ── orderbook ──────────────────────────────────────────────────────────
    ob_p = sub.add_parser("orderbook", help="Show market orderbook")
    ob_p.add_argument("ticker", help="Market ticker")
    ob_p.add_argument("--depth", type=int, default=10, help="Orderbook depth (default: 10)")

    # ── buy / sell ─────────────────────────────────────────────────────────
    buy_p = sub.add_parser("buy", help="Place a buy order")
    buy_p.add_argument("ticker", help="Market ticker")
    buy_p.add_argument("count", type=int, help="Number of contracts")
    buy_p.add_argument("price", type=int, help="Price in cents (1-99)")
    buy_p.add_argument("--side", default="yes", choices=["yes", "no"], help="Side (default: yes)")

    sell_p = sub.add_parser("sell", help="Place a sell order")
    sell_p.add_argument("ticker", help="Market ticker")
    sell_p.add_argument("count", type=int, help="Number of contracts")
    sell_p.add_argument("price", type=int, help="Price in cents (1-99)")
    sell_p.add_argument("--side", default="yes", choices=["yes", "no"], help="Side (default: yes)")

    # ── cancel ─────────────────────────────────────────────────────────────
    cancel_p = sub.add_parser("cancel", help="Cancel an order")
    cancel_p.add_argument("order_id", help="Order ID to cancel")

    # ── orders ─────────────────────────────────────────────────────────────
    orders_p = sub.add_parser("orders", help="List orders")
    orders_p.add_argument("--ticker", help="Filter by ticker")
    orders_p.add_argument("--status", default="resting", help="Order status (default: resting)")
    orders_p.add_argument("--limit", type=int, default=50, help="Max results")

    # ── positions ──────────────────────────────────────────────────────────
    pos_p = sub.add_parser("positions", help="Show positions")
    pos_p.add_argument("--ticker", help="Filter by ticker")
    pos_p.add_argument("--event", help="Filter by event ticker")
    pos_p.add_argument("--limit", type=int, default=100, help="Max results")

    # ── balance ────────────────────────────────────────────────────────────
    sub.add_parser("balance", help="Show account balance")

    # ── fills ──────────────────────────────────────────────────────────────
    fills_p = sub.add_parser("fills", help="Show recent fills")
    fills_p.add_argument("--ticker", help="Filter by ticker")
    fills_p.add_argument("--limit", type=int, default=20, help="Max results")

    # ── series (crypto / daily series discovery) ───────────────────────────
    series_p = sub.add_parser("series", help="List/search market series (crypto, daily, etc.)")
    series_p.add_argument("series_ticker", nargs="?", default=None,
                          help="Series ticker (e.g., KXBTC15M, KXBTC, KXETH)")
    series_p.add_argument("--category", default=None,
                          help="Filter by category (e.g., Crypto, Politics)")
    series_p.add_argument("--frequency", default=None,
                          help="Filter by frequency (fifteen_min, hourly, daily, weekly, monthly)")
    series_p.add_argument("--events", action="store_true", dest="show_events",
                          help="Show markets within each event")
    series_p.add_argument("--limit", type=int, default=20, help="Max events to show")

    # ── run-strategy ───────────────────────────────────────────────────────
    strat_p = sub.add_parser("run-strategy", help="Run a named strategy")
    strat_p.add_argument("strategy_name", help="Strategy module name (without .py)")
    strat_p.add_argument("--ticker", help="Ticker to pass to strategy")
    strat_p.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args forwarded to strategy")

    # ── watch ─────────────────────────────────────────────────────────────
    watch_p = sub.add_parser("watch", help="Start a position price watcher")
    watch_p.add_argument("ticker", nargs="?", default=None, help="Market ticker to watch")
    watch_p.add_argument("--entry", type=int, default=0, help="Entry price in cents")
    watch_p.add_argument("--side", default="LONG", choices=["LONG", "SHORT"], help="Position side")
    watch_p.add_argument("--contracts", type=int, default=0, help="Number of contracts")
    watch_p.add_argument("--stop", type=int, default=0, help="Stop price in cents")
    watch_p.add_argument("--tp", type=int, default=0, help="Take profit price in cents")
    watch_p.add_argument("--interval", type=float, default=None, help="Poll interval in seconds")
    watch_p.add_argument("--list", action="store_true", dest="watch_list", help="List active watchers")
    watch_p.add_argument("--remove", metavar="TICKER", default=None, help="Remove a watcher")
    watch_p.add_argument("--no-auto-exit", action="store_true", dest="no_auto_exit",
                         help="Disable auto-sell on TP/stop (alert only)")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMAND_MAP = {
    "events": cmd_events,
    "markets": {
        "search": cmd_markets_search,
        "get": cmd_markets_get,
    },
    "orderbook": cmd_orderbook,
    "buy": cmd_buy,
    "sell": cmd_sell,
    "cancel": cmd_cancel,
    "orders": cmd_orders,
    "positions": cmd_positions,
    "balance": cmd_balance,
    "fills": cmd_fills,
    "series": cmd_series,
    "run-strategy": cmd_run_strategy,
    "watch": cmd_watch,
}

# Commands that don't need the SDK client (use raw HTTP)
NO_CLIENT_COMMANDS = {"watch", "events", "positions", "series"}


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Load config
    cfg = load_config()
    if args.config:
        with open(args.config) as f:
            file_cfg = yaml.safe_load(f) or {}
        file_cfg.update({k: v for k, v in cfg.items() if v is not None})
        cfg = file_cfg

    # Build client — some commands use raw HTTP and don't need the SDK
    needs_sdk = args.command not in NO_CLIENT_COMMANDS
    # markets search also uses raw HTTP (events-based discovery)
    if args.command == "markets" and getattr(args, "markets_cmd", None) == "search":
        needs_sdk = False
    # run-strategy: try to build client but pass None if it fails
    # (some strategies like crypto_sentinel use raw HTTP only)
    if args.command == "run-strategy":
        needs_sdk = False
        try:
            client = build_client(cfg)
        except (SystemExit, Exception):
            client = None
    elif needs_sdk:
        client = build_client(cfg)
    else:
        client = None

    # Dispatch
    handler = COMMAND_MAP.get(args.command)
    if isinstance(handler, dict):
        sub_cmd = getattr(args, "markets_cmd", None)
        handler = handler.get(sub_cmd)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        handler(client, args)
    except Exception as e:
        # Extract useful info from Kalshi API errors
        body = getattr(e, "body", None)
        status = getattr(e, "status", None)
        if status and body:
            print(f"ERROR (HTTP {status}): {body}", file=sys.stderr)
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        if os.getenv("KALSHI_DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
