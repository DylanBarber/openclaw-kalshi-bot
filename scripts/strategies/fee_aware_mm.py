"""
Fee-Aware Market-Making Strategy

Implements the full trading doctrine: fee calculation, all four gates,
position sizing, order-ticket output, and position management with
take-profit / stop / time-stop.

Usage:
    python runner.py run-strategy fee_aware_mm --ticker KXBTC-26FEB14-T50050

Extra args (passed after --):
    --side LONG|SHORT           Position side (default: LONG)
    --contract YES|NO           Contract type (default: YES)
    --entry CENTS               Override entry price (default: best bid/ask)
    --exit CENTS                Override exit target
    --count N                   Override contract count (default: auto-size)
    --dry-run                   Evaluate only, do not place orders
    --loop                      Continuous monitoring mode
    --interval SECONDS          Loop poll interval (default: 10)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure scripts/ is on sys.path so we can import siblings
_scripts_dir = str(Path(__file__).resolve().parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from kalshi_math import PositionSide, FillType  # noqa: E402
from trade_engine import (  # noqa: E402
    RiskConfig,
    TradeParams,
    TradeEvaluation,
    PortfolioState,
    evaluate_trade,
    check_risk_limits,
    format_order_ticket,
    place_limit_order,
    wait_for_fill,
)

# ── Orderbook parsing helpers ─────────────────────────────────────────────


def fetch_orderbook_raw(host: str, ticker: str, depth: int = 10) -> dict:
    """Fetch orderbook via raw HTTP, bypassing the SDK.

    The kalshi-python SDK v2.1.4 has a bug: Pydantic aliases map
    var_true->'true' / var_false->'false', but the API returns 'yes'/'no'.
    The SDK silently drops all orderbook data.
    """
    import json as _json
    import urllib.request
    import urllib.error

    url = f"{host}/markets/{ticker}/orderbook?depth={depth}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
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

    Accepts a raw dict (from fetch_orderbook_raw) or SDK response object.
    """
    if isinstance(ob_or_dict, dict):
        return (ob_or_dict.get("yes") or [], ob_or_dict.get("no") or [])

    ob = ob_or_dict
    yes_raw = getattr(ob, "var_true", None)
    no_raw = getattr(ob, "var_false", None)

    if yes_raw is None:
        yes_raw = getattr(ob, "yes", None)
    if no_raw is None:
        no_raw = getattr(ob, "no", None)

    if yes_raw is None and hasattr(ob, "to_dict"):
        d = ob.to_dict()
        yes_raw = d.get("yes") or d.get("var_true") or d.get("true") or []
        no_raw = d.get("no") or d.get("var_false") or d.get("false") or []

    return (yes_raw or [], no_raw or [])


