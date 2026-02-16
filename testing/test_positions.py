#!/usr/bin/env python3
"""Debug positions endpoint - what does the SDK actually return?"""

import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path

# Load .env
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("KALSHI_API_KEY_ID", "")
KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
HOST = "https://api.elections.kalshi.com/trade-api/v2"


def sign_request(method, path, timestamp_ms):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key_data = Path(KEY_PATH).read_bytes()
    private_key = serialization.load_pem_private_key(key_data, password=None)

    msg = f"{timestamp_ms}{method}{path}".encode()
    sig = private_key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def authed_get(path):
    url = f"{HOST}{path}"
    ts = str(int(time.time() * 1000))
    sig = sign_request("GET", path, ts)
    req = urllib.request.Request(url)
    req.add_header("KALSHI-ACCESS-KEY", API_KEY)
    req.add_header("KALSHI-ACCESS-SIGNATURE", sig)
    req.add_header("KALSHI-ACCESS-TIMESTAMP", ts)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {e.reason}", "body": body}
    except Exception as e:
        return {"error": str(e)}


print("=" * 70)
print("  Positions Debug")
print("=" * 70)

# 1. Raw HTTP: get positions
print("\n  [1] Raw HTTP: GET /portfolio/positions?limit=100")
data = authed_get("/portfolio/positions?limit=100")
print(json.dumps(data, indent=2, default=str)[:3000])

# 2. Try market_positions key
print("\n  [2] Checking response keys:")
if isinstance(data, dict):
    for k in data.keys():
        v = data[k]
        if isinstance(v, list):
            print(f"    '{k}': list of {len(v)} items")
            if v:
                print(f"    First item keys: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0])}")
                print(f"    First item: {json.dumps(v[0], indent=4, default=str)[:500]}")
        else:
            print(f"    '{k}': {type(v).__name__} = {str(v)[:100]}")

# 3. SDK approach
print("\n  [3] SDK: client.get_positions(limit=100)")
try:
    scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
    sys.path.insert(0, scripts_dir)
    from runner import load_config, build_client
    cfg = load_config()
    client = build_client(cfg)

    resp = client.get_positions(limit=100)
    print(f"    Response type: {type(resp).__name__}")
    print(f"    Response attrs: {[a for a in dir(resp) if not a.startswith('_')]}")

    # Try various attribute names
    for attr in ["positions", "market_positions", "event_positions", "data"]:
        val = getattr(resp, attr, "NOT_FOUND")
        if val != "NOT_FOUND":
            if isinstance(val, list):
                print(f"    .{attr}: list of {len(val)} items")
                if val:
                    item = val[0]
                    print(f"      First item type: {type(item).__name__}")
                    attrs = [a for a in dir(item) if not a.startswith('_')]
                    print(f"      First item attrs: {attrs}")
                    if hasattr(item, "to_dict"):
                        print(f"      First item dict: {json.dumps(item.to_dict(), indent=4, default=str)[:500]}")
                    elif hasattr(item, "__dict__"):
                        print(f"      First item __dict__: {json.dumps(item.__dict__, indent=4, default=str)[:500]}")
            else:
                print(f"    .{attr}: {type(val).__name__} = {str(val)[:200]}")

    # Also try to_dict on the response itself
    if hasattr(resp, "to_dict"):
        d = resp.to_dict()
        print(f"\n    resp.to_dict() keys: {list(d.keys())}")
        for k, v in d.items():
            if isinstance(v, list):
                print(f"      '{k}': {len(v)} items")
            else:
                print(f"      '{k}': {str(v)[:100]}")

except Exception as e:
    print(f"    ERROR: {e}")
    import traceback
    traceback.print_exc()

print()
