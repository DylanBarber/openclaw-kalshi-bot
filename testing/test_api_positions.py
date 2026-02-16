#!/usr/bin/env python3
"""Test the api_server's /api/positions endpoint directly (no Flask)."""

import json
import os
import sys
from pathlib import Path

# Load .env
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Add ui/ to path
ui_dir = str(Path(__file__).resolve().parent.parent / "ui")
scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, ui_dir)
sys.path.insert(0, scripts_dir)

from api_server import _load_project_config, _get_host, _fetch_authed_json

config = _load_project_config()
host = _get_host(config)

print("=" * 70)
print("  API Server Positions Test")
print("=" * 70)
print(f"  Host: {host}")

data = _fetch_authed_json(config, host, "/portfolio/positions?limit=200")
if data is None:
    print("  FAILED: _fetch_authed_json returned None")
    sys.exit(1)

market_positions = data.get("market_positions", []) or []
event_positions = data.get("event_positions", []) or []

print(f"  market_positions: {len(market_positions)}")
print(f"  event_positions: {len(event_positions)}")

# Simulate what the endpoint does
result = []
for p in market_positions:
    pos = p.get("position", 0)
    if pos == 0 and p.get("resting_orders_count", 0) == 0:
        continue
    result.append({
        "ticker": p.get("ticker", "?"),
        "position": pos,
        "market_exposure_dollars": p.get("market_exposure_dollars", "0.00"),
        "fees_paid_dollars": p.get("fees_paid_dollars", "0.00"),
        "realized_pnl_dollars": p.get("realized_pnl_dollars", "0.00"),
        "resting_orders_count": p.get("resting_orders_count", 0),
    })

print(f"\n  Active positions for UI: {len(result)}")
for r in result:
    print(f"    {r['ticker']}: pos={r['position']} exposure=${r['market_exposure_dollars']} fees=${r['fees_paid_dollars']}")

print(f"\n  Event positions for UI: {len(event_positions)}")
for ep in event_positions:
    print(f"    {ep.get('event_ticker')}: exposure=${ep.get('event_exposure_dollars')} cost=${ep.get('total_cost_dollars')}")

print(f"\n  PASS: {len(result)} market positions + {len(event_positions)} event positions ready for UI")
