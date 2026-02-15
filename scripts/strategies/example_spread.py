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
import sys
import time
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

    try:
        while True:
            resp = client.get_market_orderbook(ticker, depth=10)
            ob = resp.orderbook if hasattr(resp, "orderbook") else resp

            # SDK uses var_true/var_false; older versions use yes/no
            yes_raw = getattr(ob, "var_true", None) or getattr(ob, "yes", None) or []
            no_raw = getattr(ob, "var_false", None) or getattr(ob, "no", None) or []

            # Fallback: try to_dict()
            if not yes_raw and hasattr(ob, "to_dict"):
                d = ob.to_dict()
                yes_raw = d.get("yes") or d.get("var_true") or d.get("true") or []
                no_raw = d.get("no") or d.get("var_false") or d.get("false") or []

            # Parse best level from a list of OrderbookLevel objects or [price, qty] arrays
            def _best(levels):
                for item in levels:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        p = float(item[0])
                        q = int(item[1])
                    elif isinstance(item, dict):
                        p = float(item.get("price", 0))
                        q = int(item.get("count", item.get("quantity", 0)))
                    elif hasattr(item, "price"):
                        p = float(item.price) if item.price is not None else 0
                        q = int(getattr(item, "count", None) or getattr(item, "quantity", 0) or 0)
                    else:
                        continue
                    # Detect dollars (0 < p < 1) vs cents
                    price_cents = round(p * 100) if 0 < p < 1.0 else int(p)
                    if price_cents > 0:
                        return price_cents, q
                return None, 0

            def _sort_key(x):
                if hasattr(x, "price"):
                    return -(float(x.price or 0))
                elif isinstance(x, (list, tuple)):
                    return -(float(x[0]))
                elif isinstance(x, dict):
                    return -(float(x.get("price", 0)))
                return 0

            bid_price, bid_depth = _best(sorted(yes_raw, key=_sort_key))
            ask_from_no, ask_depth = _best(sorted(no_raw, key=_sort_key))
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
