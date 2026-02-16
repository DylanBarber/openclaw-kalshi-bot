#!/usr/bin/env python3
"""Verify the positions fix works end-to-end."""

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

scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, scripts_dir)

from runner import load_config, _fetch_authed_json, DEFAULT_HOST

cfg = load_config()
host = cfg.get("host", DEFAULT_HOST)

print("=" * 70)
print("  Positions Fix Verification")
print("=" * 70)

# Test raw authed fetch
print("\n  [1] _fetch_authed_json('/portfolio/positions?limit=200')")
data = _fetch_authed_json(cfg, host, "/portfolio/positions?limit=200")

if data is None:
    print("    FAILED: returned None")
    sys.exit(1)

market_positions = data.get("market_positions", []) or []
event_positions = data.get("event_positions", []) or []

print(f"    market_positions: {len(market_positions)} items")
print(f"    event_positions: {len(event_positions)} items")

if market_positions:
    active = [p for p in market_positions if p.get("position", 0) != 0]
    print(f"    active (non-zero): {len(active)}")
    for p in active:
        print(f"      {p.get('ticker')}: pos={p.get('position')} exposure=${p.get('market_exposure_dollars')} fees=${p.get('fees_paid_dollars')}")

if event_positions:
    for ep in event_positions:
        print(f"      event: {ep.get('event_ticker')} exposure=${ep.get('event_exposure_dollars')} cost=${ep.get('total_cost_dollars')}")

# Compare with SDK (should be empty/broken)
print("\n  [2] SDK get_positions (for comparison - expected broken):")
try:
    from runner import build_client
    client = build_client(cfg)
    resp = client.get_positions(limit=200)
    sdk_positions = getattr(resp, "positions", None)
    print(f"    SDK .positions: {sdk_positions}")
    print(f"    SDK .to_dict(): {resp.to_dict()}")
except Exception as e:
    print(f"    SDK error: {e}")

print(f"\n  RESULT: {'PASS' if market_positions else 'FAIL'} - raw HTTP returns {len(market_positions)} market positions")
print(f"  (SDK would return: None/empty)")
