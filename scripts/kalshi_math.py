"""
kalshi_math.py — Pure fee / P&L / break-even formulas for Kalshi prediction markets.

All prices are in INTEGER CENTS (1-99).  All dollar amounts are floats.
Implements the canonical formulas from the trading doctrine.
"""

from __future__ import annotations

import math
from typing import Literal

# ── Fee coefficients (Section 3) ──────────────────────────────────────────

K_TAKER_GENERAL = 0.07
K_TAKER_INDEX = 0.035
K_MAKER = 0.0175

FillType = Literal["TAKER", "MAKER"]
PositionSide = Literal["LONG", "SHORT"]

# ── Core helpers ──────────────────────────────────────────────────────────


def round_up_cent(x_dollars: float) -> float:
    """Section 2 — round up to the next cent."""
    return math.ceil(x_dollars * 100) / 100.0


def is_index_market(ticker: str) -> bool:
    """True for S&P 500 / Nasdaq-100 family tickers."""
    t = ticker.upper()
    return t.startswith("INX") or t.startswith("NASDAQ100")


def taker_coeff(market_ticker: str) -> float:
    """Section 6 — select the correct taker fee coefficient."""
    return K_TAKER_INDEX if is_index_market(market_ticker) else K_TAKER_GENERAL


# ── Fee calculation ───────────────────────────────────────────────────────


def fee_usd(C: int, P: float, k: float) -> float:
    """Section 4 — fee for C contracts at probability P with coefficient k."""
    if k == 0 or C == 0:
        return 0.0
    return round_up_cent(k * C * P * (1.0 - P))


def effective_k(
    fill_type: FillType,
    market_ticker: str,
    market_has_maker_fees: bool,
) -> float:
    """Section 5 — resolve fee coefficient for a given fill type."""
    if fill_type == "TAKER":
        return taker_coeff(market_ticker)
    else:  # MAKER
        return K_MAKER if market_has_maker_fees else 0.0


def compute_leg_fee(
    C: int,
    price_cents: int,
    fill_type: FillType,
    market_ticker: str,
    market_has_maker_fees: bool,
) -> float:
    """Fee for one leg (entry or exit) of a trade."""
    P = price_cents / 100.0
    k = effective_k(fill_type, market_ticker, market_has_maker_fees)
    return fee_usd(C, P, k)


def compute_round_trip_fees(
    C: int,
    entry_price_cents: int,
    exit_price_cents: int,
    market_ticker: str,
    market_has_maker_fees: bool,
    entry_fill_type: FillType = "TAKER",
    exit_fill_type: FillType = "TAKER",
) -> tuple[float, float, float]:
    """
    Section 7 — compute entry, exit, and total fees for a round trip.
    Returns (fee_entry_usd, fee_exit_usd, fee_total_usd).
    """
    fee_entry = compute_leg_fee(
        C, entry_price_cents, entry_fill_type, market_ticker, market_has_maker_fees
    )
    fee_exit = compute_leg_fee(
        C, exit_price_cents, exit_fill_type, market_ticker, market_has_maker_fees
    )
    return fee_entry, fee_exit, fee_entry + fee_exit


def compute_worst_case_fees(
    C: int,
    entry_price_cents: int,
    exit_price_cents: int,
    market_ticker: str,
    market_has_maker_fees: bool,
) -> tuple[float, float, float]:
    """Section 8 — worst-case fees assuming taker/taker on both legs."""
    return compute_round_trip_fees(
        C, entry_price_cents, exit_price_cents,
        market_ticker, market_has_maker_fees,
        entry_fill_type="TAKER", exit_fill_type="TAKER",
    )


# ── P&L formulas ─────────────────────────────────────────────────────────


def position_sign(side: PositionSide) -> int:
    """Section 9."""
    return 1 if side == "LONG" else -1


def gross_pnl_usd(
    side: PositionSide,
    C: int,
    entry_cents: int,
    exit_cents: int,
) -> float:
    """Section 10 — gross P&L for a round trip."""
    return position_sign(side) * C * ((exit_cents - entry_cents) / 100.0)


