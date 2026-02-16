#!/usr/bin/env python3
"""Deep debug: what does the raw API return vs what the SDK deserializes?"""

import json
import os
import sys
from pathlib import Path

scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, scripts_dir)

# Load .env
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
print("  Deep Positions Debug")
print("=" * 70)

# 1. Check the SDK's PositionsAPI method signature
print("\n  [1] SDK get_positions method signature:")
import inspect
try:
    sig = inspect.signature(client.get_positions)
    print(f"    {sig}")
except Exception as e:
    print(f"    Error: {e}")

# 2. Try different parameter combos
print("\n  [2] Trying different parameter combos:")
combos = [
    {"limit": 100},
    {"limit": 10},
    {},
    {"settlement_status": "unsettled"},
    {"count_filter": "has_position"},
]

for kwargs in combos:
    try:
        resp = client.get_positions(**kwargs)
        positions = getattr(resp, "positions", None)
        market_positions = getattr(resp, "market_positions", None)
        event_positions = getattr(resp, "event_positions", None)
        cursor = getattr(resp, "cursor", None)

        pos_count = len(positions) if positions else 0
        mp_count = len(market_positions) if market_positions else 0
        ep_count = len(event_positions) if event_positions else 0

        d = resp.to_dict() if hasattr(resp, "to_dict") else {}

        print(f"    {kwargs} -> positions={pos_count}, market_positions={mp_count}, event_positions={ep_count}, cursor='{cursor}', dict_keys={list(d.keys())}")

        # If any has items, dump the first
        for name, val in [("positions", positions), ("market_positions", market_positions), ("event_positions", event_positions)]:
            if val and len(val) > 0:
                item = val[0]
                if hasattr(item, "to_dict"):
                    print(f"      First {name} item: {json.dumps(item.to_dict(), indent=4, default=str)[:500]}")
                elif hasattr(item, "__dict__"):
                    print(f"      First {name} item: {json.dumps(item.__dict__, indent=4, default=str)[:500]}")
                else:
                    print(f"      First {name} item: {item}")

    except Exception as e:
        print(f"    {kwargs} -> ERROR: {e}")

# 3. Monkey-patch to intercept the raw API response
print("\n  [3] Intercepting raw HTTP response:")
try:
    original_call = client.api_client.rest_client.request

    last_response = {}

    def intercepting_request(*args, **kwargs):
        resp = original_call(*args, **kwargs)
        try:
            body = resp.data.decode() if isinstance(resp.data, bytes) else resp.data
            last_response["status"] = resp.status
            last_response["body"] = body[:3000]
        except Exception:
            pass
        return resp

    client.api_client.rest_client.request = intercepting_request

    resp = client.get_positions(limit=100)
    print(f"    HTTP status: {last_response.get('status')}")
    raw_body = last_response.get("body", "")
    print(f"    Raw body ({len(raw_body)} chars):")
    # Parse and pretty print
    try:
        parsed = json.loads(raw_body)
        print(json.dumps(parsed, indent=2, default=str)[:2000])
    except Exception:
        print(f"    {raw_body[:2000]}")

    # Restore
    client.api_client.rest_client.request = original_call

except Exception as e:
    print(f"    Error: {e}")
    import traceback
    traceback.print_exc()

# 4. Check the Pydantic model fields
print("\n  [4] Pydantic model fields:")
try:
    from kalshi_python.models.get_positions_response import GetPositionsResponse
    print(f"    Model fields: {list(GetPositionsResponse.model_fields.keys())}")
    for fname, finfo in GetPositionsResponse.model_fields.items():
        alias = finfo.alias if hasattr(finfo, 'alias') else None
        print(f"      {fname}: alias={alias}, type={finfo.annotation}")
except Exception as e:
    print(f"    Error: {e}")

print()
