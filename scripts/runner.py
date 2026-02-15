#!/usr/bin/env python3
"""
Kalshi Bot CLI – trade prediction markets from the command line.

Usage:
    python runner.py markets search <query> [--status active] [--limit 20]
    python runner.py markets get <ticker>
    python runner.py orderbook <ticker> [--depth 10]
    python runner.py buy <ticker> <count> <price> [--side yes]
    python runner.py sell <ticker> <count> <price> [--side yes]
    python runner.py cancel <order_id>
    python runner.py orders [--status resting] [--ticker TICKER]
    python runner.py positions [--ticker TICKER] [--event EVENT]
    python runner.py balance
    python runner.py fills [--ticker TICKER] [--limit 20]
    python runner.py run-strategy <strategy_name> [--ticker TICKER] [-- ...]

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


def cmd_markets_search(client, args):
    """Search / list markets."""
    kwargs: dict[str, Any] = {}
    if args.query:
        # The SDK's get_markets doesn't have a text search param directly;
        # use series_ticker or event_ticker if provided, else filter client-side.
        kwargs["series_ticker"] = args.query if args.series else None
        kwargs["event_ticker"] = args.query if args.event else None
        kwargs["tickers"] = args.query if args.tickers else None
    if args.status:
        kwargs["status"] = args.status
    kwargs["limit"] = args.limit

    # Clean None values
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    resp = client.get_markets(**kwargs)
    markets = resp.markets or []

    if not markets:
        print("No markets found.")
        return

    # If we have a free-text query and didn't use a specific filter, filter locally
    if args.query and not (args.series or args.event or args.tickers):
        q = args.query.lower()
        markets = [m for m in markets if q in (getattr(m, "title", "") or "").lower()
                    or q in (getattr(m, "ticker", "") or "").lower()
                    or q in (getattr(m, "subtitle", "") or "").lower()]

    for m in markets:
        ticker = getattr(m, "ticker", "?")
        title = getattr(m, "title", "")
        status = getattr(m, "status", "")
        yes_bid = getattr(m, "yes_bid", None)
        yes_ask = getattr(m, "yes_ask", None)
        volume = getattr(m, "volume", None)
        print(f"  {ticker:<30s}  bid={yes_bid}  ask={yes_ask}  vol={volume}  [{status}]  {title}")


def cmd_markets_get(client, args):
    """Get a single market by ticker."""
    resp = client.get_market(args.ticker)
    _pp(resp)


def _extract_ob_levels(ob: Any) -> tuple[list, list]:
    """Extract YES and NO levels from an orderbook response object.

    The SDK model uses 'var_true'/'var_false' (because yes/no map to
    true/false which are reserved in Python). Older versions may use
    'yes'/'no'. We also try to_dict() as a fallback.

    Each level is an OrderbookLevel with .price (float, dollars) and .count (int).
    """
    # Try SDK model attributes first (current SDK)
    yes_raw = getattr(ob, "var_true", None)
    no_raw = getattr(ob, "var_false", None)

    # Fallback: older SDK or dict-style
    if yes_raw is None:
        yes_raw = getattr(ob, "yes", None)
    if no_raw is None:
        no_raw = getattr(ob, "no", None)

    # Fallback: try to_dict()
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
    resp = client.get_market_orderbook(args.ticker, depth=args.depth)
    ob = resp.orderbook if hasattr(resp, "orderbook") else resp

    yes_raw, no_raw = _extract_ob_levels(ob)

    if not yes_raw and not no_raw:
        # Diagnostics: help the agent understand WHY the book is empty
        print(f"\n  Orderbook: {args.ticker}  (depth={args.depth})")
        print(f"  ** EMPTY — no YES or NO levels returned **")
        print(f"  Possible reasons:")
        print(f"    - Market has no resting orders (genuinely empty book)")
        print(f"    - Market is not open (check: runner.py markets get {args.ticker})")
        print(f"    - Ticker is a multivariate event / combo (no standalone book)")
        # Dump the raw response for debugging
        print(f"\n  Raw response type: {type(ob).__name__}")
        if hasattr(ob, "to_dict"):
            print(f"  Raw to_dict(): {ob.to_dict()}")
        elif hasattr(ob, "__dict__"):
            print(f"  Raw __dict__: {ob.__dict__}")
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
    resp = client.create_order(req)
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
    resp = client.create_order(req)
    order = resp.order
    print(f"  SELL order placed: {order.order_id}")
    print(f"    ticker={order.ticker}  side={order.side}  count={order.initial_count}  "
          f"yes_price={order.yes_price}  status={order.status}")


def cmd_cancel(client, args):
    """Cancel an order by ID."""
    resp = client.cancel_order(args.order_id)
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


def cmd_positions(client, args):
    """Show current positions."""
    kwargs: dict[str, Any] = {"limit": args.limit}
    if args.ticker:
        kwargs["ticker"] = args.ticker
    if args.event:
        kwargs["event_ticker"] = args.event

    resp = client.get_positions(**kwargs)
    positions = getattr(resp, "market_positions", None) or getattr(resp, "positions", []) or []

    if not positions:
        print("  No open positions.")
        return

    for p in positions:
        ticker = getattr(p, "ticker", getattr(p, "market_ticker", "?"))
        position = getattr(p, "position", 0)
        market_exposure = getattr(p, "market_exposure", None)
        realized_pnl = getattr(p, "realized_pnl", None)
        print(f"  {ticker:<30s}  position={position}  exposure={market_exposure}  realized_pnl={realized_pnl}")


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
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runner",
        description="Kalshi Bot – trade prediction markets from the CLI.",
    )
    parser.add_argument("--config", help="Path to config.yaml (auto-detected by default)")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── markets ────────────────────────────────────────────────────────────
    markets_p = sub.add_parser("markets", help="Market data commands")
    markets_sub = markets_p.add_subparsers(dest="markets_cmd", required=True)

    search_p = markets_sub.add_parser("search", help="Search / list markets")
    search_p.add_argument("query", nargs="?", default=None, help="Free-text search query")
    search_p.add_argument("--status", default=None, help="Market status filter: unopened, open, paused, closed, settled")
    search_p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    search_p.add_argument("--series", action="store_true", help="Treat query as series_ticker")
    search_p.add_argument("--event", action="store_true", help="Treat query as event_ticker")
    search_p.add_argument("--tickers", action="store_true", help="Treat query as comma-separated tickers")

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

    # ── run-strategy ───────────────────────────────────────────────────────
    strat_p = sub.add_parser("run-strategy", help="Run a named strategy")
    strat_p.add_argument("strategy_name", help="Strategy module name (without .py)")
    strat_p.add_argument("--ticker", help="Ticker to pass to strategy")
    strat_p.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args forwarded to strategy")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMAND_MAP = {
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
    "run-strategy": cmd_run_strategy,
}


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

    # Build client
    client = build_client(cfg)

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