def slippage_usd(C: int, slippage_buffer_cents: float) -> float:
    """Section 11."""
    return C * (slippage_buffer_cents / 100.0)


def net_pnl(
    gross: float,
    fee_total: float,
    slippage: float,
) -> float:
    """Section 12 / 13."""
    return gross - fee_total - slippage


# ── Capital at risk ───────────────────────────────────────────────────────


def capital_at_risk(
    C: int,
    entry_cents: int,
    side: PositionSide,
    fee_worst_total: float,
) -> tuple[float, float, float]:
    """
    Section 14 — settlement-bound capital at risk.
    Returns (max_loss_usd, max_gain_usd, capital_at_risk_usd).
    """
    P = entry_cents / 100.0
    if side == "LONG":
        max_loss = C * P
        max_gain = C * (1.0 - P)
    else:
        max_loss = C * (1.0 - P)
        max_gain = C * P
    return max_loss, max_gain, max_loss + fee_worst_total


# ── ROI metrics ───────────────────────────────────────────────────────────


def roc(net_pnl_usd: float, capital_at_risk_usd: float) -> float:
    """Section 15 — return on capital at risk."""
    return net_pnl_usd / max(capital_at_risk_usd, 0.01)


def fee_drag(fee_total: float, gross_abs: float) -> float:
    """Section 15 — fee drag ratio."""
    return fee_total / max(gross_abs, 0.01)


# ── Break-even search ────────────────────────────────────────────────────


def break_even_exit_cents(
    entry_price_cents: int,
    side: PositionSide,
    C: int,
    market_ticker: str,
    market_has_maker_fees: bool,
    entry_fill_type: FillType,
    exit_fill_type: FillType,
    slippage_buffer_cents: float,
) -> int | None:
    """
    Section 16 — find the minimum integer exit price (in cents) where
    net P&L >= 0, searching in the profitable direction.
    Returns None if no break-even exists within 1..99.
    """
    if side == "LONG":
        candidates = range(entry_price_cents, 100)  # entry .. 99
    else:
        candidates = range(entry_price_cents, 0, -1)  # entry .. 1

    for exit_cents in candidates:
        _, _, ft = compute_round_trip_fees(
            C, entry_price_cents, exit_cents,
            market_ticker, market_has_maker_fees,
            entry_fill_type, exit_fill_type,
        )
        gross = gross_pnl_usd(side, C, entry_price_cents, exit_cents)
        slip = slippage_usd(C, slippage_buffer_cents)
        if net_pnl(gross, ft, slip) >= 0:
            return exit_cents

    return None


def break_even_exit_cents_worst(
    entry_price_cents: int,
    side: PositionSide,
    C: int,
    market_ticker: str,
    market_has_maker_fees: bool,
    slippage_buffer_cents: float,
) -> int | None:
    """Section 16 — break-even under worst-case (taker/taker) fees."""
    return break_even_exit_cents(
        entry_price_cents, side, C,
        market_ticker, market_has_maker_fees,
        entry_fill_type="TAKER",
        exit_fill_type="TAKER",
        slippage_buffer_cents=slippage_buffer_cents,
    )


# ── Position sizing ──────────────────────────────────────────────────────


def max_contracts(
    max_capital_usd: float,
    entry_cents: int,
    side: PositionSide,
    market_ticker: str,
    market_has_maker_fees: bool,
) -> int:
    """
    Section 23 — maximum contracts given a capital budget.
    Uses worst-case taker fee estimate.  Returns at least 0.
    """
    P = entry_cents / 100.0
    loss_per_contract = P if side == "LONG" else (1.0 - P)

    # Approximate worst-case fee per contract (self-referential, so we
    # iterate once with C=1 to get a per-contract fee estimate).
    k = taker_coeff(market_ticker)
    fee_per_contract = 2 * round_up_cent(k * 1 * P * (1.0 - P))

    denom = loss_per_contract + fee_per_contract
    if denom <= 0:
        return 0
    return max(0, math.floor(max_capital_usd / denom))
