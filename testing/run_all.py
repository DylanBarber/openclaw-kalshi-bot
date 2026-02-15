#!/usr/bin/env python3
"""
Run all test scripts in sequence.
Stops on first failure unless --continue is passed.

Usage:
    python testing/run_all.py
    python testing/run_all.py --continue
    python testing/run_all.py --ticker KXBTC-26FEB14-T50050
"""

import argparse
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--continue", dest="keep_going", action="store_true",
                    help="Continue on failure")
parser.add_argument("--ticker", default=None, help="Ticker for orderbook/orders tests")
args = parser.parse_args()

testing_dir = Path(__file__).parent
python = sys.executable

tests = [
    ("Connection & Auth", [python, str(testing_dir / "test_connection.py")]),
    ("Markets API", [python, str(testing_dir / "test_markets.py")]),
    ("Orderbook", [python, str(testing_dir / "test_orderbook.py"),
                   args.ticker or "KXBTC-26FEB15-B50000"]),
    ("Orders & Portfolio", [python, str(testing_dir / "test_orders.py")]),
]

# Add --ticker to relevant tests if provided
if args.ticker:
    tests[2] = ("Orderbook", [python, str(testing_dir / "test_orderbook.py"), args.ticker])
    tests[3] = ("Orders & Portfolio", [python, str(testing_dir / "test_orders.py"),
                                       "--ticker", args.ticker])

results = []
for name, cmd in tests:
    print(f"\n{'#'*60}")
    print(f"#  Running: {name}")
    print(f"#  Command: {' '.join(cmd)}")
    print(f"{'#'*60}\n")

    ret = subprocess.run(cmd, cwd=str(testing_dir))
    passed = ret.returncode == 0
    results.append((name, passed))

    if not passed and not args.keep_going:
        print(f"\n  STOPPED — '{name}' failed (exit code {ret.returncode})")
        print(f"  Re-run with --continue to run remaining tests")
        break

print(f"\n{'='*60}")
print("  RESULTS")
print(f"{'='*60}")
for name, passed in results:
    icon = "PASS" if passed else "FAIL"
    print(f"  [{icon}]  {name}")

total = len(results)
passed_count = sum(1 for _, p in results if p)
print(f"\n  {passed_count}/{total} passed")

sys.exit(0 if all(p for _, p in results) else 1)
