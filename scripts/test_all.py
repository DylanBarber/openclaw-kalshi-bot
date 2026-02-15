#!/usr/bin/env python3
"""
Smoke tests for kalshi_math, trade_engine, and orderbook parsing helpers.
Run:  python scripts/test_all.py
"""

from __future__ import annotations

import sys
import os
import math

# Ensure scripts/ is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0


def check(name: str, got, expected, tol: float = 0.0001):
    global passed, failed
    if isinstance(expected, float):
        ok = abs(got - expected) < tol
    else:
        ok = got == expected
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  got={got!r}  expected={expected!r}")


# ═══════════════════════════════════════════════════════════════════════════
# 1. kalshi_math tests
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== kalshi_math ===")

from kalshi_math import (
    round_up_cent, is_index_market, taker_coeff, fee_usd,
    effective_k, compute_round_trip_fees, gross_pnl_usd,
    break_even_exit_cents, K_TAKER_GENERAL, K_TAKER_INDEX, K_MAKER,
)

# round_up_cent
check("round_up_cent(0.123)", round_up_cent(0.123), 0.13)
check("round_up_cent(0.10)", round_up_cent(0.10), 0.10)
check("round_up_cent(0.001)", round_up_cent(0.001), 0.01)
check("round_up_cent(0.0)", round_up_cent(0.0), 0.0)

# is_index_market
check("is_index_market('INXD-26FEB')", is_index_market("INXD-26FEB"), True)
check("is_index_market('NASDAQ100-X')", is_index_market("NASDAQ100-X"), True)
check("is_index_market('KXBTC-26FEB')", is_index_market("KXBTC-26FEB"), False)

# taker_coeff
check("taker_coeff('INXD-26FEB')", taker_coeff("INXD-26FEB"), K_TAKER_INDEX)
check("taker_coeff('KXBTC-26FEB')", taker_coeff("KXBTC-26FEB"), K_TAKER_GENERAL)

# fee_usd — Section 4: fee = round_up_cent(k * C * P * (1-P))
# 10 contracts, P=0.50, k=0.07 → round_up_cent(0.07*10*0.5*0.5) = round_up_cent(0.175) = 0.18
check("fee_usd(10, 0.50, 0.07)", fee_usd(10, 0.50, 0.07), 0.18)
# 1 contract, P=0.65, k=0.07 → round_up_cent(0.07*1*0.65*0.35) = round_up_cent(0.015925) = 0.02
check("fee_usd(1, 0.65, 0.07)", fee_usd(1, 0.65, 0.07), 0.02)

# effective_k
check("effective_k(TAKER, general)", effective_k("TAKER", "KXBTC", True), K_TAKER_GENERAL)
check("effective_k(MAKER, maker_fees)", effective_k("MAKER", "KXBTC", True), K_MAKER)
check("effective_k(MAKER, no_maker_fees)", effective_k("MAKER", "KXBTC", False), 0.0)

# gross_pnl_usd — LONG at 40c, exit 60c, 10 contracts → +10*(20/100) = +2.0
check("gross_pnl_usd(LONG,10,40,60)", gross_pnl_usd("LONG", 10, 40, 60), 2.0)
# SHORT at 60c, exit 40c, 10 contracts → +10*(20/100) = +2.0
check("gross_pnl_usd(SHORT,10,60,40)", gross_pnl_usd("SHORT", 10, 60, 40), 2.0)
# LONG at 40c, exit 30c (loss) → -10*(10/100) = -1.0
check("gross_pnl_usd(LONG,10,40,30)", gross_pnl_usd("LONG", 10, 40, 30), -1.0)

# break_even_exit_cents — LONG at 40c should find break-even above 40
be = break_even_exit_cents(40, "LONG", 10, "KXBTC", False, "TAKER", "TAKER", 1.0)
check("break_even_exit(LONG@40) is not None", be is not None, True)
if be is not None:
    check("break_even_exit(LONG@40) > 40", be > 40, True)

# break_even — SHORT at 60c should find break-even below 60
be_s = break_even_exit_cents(60, "SHORT", 10, "KXBTC", False, "TAKER", "TAKER", 1.0)
check("break_even_exit(SHORT@60) is not None", be_s is not None, True)
if be_s is not None:
    check("break_even_exit(SHORT@60) < 60", be_s < 60, True)


# ═══════════════════════════════════════════════════════════════════════════
# 2. trade_engine tests
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== trade_engine ===")

from trade_engine import RiskConfig, TradeParams, evaluate_trade, format_order_ticket

cfg = RiskConfig()

