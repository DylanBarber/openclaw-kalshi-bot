#!/usr/bin/env python3
"""
Diagnose SDK orderbook deserialization.
Dumps every attribute on the response to find where the yes/no data lives.
"""

from _common import make_client, section

section("SDK Orderbook Internals")

client = make_client()

# Use a known liquid ticker
ticker = "KXBTC-26FEB1517-B69250"
print(f"  Ticker: {ticker}\n")

resp = client.get_market_orderbook(ticker, depth=5)

print(f"  resp type: {type(resp).__name__}")
print(f"  resp dir: {[a for a in dir(resp) if not a.startswith('_')]}")
print(f"  resp.__dict__:")
for k, v in resp.__dict__.items():
    print(f"    {k}: {type(v).__name__} = {repr(v)[:200]}")

ob = resp.orderbook if hasattr(resp, "orderbook") else resp
print(f"\n  ob type: {type(ob).__name__}")
print(f"  ob dir: {[a for a in dir(ob) if not a.startswith('_')]}")
print(f"  ob.__dict__:")
for k, v in ob.__dict__.items():
    print(f"    {k}: {type(v).__name__} = {repr(v)[:200]}")

# Check if there's a model_fields_set or similar
for attr in ["model_fields_set", "model_extra", "model_fields", "__fields__",
             "__pydantic_fields__", "__annotations__"]:
    val = getattr(ob, attr, "MISSING")
    if val != "MISSING":
        print(f"\n  ob.{attr}: {val}")

# Try to_json
if hasattr(ob, "to_json"):
    print(f"\n  ob.to_json(): {ob.to_json()}")

# Try model_dump
if hasattr(ob, "model_dump"):
    print(f"\n  ob.model_dump(): {ob.model_dump()}")
    print(f"  ob.model_dump(by_alias=True): {ob.model_dump(by_alias=True)}")

# Check the full response object too
if hasattr(resp, "to_json"):
    j = resp.to_json()
    print(f"\n  resp.to_json() (first 1000 chars):\n  {j[:1000]}")

if hasattr(resp, "model_dump"):
    print(f"\n  resp.model_dump(): {resp.model_dump()}")

print("\n  Done.")