def _level_to_cents(level: Any) -> tuple[int, int]:
    """Convert an OrderbookLevel to (price_cents, quantity).

    Handles: OrderbookLevel objects (.price/.count), [price, qty] lists,
    and dicts. Price may be dollars (float 0.65) or cents (int 65).
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

    p_num = float(p) if p else 0.0
    if 0 < p_num < 1.0:
        price_cents = round(p_num * 100)
    else:
        price_cents = int(p_num)
    return (price_cents, int(q) if q else 0)


def _parse_book(client: Any, ticker: str, depth: int = 20) -> dict[str, Any]:
    """
    Fetch the orderbook and return a normalised dict:
    {
        "yes_bids": [(price_cents, qty), ...],   # descending by price
        "yes_asks": [(price_cents, qty), ...],   # ascending by price
        "best_yes_bid": int|None,
        "best_yes_ask": int|None,
        "spread_cents": int,
        "depth_at_bid": int,
        "depth_at_ask": int,
    }
    """
    # Use raw HTTP to bypass SDK deserialization bug (alias mismatch)
    host = os.environ.get("KALSHI_HOST", "https://api.elections.kalshi.com/trade-api/v2")
    try:
        ob_data = fetch_orderbook_raw(host, ticker, depth=depth)
        raw_yes, raw_no = _extract_ob_levels(ob_data)
    except Exception:
        # Fallback to SDK if raw HTTP fails (e.g. network issue)
        resp = client.get_market_orderbook(ticker, depth=depth)
        ob = resp.orderbook if hasattr(resp, "orderbook") else resp
        raw_yes, raw_no = _extract_ob_levels(ob)

    if not raw_yes and not raw_no:
        print(f"  WARNING: Orderbook for {ticker} is completely empty.")
        print(f"  This may mean the market has no resting orders, is not open,")
        print(f"  or is a multivariate/combo market without a standalone book.")

    yes_levels = [_level_to_cents(l) for l in raw_yes]
    no_levels = [_level_to_cents(l) for l in raw_no]

    # YES bids = yes_levels (people wanting to buy YES)
    # YES asks = derived from NO bids (100 - no_bid_price)
    yes_bids = sorted(yes_levels, key=lambda x: x[0], reverse=True)
    yes_asks = sorted(
        [(100 - p, q) for p, q in no_levels],
        key=lambda x: x[0],
    )

    best_bid = yes_bids[0][0] if yes_bids else None
    best_ask = yes_asks[0][0] if yes_asks else None

    spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else 99
    depth_bid = yes_bids[0][1] if yes_bids else 0
    depth_ask = yes_asks[0][1] if yes_asks else 0

    return {
        "yes_bids": yes_bids,
        "yes_asks": yes_asks,
        "best_yes_bid": best_bid,
        "best_yes_ask": best_ask,
        "spread_cents": max(0, spread),
        "depth_at_bid": depth_bid,
        "depth_at_ask": depth_ask,
    }


def _get_market_info(client: Any, ticker: str) -> dict[str, Any]:
    """Fetch market metadata."""
    resp = client.get_market(ticker)
    m = resp.market if hasattr(resp, "market") else resp
    return {
        "title": getattr(m, "title", ticker),
        "status": getattr(m, "status", "unknown"),
        "volume": getattr(m, "volume", 0),
        "yes_bid": getattr(m, "yes_bid", None),
        "yes_ask": getattr(m, "yes_ask", None),
    }


def _get_portfolio_state(client: Any) -> PortfolioState:
    """Build a portfolio snapshot for risk checks."""
    try:
        pos_resp = client.get_positions(limit=100)
        positions = getattr(pos_resp, "market_positions", None) or getattr(pos_resp, "positions", []) or []
        open_count = len([p for p in positions if getattr(p, "position", 0) != 0])
    except Exception:
        open_count = 0

    # Daily P&L — approximate from today's settlements (simplified)
    daily_loss = 0.0
    try:
        import datetime
        today_ts = int(datetime.datetime.combine(
            datetime.date.today(), datetime.time.min,
        ).timestamp())
        fills_resp = client.get_fills(min_ts=today_ts, limit=200)
        fills = getattr(fills_resp, "fills", []) or []
        # Rough approximation — sum up realized cost of sells
        for f in fills:
            if getattr(f, "action", "") == "sell":
                pnl = getattr(f, "realized_pnl", 0) or 0
                if pnl < 0:
                    daily_loss += abs(pnl) / 100.0
    except Exception:
        pass

    return PortfolioState(
        open_position_count=open_count,
        daily_realized_loss_usd=daily_loss,
    )


# ── Strategy arg parsing ─────────────────────────────────────────────────


def _parse_extra_args(extra: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="fee_aware_mm extras")
    p.add_argument("--side", default="LONG", choices=["LONG", "SHORT"])
    p.add_argument("--contract", default="YES", choices=["YES", "NO"])
    p.add_argument("--entry", type=int, default=0, help="Entry price cents")
    p.add_argument("--exit", type=int, default=0, help="Exit target cents")
    p.add_argument("--count", type=int, default=0, help="Contract count override")
    p.add_argument("--dry-run", action="store_true", help="Evaluate only")
    p.add_argument("--loop", action="store_true", help="Continuous mode")
    p.add_argument("--interval", type=float, default=10.0, help="Loop interval secs")
    # Strip leading '--' separator if present
    cleaned = [a for a in extra if a != "--"]
    return p.parse_args(cleaned)


# ── Main entry point ──────────────────────────────────────────────────────


def run(client: Any, args: Any) -> None:
    """Strategy entry point called by runner.py."""
    ticker = args.ticker
    if not ticker:
        print("ERROR: --ticker is required for fee_aware_mm strategy.", file=sys.stderr)
        return

    extra = _parse_extra_args(getattr(args, "extra", []))

    # Load risk config from the same config.yaml the runner uses
    try:
        import yaml
        cfg_candidates = [
            Path.cwd() / "config.yaml",
            Path(__file__).resolve().parent.parent / "config.yaml",
            Path(__file__).resolve().parent.parent.parent / "config.yaml",
        ]
        risk_cfg = RiskConfig()
        for cp in cfg_candidates:
            if cp.is_file():
                with open(cp) as f:
                    raw = yaml.safe_load(f) or {}
                risk_cfg = RiskConfig.from_dict(raw)
                break
    except Exception:
        risk_cfg = RiskConfig()

    if extra.loop:
        _run_loop(client, ticker, extra, risk_cfg)
    else:
        _run_once(client, ticker, extra, risk_cfg)


def _run_once(client: Any, ticker: str, extra: argparse.Namespace, cfg: RiskConfig) -> None:
    """Single evaluation cycle."""
    market = _get_market_info(client, ticker)
    book = _parse_book(client, ticker)

    print(f"\n  Market: {ticker} — {market['title']}")
    print(f"  Status: {market['status']}  Volume: {market['volume']}")
    print(f"  Book:   bid={book['best_yes_bid']}  ask={book['best_yes_ask']}  "
          f"spread={book['spread_cents']}c")

    if market["status"] not in ("active", "open"):
        print(f"  Market is '{market['status']}' — skipping.")
        return

    side: PositionSide = extra.side  # type: ignore[assignment]

    # Determine entry/exit
    if extra.entry > 0:
        entry_cents = extra.entry
    elif side == "LONG":
        entry_cents = book["best_yes_bid"]
    else:
        entry_cents = book["best_yes_ask"]

    if entry_cents is None:
        print("  No valid entry price available.")
        return

    if extra.exit > 0:
        exit_cents = extra.exit
    elif side == "LONG":
        exit_cents = min(99, entry_cents + cfg.default_take_profit_offset_cents)
    else:
        exit_cents = max(1, entry_cents - cfg.default_take_profit_offset_cents)

    # Determine fill type — posting limit = MAKER intent
    entry_fill: FillType = "MAKER"
    exit_fill: FillType = "MAKER"

    # Choose depth for Gate D based on side
    depth_at_price = book["depth_at_bid"] if side == "LONG" else book["depth_at_ask"]

    params = TradeParams(
        market_ticker=ticker,
        market_title=market["title"],
        outcome_contract=extra.contract,
        position_side=side,
        entry_price_cents=entry_cents,
        exit_target_cents=exit_cents,
        entry_fill_type=entry_fill,
        exit_fill_type=exit_fill,
        market_has_maker_fees=False,  # most markets; override in config if needed
        contracts=extra.count,
        spread_cents=book["spread_cents"],
        depth_at_price=depth_at_price,
    )

    ev = evaluate_trade(params, cfg)
    print(format_order_ticket(ev))

    if not ev.all_gates_pass:
        print("  Trade BLOCKED by gates. No order placed.")
        return

    # Portfolio risk check
    portfolio = _get_portfolio_state(client)
    allowed, risk_reasons = check_risk_limits(ev, portfolio, cfg)
    if not allowed:
        print("  Trade BLOCKED by risk limits:")
        for r in risk_reasons:
            print(f"    !! {r}")
        return

    if extra.dry_run:
        print("  [DRY RUN] All gates passed — would place order.")
        return

    # ── Execute (Section 19-21) ───────────────────────────────────────
    print("  Placing entry order...")
    sdk_side = "yes" if extra.contract == "YES" else "no"
    action = "buy" if side == "LONG" else "sell"

    try:
        resp = place_limit_order(
            client, ticker, sdk_side, action,
            ev.contracts, entry_cents, post_only=True,
        )
        order = resp.order if hasattr(resp, "order") else resp
        order_id = getattr(order, "order_id", "???")
        print(f"  Entry order placed: {order_id}")
    except Exception as e:
        print(f"  ERROR placing entry: {e}", file=sys.stderr)
        return

    # Wait for fill
    print("  Waiting for fill...")
    filled = wait_for_fill(client, order_id, timeout_s=60)
    if filled is None or getattr(filled, "status", "") == "canceled":
        print("  Entry did not fill — aborting.")
        return

    remaining = getattr(filled, "remaining_count", 0)
    fill_count = getattr(filled, "fill_count", ev.contracts)
    print(f"  Filled {fill_count} contracts (remaining={remaining}).")

    # ── Place exit orders (Section 18 + 21) ───────────────────────────
    exit_action = "sell" if side == "LONG" else "buy"

    # Take-profit
    try:
        tp_resp = place_limit_order(
            client, ticker, sdk_side, exit_action,
            fill_count, ev.take_profit_cents, post_only=True,
        )
        tp_order = tp_resp.order if hasattr(tp_resp, "order") else tp_resp
        print(f"  Take-profit order: {getattr(tp_order, 'order_id', '???')} @ {ev.take_profit_cents}¢")
    except Exception as e:
        print(f"  WARNING: Failed to place TP order: {e}", file=sys.stderr)

    print(f"  Stop level: {ev.stop_cents}c  |  Time-stop: {ev.max_hold_minutes} min")

    # Auto-start watcher for this position
    try:
        import subprocess
        watcher_script = str(Path(__file__).resolve().parent.parent / "watcher.py")
        watcher_cmd = [
            sys.executable, watcher_script, ticker,
            "--entry", str(entry_cents),
            "--side", str(side),
            "--contracts", str(fill_count),
            "--stop", str(ev.stop_cents),
            "--tp", str(ev.take_profit_cents),
        ]
        proc = subprocess.Popen(
            watcher_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"  Watcher started (PID {proc.pid}) for {ticker}")
    except Exception as e:
        print(f"  WARNING: Failed to auto-start watcher: {e}", file=sys.stderr)
        print(f"  Start manually: python watcher.py {ticker} --entry {entry_cents} --side {side} --contracts {fill_count} --stop {ev.stop_cents} --tp {ev.take_profit_cents}")


def _run_loop(client: Any, ticker: str, extra: argparse.Namespace, cfg: RiskConfig) -> None:
    """Continuous monitoring — evaluate, print, repeat."""
    print(f"\n  [LOOP] Monitoring {ticker} every {extra.interval}s  (Ctrl-C to stop)\n")
    try:
        while True:
            try:
                _run_once(client, ticker, extra, cfg)
            except Exception as e:
                print(f"  Loop error: {e}", file=sys.stderr)
                if os.getenv("KALSHI_DEBUG"):
                    import traceback
                    traceback.print_exc()
            time.sleep(extra.interval)
    except KeyboardInterrupt:
        print("\n  Stopped.")