# Basic evaluation — should produce a TradeEvaluation
params = TradeParams(
    market_ticker="KXBTC-26FEB14-T50050",
    market_title="Bitcoin above 50050?",
    outcome_contract="YES",
    position_side="LONG",
    entry_price_cents=40,
    exit_target_cents=55,
    contracts=10,
    entry_fill_type="MAKER",
    exit_fill_type="MAKER",
    market_has_maker_fees=False,
    spread_cents=3,
    depth_at_price=20,
)

ev = evaluate_trade(params, cfg)
check("evaluate_trade returns object", ev is not None, True)
check("ev.gross_pnl > 0", ev.gross_pnl > 0, True)
check("ev.params.entry_price_cents == 40", ev.params.entry_price_cents, 40)
check("ev.contracts == 10", ev.contracts, 10)

# Order ticket formatting should not crash
ticket = format_order_ticket(ev)
check("format_order_ticket produces string", isinstance(ticket, str), True)
check("ticket contains 'ORDER TICKET'", "ORDER TICKET" in ticket, True)
check("ticket contains market ticker", "KXBTC" in ticket, True)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Orderbook parsing tests (runner.py helpers)
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== orderbook parsing ===")

from runner import _extract_ob_levels, _level_to_cents


# Test _level_to_cents with different formats

# SDK OrderbookLevel-style object (price in dollars)
class FakeLevel:
    def __init__(self, price, count):
        self.price = price
        self.count = count

check("level_to_cents(obj 0.65, 100)", _level_to_cents(FakeLevel(0.65, 100)), (65, 100))
check("level_to_cents(obj 0.05, 50)", _level_to_cents(FakeLevel(0.05, 50)), (5, 50))
check("level_to_cents(obj 0.99, 10)", _level_to_cents(FakeLevel(0.99, 10)), (99, 10))

# List format [price, qty] — as returned by raw JSON
check("level_to_cents([0.65, 100])", _level_to_cents([0.65, 100]), (65, 100))
check("level_to_cents([65, 100]) cents", _level_to_cents([65, 100]), (65, 100))

# Dict format
check("level_to_cents(dict dollars)", _level_to_cents({"price": 0.45, "count": 30}), (45, 30))
check("level_to_cents(dict cents)", _level_to_cents({"price": 45, "count": 30}), (45, 30))
check("level_to_cents(dict qty key)", _level_to_cents({"price": 0.45, "quantity": 30}), (45, 30))


# Test _extract_ob_levels with var_true/var_false (current SDK)
class FakeOB_VarTrue:
    def __init__(self):
        self.var_true = [FakeLevel(0.40, 10), FakeLevel(0.35, 20)]
        self.var_false = [FakeLevel(0.55, 15), FakeLevel(0.60, 25)]

yes_raw, no_raw = _extract_ob_levels(FakeOB_VarTrue())
check("extract var_true count", len(yes_raw), 2)
check("extract var_false count", len(no_raw), 2)
check("extract var_true[0].price", yes_raw[0].price, 0.40)


# Test _extract_ob_levels with yes/no (older SDK fallback)
class FakeOB_YesNo:
    def __init__(self):
        self.yes = [[40, 10], [35, 20]]
        self.no = [[55, 15], [60, 25]]

yes_raw2, no_raw2 = _extract_ob_levels(FakeOB_YesNo())
check("extract yes count", len(yes_raw2), 2)
check("extract no count", len(no_raw2), 2)


# Test _extract_ob_levels with to_dict() fallback
class FakeOB_Dict:
    def to_dict(self):
        return {
            "yes": [[40, 10], [35, 20]],
            "no": [[55, 15], [60, 25]],
        }

yes_raw3, no_raw3 = _extract_ob_levels(FakeOB_Dict())
check("extract to_dict yes count", len(yes_raw3), 2)
check("extract to_dict no count", len(no_raw3), 2)


# Test that an empty/None object doesn't crash
class FakeOB_Empty:
    pass

yes_empty, no_empty = _extract_ob_levels(FakeOB_Empty())
check("extract empty yes", len(yes_empty), 0)
check("extract empty no", len(no_empty), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 4. fee_aware_mm orderbook parsing
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== fee_aware_mm orderbook parsing ===")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategies"))
from fee_aware_mm import _extract_ob_levels as mm_extract, _level_to_cents as mm_level

check("mm _level_to_cents(obj)", mm_level(FakeLevel(0.65, 100)), (65, 100))
check("mm _level_to_cents(list)", mm_level([0.65, 100]), (65, 100))

mm_yes, mm_no = mm_extract(FakeOB_VarTrue())
check("mm extract var_true", len(mm_yes), 2)
check("mm extract var_false", len(mm_no), 2)


# ═══════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"  Results: {passed} passed, {failed} failed")
print(f"{'='*50}")

sys.exit(1 if failed > 0 else 0)
