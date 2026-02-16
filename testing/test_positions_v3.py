#!/usr/bin/env python3
"""Use the SDK's own rest client properly, patching response_deserialize."""

import json
import os
import sys
from pathlib import Path

scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, scripts_dir)

env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from runner import load_config, build_client
cfg = load_config()
client = build_client(cfg)

print("=" * 70)
print("  Deserialization Intercept")
print("=" * 70)

# Patch response_deserialize
original_deser = client.api_client.response_deserialize

def logging_deser(response_data, response_types_map):
    raw_data = response_data.data
    status = response_data.status
    if isinstance(raw_data, bytes):
        decoded = raw_data.decode("utf-8", errors="replace")
    elif raw_data is not None:
        decoded = str(raw_data)
    else:
        decoded = "(None)"

    print(f"  [Deserialize] status={status}, body({len(decoded) if decoded else 0}): {decoded[:2000]}")

    try:
        parsed = json.loads(decoded) if decoded and decoded != "(None)" else None
        if parsed and isinstance(parsed, dict):
            print(f"  [Deserialize] JSON keys: {list(parsed.keys())}")
            for k, v in parsed.items():
                if isinstance(v, list):
                    print(f"    '{k}': {len(v)} items")
                    if v and isinstance(v[0], dict):
                        print(f"      First item keys: {list(v[0].keys())}")
                else:
                    print(f"    '{k}': {str(v)[:100]}")
    except Exception:
        pass

    return original_deser(response_data, response_types_map)

client.api_client.response_deserialize = logging_deser

# Test 1: get_positions
print("\n  === get_positions(limit=100) ===")
try:
    resp = client.get_positions(limit=100)
    print(f"  Final: positions={resp.positions}, cursor='{resp.cursor}'")
    d = resp.to_dict()
    print(f"  to_dict: {d}")
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback
    traceback.print_exc()

# Test 2: get_orders
print("\n  === get_orders(status='resting', limit=5) ===")
try:
    resp2 = client.get_orders(status="resting", limit=5)
    orders = getattr(resp2, "orders", []) or []
    print(f"  Final: {len(orders)} orders")
    if orders:
        for o in orders[:2]:
            d = o.to_dict() if hasattr(o, 'to_dict') else str(o)
            print(f"    {json.dumps(d, indent=2, default=str)[:300]}")
except Exception as e:
    print(f"  ERROR: {e}")

# Test 3: get_fills
print("\n  === get_fills(limit=5) ===")
try:
    resp3 = client.get_fills(limit=5)
    fills = getattr(resp3, "fills", []) or []
    print(f"  Final: {len(fills)} fills")
    if fills:
        for f in fills[:2]:
            d = f.to_dict() if hasattr(f, 'to_dict') else str(f)
            print(f"    {json.dumps(d, indent=2, default=str)[:300]}")
except Exception as e:
    print(f"  ERROR: {e}")

client.api_client.response_deserialize = original_deser
print()
