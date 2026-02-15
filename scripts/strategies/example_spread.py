"""
Example strategy: spread watcher with doctrine-aware evaluation.

Monitors a market's orderbook and prints a full order-ticket evaluation
whenever the spread narrows below a threshold.

Usage:
    python runner.py run-strategy example_spread --ticker SOME-TICKER
    python runner.py run-strategy example_spread --ticker SOME-TICKER -- --threshold 4
"""

from __future__ import annotations

import argparse
import json as _json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

_scripts_dir = str(Path(__file__).resolve().parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from kalshi_math import FillType, PositionSide  # noqa: E402
from trade_engine import (  # noqa: E402
    RiskConfig,
    TradeParams,
    evaluate_trade,
    format_order_ticket,
)


def run(client: Any, args: Any) -> None:
    """Watch the spread on a market and evaluate when it tightens."""
    ticker = args.ticker
    if not ticker:
        print("ERROR: --ticker is required for example_spread strategy.")
        return

    extra = getattr(args, "extra", [])
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=int, default=5, help="Spread threshold (cents)")
    p.add_argument("--interval", type=float, default=5.0, help="Poll interval (secs)")
    opts = p.parse_args([a for a in extra if a != "--"])

    cfg = RiskConfig()

    print(f"  Watching spread on {ticker}  (threshold={opts.threshold}c, Ctrl-C to stop)\n")

    host = os.environ.get("KALSHI_HOST", "https://api.elections.kalshi.com/trade-api/v2")

    def _fetch_book_raw(t: str) -> dict:
        """Raw HTTP orderbook fetch (bypasses SDK alias bug)."""
        url = f"{host}/markets/{t}/orderbook?depth=10"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
        ob = data.get("orderbook", data)
        return {"yes": ob.get("yes") or [], "no": ob.get("no") or []}

    try:
        while True:
            try:
                book = _fetch_book_raw(ticker)
                yes_raw = book["yes"]
                no_raw = book["no"]
            except Exception:
                # Fallback to SDK if raw HTTP fails
                resp = client.get_market_orderbook(ticker, depth=10)
                ob = resp.orderbook if hasattr(resp, "orderbook") else resp
                yes_raw = getattr(ob, "var_true", None) or getattr(ob, "yes", None) or []
                no_raw = getattr(ob, "var_false", None) or getattr(ob, "no", None) or []

            # Parse best level — data is [[price_cents, qty], ...]
            def _best(levels):
                for item in sorted(levels, key=lambda x: -(x[0] if isinstance(x, (list, tuple)) else 0), reverse=False):
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        price_cents = int(item[0])
                        qty = int(item[1])
                        if price_cents > 0:
                            return price_cents, qty
                return None, 0

            # Best YES bid = highest price in yes_raw
            yes_sorted = sorted(yes_raw, key=lambda x: x[0] if isinstance(x, (list, tuple)) else 0, reverse=True)
            bid_price, bid_depth = _best(yes_sorted)
            # Best NO bid = highest price in no_raw → YES ask = 100 - that
            no_sorted = sorted(no_raw, key=lambda x: x[0] if isinstance(x, (list, tuple)) else 0, reverse=True)
            ask_from_no, ask_depth = _best(no_sorted)
            ask_price = (100 - ask_from_no) if ask_from_no is not None else None

            if bid_price is None or ask_price is None:
                print(f"  [{ticker}] Insufficient book data.")
                time.sleep(opts.interval)
                continue

            spread = ask_price - bid_price
            print(f"  [{ticker}]  bid={bid_price}c  ask={ask_price}c  spread={spread}c", end="")

            if spread <= opts.threshold:
                print("  << EVALUATING")
                entry = bid_price  # post at bid for maker
                exit_target = min(99, entry + cfg.default_take_profit_offset_cents)

                params = TradeParams(
                    market_ticker=ticker,
                    market_title=ticker,
                    outcome_contract="YES",
                    position_side="LONG",
                    entry_price_cents=entry,
                    exit_target_cents=exit_target,
                    entry_fill_type="MAKER",
                    exit_fill_type="MAKER",
                    market_has_maker_fees=False,
                    spread_cents=spread,
                    depth_at_price=bid_depth,
                )
                ev = evaluate_trade(params, cfg)
                print(format_order_ticket(ev))
            else:
                print()

            time.sleep(opts.interval)
    except KeyboardInterrupt:
        print("\n  Stopped.")
