#!/usr/bin/env python3
"""
watcher.py -- Position price watcher daemon.

Polls Kalshi orderbook at configurable intervals, records price history
to a shared JSON state file, and prints alerts when stop/TP levels are hit.

Can run standalone or be spawned by fee_aware_mm after a fill.

Usage:
    python watcher.py <ticker> [options]
    python watcher.py KXBTC-26FEB1517-B69250 --entry 40 --side LONG --contracts 10
    python watcher.py --remove KXBTC-26FEB1517-B69250
    python watcher.py --list
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

# ── Defaults ──────────────────────────────────────────────────────────────

DEFAULT_HOST = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_POLL_INTERVAL = 5
DEFAULT_MAX_HISTORY = 500
DEFAULT_STORE_PATH = Path(__file__).resolve().parent / "watcher_store.json"


# ── Store helpers ─────────────────────────────────────────────────────────

def _load_store(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_store(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


# ── Orderbook fetch (raw HTTP, bypasses SDK alias bug) ────────────────────

def fetch_orderbook(host: str, ticker: str, depth: int = 5) -> dict:
    """Return {"yes": [[p,q],...], "no": [[p,q],...]} or empty."""
    url = f"{host}/markets/{ticker}/orderbook?depth={depth}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError):
        return {"yes": [], "no": []}
    ob = data.get("orderbook", data)
    return {"yes": ob.get("yes") or [], "no": ob.get("no") or []}


def fetch_market_info(host: str, ticker: str) -> dict:
    """Fetch basic market info (title, status, last_price)."""
    url = f"{host}/markets/{ticker}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError):
        return {}
    return data.get("market", data)


# ── Core watcher logic ────────────────────────────────────────────────────

def add_watcher(
    store_path: Path,
    ticker: str,
    entry_cents: int = 0,
    side: str = "LONG",
    contracts: int = 0,
    stop_cents: int = 0,
    take_profit_cents: int = 0,
    title: str = "",
) -> dict:
    """Add or update a watcher entry in the store."""
    store = _load_store(store_path)

    now = datetime.now(timezone.utc).isoformat()

    if ticker in store:
        entry = store[ticker]
        if entry_cents:
            entry["entry_cents"] = entry_cents
        if contracts:
            entry["contracts"] = contracts
        if stop_cents:
            entry["stop_cents"] = stop_cents
        if take_profit_cents:
            entry["take_profit_cents"] = take_profit_cents
        if title:
            entry["title"] = title
        entry["side"] = side
    else:
        entry = {
            "ticker": ticker,
            "title": title,
            "side": side,
            "entry_cents": entry_cents,
            "contracts": contracts,
            "started_at": now,
            "history": [],
            "current": {},
            "stop_cents": stop_cents,
            "take_profit_cents": take_profit_cents,
            "status": "watching",
        }

    store[ticker] = entry
    _save_store(store_path, store)
    return entry


def remove_watcher(store_path: Path, ticker: str) -> bool:
    """Remove a watcher from the store. Returns True if found."""
    store = _load_store(store_path)
    if ticker in store:
        del store[ticker]
        _save_store(store_path, store)
        return True
    return False


def list_watchers(store_path: Path) -> dict:
    """Return all watchers."""
    return _load_store(store_path)


def poll_once(
    store_path: Path,
    ticker: str,
    host: str,
    max_history: int,
) -> dict | None:
    """Fetch current prices, update history, check alerts. Returns snapshot."""
    store = _load_store(store_path)
    entry = store.get(ticker)
    if not entry:
        return None

    ob = fetch_orderbook(host, ticker, depth=5)

    yes_levels = ob.get("yes") or []
    no_levels = ob.get("no") or []

    best_yes_bid = yes_levels[-1][0] if yes_levels else None
    best_no_bid = no_levels[-1][0] if no_levels else None
    best_yes_ask = (100 - best_no_bid) if best_no_bid is not None else None
    spread = (best_yes_ask - best_yes_bid) if (best_yes_bid is not None and best_yes_ask is not None) else None

    now = datetime.now(timezone.utc).isoformat()

    snapshot = {
        "ts": now,
        "yes_bid": best_yes_bid,
        "yes_ask": best_yes_ask,
        "spread": spread,
    }

    # Compute fee-aware P&L if we have entry price and current bid
    entry_cents = entry.get("entry_cents", 0)
    contracts = entry.get("contracts", 0)
    side = entry.get("side", "LONG")

    if best_yes_bid is not None and entry_cents and contracts:
        try:
            from kalshi_math import (
                gross_pnl_usd, compute_worst_case_fees, net_pnl, slippage_usd,
            )
            current_exit = best_yes_bid if side == "LONG" else best_yes_ask or best_yes_bid
            gross = gross_pnl_usd(side, contracts, entry_cents, current_exit)
            _, _, fee_worst = compute_worst_case_fees(
                contracts, entry_cents, current_exit, ticker, False,
            )
            slip = slippage_usd(contracts, 1)  # 1c default buffer
            net = net_pnl(gross, fee_worst, slip)

            snapshot["gross_pnl"] = round(gross, 4)
            snapshot["fees_worst"] = round(fee_worst, 4)
            snapshot["net_pnl"] = round(net, 4)
        except Exception:
            pass  # kalshi_math not available; skip

    entry["current"] = snapshot
    entry["history"].append(snapshot)

    if len(entry["history"]) > max_history:
        entry["history"] = entry["history"][-max_history:]

    # Check alerts
    alerts = []
    if best_yes_bid is not None and entry.get("entry_cents"):
        side = entry.get("side", "LONG")
        price = best_yes_bid

        if side == "LONG":
            if entry.get("stop_cents") and price <= entry["stop_cents"]:
                alerts.append(f"STOP HIT: {ticker} YES bid {price}c <= stop {entry['stop_cents']}c")
                entry["status"] = "stopped"
            if entry.get("take_profit_cents") and price >= entry["take_profit_cents"]:
                alerts.append(f"TAKE PROFIT HIT: {ticker} YES bid {price}c >= TP {entry['take_profit_cents']}c")
                entry["status"] = "tp_hit"
        else:
            if entry.get("stop_cents") and price >= entry["stop_cents"]:
                alerts.append(f"STOP HIT: {ticker} YES bid {price}c >= stop {entry['stop_cents']}c (SHORT)")
                entry["status"] = "stopped"
            if entry.get("take_profit_cents") and price <= entry["take_profit_cents"]:
                alerts.append(f"TAKE PROFIT HIT: {ticker} YES bid {price}c <= TP {entry['take_profit_cents']}c (SHORT)")
                entry["status"] = "tp_hit"

    store[ticker] = entry
    _save_store(store_path, store)

    return {"snapshot": snapshot, "alerts": alerts, "status": entry["status"]}


def run_watcher(
    ticker: str,
    host: str = DEFAULT_HOST,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_history: int = DEFAULT_MAX_HISTORY,
    store_path: Path = DEFAULT_STORE_PATH,
    entry_cents: int = 0,
    side: str = "LONG",
    contracts: int = 0,
    stop_cents: int = 0,
    take_profit_cents: int = 0,
) -> None:
    """Main watcher loop. Runs until Ctrl-C or stop/TP hit."""

    # Fetch market info (title + status)
    mkt = fetch_market_info(host, ticker)
    title = mkt.get("title", "")
    mkt_status = mkt.get("status", "unknown")

    add_watcher(
        store_path, ticker,
        entry_cents=entry_cents, side=side, contracts=contracts,
        stop_cents=stop_cents, take_profit_cents=take_profit_cents,
        title=title,
    )

    print(f"  Watcher started: {ticker}")
    print(f"  Title:  {title or '(not found)'}")
    print(f"  Market: {mkt_status}")
    print(f"  Side:   {side}  Entry: {entry_cents}c  Contracts: {contracts}")
    print(f"  Stop:   {stop_cents}c  TP: {take_profit_cents}c")
    print(f"  Poll:   every {poll_interval}s  (Ctrl-C to stop)")
    print(f"  Store:  {store_path}")

    if mkt_status in ("closed", "settled"):
        print(f"\n  WARNING: Market is '{mkt_status}' -- orderbook will be empty.")
        print(f"  Use a currently open market for live price tracking.")
    if not title and not mkt_status:
        print(f"\n  WARNING: Could not fetch market info for {ticker}.")
        print(f"  Check that the ticker is valid and the API host is reachable.")

    print()

    empty_count = 0
    try:
        while True:
            result = poll_once(store_path, ticker, host, max_history)
            if result is None:
                print(f"  Watcher for {ticker} not found in store. Exiting.")
                break

            snap = result["snapshot"]
            bid = snap.get("yes_bid")
            ask = snap.get("yes_ask")
            spread = snap.get("spread")

            if bid is None and ask is None:
                empty_count += 1
                if empty_count == 3:
                    print(f"  (orderbook empty for 3 consecutive polls -- market may be settled/closed or illiquid)")
            else:
                empty_count = 0

            bid_s = f"{bid}c" if bid is not None else "--"
            ask_s = f"{ask}c" if ask is not None else "--"
            spread_s = f"{spread}c" if spread is not None else "--"

            pnl_str = ""
            gross = snap.get("gross_pnl")
            net = snap.get("net_pnl")
            fees = snap.get("fees_worst")
            if gross is not None:
                g_sign = "+" if gross >= 0 else ""
                n_sign = "+" if net is not None and net >= 0 else ""
                pnl_str = f"  gross={g_sign}${gross:.2f}"
                if fees is not None:
                    pnl_str += f"  fees=${fees:.2f}"
                if net is not None:
                    pnl_str += f"  net={n_sign}${net:.2f}"
            elif entry_cents and bid is not None:
                if side == "LONG":
                    pnl_cents = bid - entry_cents
                else:
                    pnl_cents = entry_cents - bid
                pnl_dollars = contracts * pnl_cents / 100.0 if contracts else 0
                sign = "+" if pnl_cents >= 0 else ""
                pnl_str = f"  gross={sign}${pnl_dollars:.2f} (no fee calc)"

            ts_short = snap["ts"][11:19]
            print(f"  [{ts_short}] {ticker}  bid={bid_s}  ask={ask_s}  spread={spread_s}{pnl_str}")

            for alert in result.get("alerts", []):
                print(f"  *** ALERT: {alert} ***")

            if result["status"] in ("stopped", "tp_hit"):
                print(f"\n  Watcher exiting: {result['status']}")
                break

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print(f"\n  Watcher stopped by user.")


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Kalshi position watcher daemon",
    )
    parser.add_argument("ticker", nargs="?", default=None, help="Market ticker to watch")
    parser.add_argument("--entry", type=int, default=0, help="Entry price in cents")
    parser.add_argument("--side", default="LONG", choices=["LONG", "SHORT"], help="Position side")
    parser.add_argument("--contracts", type=int, default=0, help="Number of contracts")
    parser.add_argument("--stop", type=int, default=0, help="Stop price in cents")
    parser.add_argument("--tp", type=int, default=0, help="Take profit price in cents")
    parser.add_argument("--interval", type=float, default=None, help="Poll interval in seconds")
    parser.add_argument("--list", action="store_true", help="List all active watchers")
    parser.add_argument("--remove", metavar="TICKER", default=None, help="Remove a watcher")
    parser.add_argument("--store", default=None, help="Path to watcher_store.json")
    parser.add_argument("--host", default=None, help="Kalshi API host")

    args = parser.parse_args()

    # Load config for defaults
    config: dict[str, Any] = {}
    try:
        import yaml
        for p in [Path.cwd() / "config.yaml", Path(__file__).resolve().parent / "config.yaml"]:
            if p.is_file():
                config = yaml.safe_load(p.read_text()) or {}
                break
    except ImportError:
        pass

    watcher_cfg = config.get("watcher", {})
    host = args.host or os.environ.get("KALSHI_HOST", config.get("host", DEFAULT_HOST))
    poll_interval = args.interval or watcher_cfg.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL)
    max_history = watcher_cfg.get("max_history_points", DEFAULT_MAX_HISTORY)
    store_path = Path(args.store) if args.store else Path(watcher_cfg.get("store_path", DEFAULT_STORE_PATH))

    if not store_path.is_absolute():
        store_path = Path(__file__).resolve().parent / store_path

    if args.list:
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
        parser.print_help()
        sys.exit(1)

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
    )


if __name__ == "__main__":
    main()
