#!/usr/bin/env python3
"""
Test 1: Connection & Authentication
────────────────────────────────────
Verifies that credentials work, prints account balance and exchange status.

Usage:
    python testing/test_connection.py
"""

from _common import make_client, pp, section

section("TEST: Connection & Authentication")

client = make_client()

# ── Balance ───────────────────────────────────────────────────────────────
print("\n  Fetching balance...")
try:
    resp = client.get_balance()
    pp(resp, "Balance Response")
except Exception as e:
    print(f"  FAILED: {e}")

# ── Exchange status ───────────────────────────────────────────────────────
print("\n  Fetching exchange status...")
try:
    resp = client.get_exchange_status()
    pp(resp, "Exchange Status")
except Exception as e:
    print(f"  FAILED: {e}")

print("\n  Done.")
