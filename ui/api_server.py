#!/usr/bin/env python3
"""
api_server.py -- Flask REST API + static file server for the trading dashboard.

Serves the UI from ui/static/ and exposes JSON endpoints for:
  - Account balance & positions (live from Kalshi)
  - Active watchers (from watcher_store.json)
  - Orderbook data (raw HTTP, bypasses SDK)

Usage:
    python ui/api_server.py
    python ui/api_server.py --port 5123
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add scripts/ to path for imports
_scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from flask import Flask, jsonify, request, send_from_directory

# ── Configuration ─────────────────────────────────────────────────────────

DEFAULT_HOST = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_PORT = 5123

_project_root = Path(__file__).resolve().parent.parent
_static_dir = Path(__file__).resolve().parent / "static"


def _load_project_config() -> dict:
    """Load config.yaml from scripts/."""
    try:
        import yaml
        for p in [_project_root / "scripts" / "config.yaml", _project_root / "config.yaml"]:
            if p.is_file():
                return yaml.safe_load(p.read_text()) or {}
    except ImportError:
        pass
    return {}


def _get_host(config: dict) -> str:
    return os.environ.get("KALSHI_HOST", config.get("host", DEFAULT_HOST))


def _get_store_path(config: dict) -> Path:
    watcher_cfg = config.get("watcher", {})
    sp = watcher_cfg.get("store_path", "watcher_store.json")
    p = Path(sp)
    if not p.is_absolute():
        p = _project_root / "scripts" / p
    return p


# ── Kalshi client (lazy init) ────────────────────────────────────────────

_kalshi_client = None
_client_init_failed = False


def _build_client_direct(config: dict):
    """Build Kalshi client directly without importing runner.py.

    Tries multiple import paths to handle lazy_imports quirks in kalshi-python.
    """
    # Try various import strategies for Configuration + KalshiClient
    Configuration = None
    KalshiClient = None

    # Strategy 1: top-level import
    try:
        from kalshi_python import Configuration as _Cfg, KalshiClient as _Cli
        Configuration, KalshiClient = _Cfg, _Cli
    except (ImportError, AttributeError):
        pass

    # Strategy 2: submodule imports
    if Configuration is None:
        try:
            from kalshi_python.configuration import Configuration as _Cfg
            Configuration = _Cfg
        except (ImportError, AttributeError):
            pass

    if KalshiClient is None:
        try:
            from kalshi_python.kalshi_client import KalshiClient as _Cli
            KalshiClient = _Cli
        except (ImportError, AttributeError):
            pass

    if Configuration is None or KalshiClient is None:
        # Most common cause: kalshi-python needs cryptography but doesn't declare it
        crypto_hint = ""
        try:
            import cryptography  # noqa: F401
        except ImportError:
            crypto_hint = " (cryptography package is MISSING -- run: pip install cryptography)"
        raise ImportError(
            "Could not import Configuration/KalshiClient from kalshi_python"
            f"{crypto_hint}. Try: pip install cryptography kalshi-python"
        )

    host = config.get("host", DEFAULT_HOST)
    cfg = Configuration(host=host)

    api_key_id = config.get("api_key_id") or os.environ.get("KALSHI_API_KEY_ID")
    private_key_pem = config.get("private_key_pem") or os.environ.get("KALSHI_PRIVATE_KEY_PEM")
    private_key_path = config.get("private_key_path") or os.environ.get("KALSHI_PRIVATE_KEY_PATH")

    if not api_key_id:
        raise ValueError("api_key_id not set in config.yaml or KALSHI_API_KEY_ID env var")

    cfg.api_key_id = api_key_id

    if private_key_pem:
        cfg.private_key_pem = private_key_pem
    elif private_key_path:
        key_file = Path(private_key_path).expanduser()
        if not key_file.is_file():
            raise FileNotFoundError(f"Private key file not found: {key_file}")
        cfg.private_key_pem = key_file.read_text()
    else:
        raise ValueError("No private key configured (private_key_path or private_key_pem)")

    return KalshiClient(cfg)


def _get_client(config: dict):
    """Build Kalshi SDK client, cached. Returns None on failure."""
    global _kalshi_client, _client_init_failed
    if _kalshi_client is not None:
        return _kalshi_client
    if _client_init_failed:
        return None

    try:
        _kalshi_client = _build_client_direct(config)
    except Exception as e:
        print(f"  WARNING: Could not build Kalshi client: {e}", file=sys.stderr)
        _kalshi_client = None
        _client_init_failed = True

    return _kalshi_client


# ── Raw HTTP helpers ──────────────────────────────────────────────────────

def _fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── Flask app ─────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)


@app.route("/")
def index():
    return send_from_directory(str(_static_dir), "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(str(_static_dir), filename)


@app.route("/api/balance")
def api_balance():
    config = _load_project_config()
    client = _get_client(config)
    if client is None:
        return jsonify({"error": "Kalshi client not configured"}), 503

    try:
        resp = client.get_balance()
        balance = getattr(resp, "balance", 0) or 0
        portfolio_value = getattr(resp, "portfolio_value", 0) or 0
        return jsonify({
            "balance_cents": balance,
            "balance_dollars": balance / 100.0,
            "portfolio_value_cents": portfolio_value,
            "portfolio_value_dollars": portfolio_value / 100.0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/positions")
def api_positions():
    config = _load_project_config()
    client = _get_client(config)
    if client is None:
        return jsonify({"error": "Kalshi client not configured"}), 503

    try:
        resp = client.get_positions(limit=100)
        positions = getattr(resp, "positions", []) or []

        result = []
        for p in positions:
            result.append({
                "ticker": getattr(p, "ticker", "?"),
                "event_ticker": getattr(p, "event_ticker", ""),
                "position": getattr(p, "position", 0),
                "resting_order_count": getattr(p, "resting_order_count", 0),
                "realized_pnl": getattr(p, "realized_pnl", 0),
                "fees_paid": getattr(p, "fees_paid", 0),
                "total_cost": getattr(p, "total_cost", 0),
                "market_result": getattr(p, "market_result", ""),
            })
        return jsonify({"positions": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders")
def api_orders():
    config = _load_project_config()
    client = _get_client(config)
    if client is None:
        return jsonify({"error": "Kalshi client not configured"}), 503

    try:
        status_filter = request.args.get("status", "resting")
        resp = client.get_orders(status=status_filter, limit=100)
        orders = getattr(resp, "orders", []) or []

        result = []
        for o in orders:
            result.append({
                "order_id": getattr(o, "order_id", "?"),
                "ticker": getattr(o, "ticker", "?"),
                "side": getattr(o, "side", ""),
                "action": getattr(o, "action", ""),
                "type": getattr(o, "type", ""),
                "status": getattr(o, "status", ""),
                "yes_price": getattr(o, "yes_price", None),
                "no_price": getattr(o, "no_price", None),
                "count": getattr(o, "count", 0),
                "remaining_count": getattr(o, "remaining_count", 0),
                "created_time": str(getattr(o, "created_time", "")),
            })
        return jsonify({"orders": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/watchers")
def api_watchers():
    config = _load_project_config()
    store_path = _get_store_path(config)
    try:
        if store_path.is_file():
            data = json.loads(store_path.read_text())
        else:
            data = {}

        watchers = []
        for ticker, w in data.items():
            cur = w.get("current", {})
            entry_cents = w.get("entry_cents", 0)
            contracts = w.get("contracts", 0)
            yes_bid = cur.get("yes_bid")
            side = w.get("side", "LONG")

            pnl_cents = None
            pnl_dollars = None
            if yes_bid is not None and entry_cents:
                if side == "LONG":
                    pnl_cents = yes_bid - entry_cents
                else:
                    pnl_cents = entry_cents - yes_bid
                pnl_dollars = contracts * pnl_cents / 100.0 if contracts else 0

            watchers.append({
                "ticker": ticker,
                "title": w.get("title", ""),
                "side": side,
                "entry_cents": entry_cents,
                "contracts": contracts,
                "yes_bid": yes_bid,
                "yes_ask": cur.get("yes_ask"),
                "spread": cur.get("spread"),
                "pnl_cents": pnl_cents,
                "pnl_dollars": pnl_dollars,
                "stop_cents": w.get("stop_cents", 0),
                "take_profit_cents": w.get("take_profit_cents", 0),
                "status": w.get("status", "unknown"),
                "started_at": w.get("started_at", ""),
                "history_count": len(w.get("history", [])),
            })
        return jsonify({"watchers": watchers})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/watchers/<ticker>")
def api_watcher_detail(ticker):
    config = _load_project_config()
    store_path = _get_store_path(config)
    try:
        if store_path.is_file():
            data = json.loads(store_path.read_text())
        else:
            data = {}

        w = data.get(ticker)
        if w is None:
            return jsonify({"error": f"Watcher not found: {ticker}"}), 404
        return jsonify(w)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/watchers/<ticker>", methods=["DELETE"])
def api_remove_watcher(ticker):
    config = _load_project_config()
    store_path = _get_store_path(config)
    try:
        from watcher import remove_watcher
        if remove_watcher(store_path, ticker):
            return jsonify({"removed": ticker})
        else:
            return jsonify({"error": f"Watcher not found: {ticker}"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orderbook/<ticker>")
def api_orderbook(ticker):
    config = _load_project_config()
    host = _get_host(config)
    depth = request.args.get("depth", 10, type=int)

    data = _fetch_json(f"{host}/markets/{ticker}/orderbook?depth={depth}")
    if data is None:
        return jsonify({"error": "Failed to fetch orderbook"}), 502

    ob = data.get("orderbook", {})
    yes_levels = ob.get("yes") or []
    no_levels = ob.get("no") or []

    best_yes_bid = yes_levels[-1][0] if yes_levels else None
    best_no_bid = no_levels[-1][0] if no_levels else None
    best_yes_ask = (100 - best_no_bid) if best_no_bid is not None else None

    return jsonify({
        "ticker": ticker,
        "yes": yes_levels,
        "no": no_levels,
        "best_yes_bid": best_yes_bid,
        "best_yes_ask": best_yes_ask,
        "spread": (best_yes_ask - best_yes_bid) if (best_yes_bid is not None and best_yes_ask is not None) else None,
    })


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kalshi trading dashboard server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    print(f"  Kalshi Dashboard: http://{args.host}:{args.port}")
    print(f"  Static dir: {_static_dir}")
    print(f"  Press Ctrl-C to stop.\n")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
