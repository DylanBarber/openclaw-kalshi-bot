"""
trade_engine.py — Trade evaluation, acceptance gates, order-ticket formatting,
and risk-limit checks.  Implements the full trading doctrine.

Usage:
    from trade_engine import RiskConfig, TradeParams, evaluate_trade, format_order_ticket

All monetary values are USD floats.  All prices are integer cents (1-99).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from kalshi_math import (
    FillType,
    PositionSide,
    break_even_exit_cents,
    break_even_exit_cents_worst,
    capital_at_risk,
    compute_round_trip_fees,
    compute_worst_case_fees,
    fee_drag,
    gross_pnl_usd,
    max_contracts,
    net_pnl,
    position_sign,
    roc,
    slippage_usd,
)

# ── Configuration ─────────────────────────────────────────────────────────


@dataclass
class RiskConfig:
    """Section 22 — hard limits loaded from config.yaml."""

    max_capital_at_risk_per_market_usd: float = 50.0
    max_total_capital_at_risk_usd: float = 200.0
    max_daily_realized_loss_usd: float = 100.0
    max_concurrent_positions: int = 5
    max_order_rate_per_min: int = 30

    # Microstructure (Gate D)
    max_spread_cents: int = 8
    min_depth_contracts: int = 5

    # Slippage & safety (Section 11 / Gate C)
    slippage_buffer_cents: float = 1.0
    safety_margin_cents: int = 2

    # Gate B multiplier (net >= fees * multiplier)
    fee_margin_multiplier: float = 2.0

    # Take-profit / stop defaults
    default_take_profit_offset_cents: int = 6
    default_stop_offset_cents: int = 4
    default_max_hold_minutes: int = 120

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RiskConfig:
        risk = d.get("risk", {})
        kwargs: dict[str, Any] = {}
        for fld in cls.__dataclass_fields__:
            if fld in risk:
                kwargs[fld] = risk[fld]
        return cls(**kwargs)


# ── Trade parameters ──────────────────────────────────────────────────────


@dataclass
class TradeParams:
    """Inputs the caller must supply for a trade evaluation."""

    market_ticker: str
    market_title: str = ""
    outcome_contract: str = "YES"          # YES or NO
    position_side: PositionSide = "LONG"

    entry_price_cents: int = 0
    exit_target_cents: int = 0

    entry_fill_type: FillType = "MAKER"
    exit_fill_type: FillType = "MAKER"

    market_has_maker_fees: bool = False

    # Optional overrides (0 = auto-compute)
    contracts: int = 0
    stop_cents: int = 0
    take_profit_cents: int = 0
    max_hold_minutes: int = 0

    # Live orderbook snapshot for Gate D
    spread_cents: int = 0
    depth_at_price: int = 0


# ── Evaluation result ─────────────────────────────────────────────────────


@dataclass
class TradeEvaluation:
    """All computed metrics for a proposed trade."""

    params: TradeParams
    contracts: int = 0

    # Fees
    fee_entry_usd: float = 0.0
    fee_exit_usd: float = 0.0
    fee_total_usd: float = 0.0
    fee_entry_worst: float = 0.0
    fee_exit_worst: float = 0.0
    fee_total_worst_usd: float = 0.0

    # P&L
    gross_pnl: float = 0.0
    slippage: float = 0.0
    net_pnl_planned: float = 0.0
    net_pnl_worst: float = 0.0

    # Capital
    max_loss_usd: float = 0.0
    max_gain_usd: float = 0.0
    capital_at_risk_usd: float = 0.0

    # ROI
    return_on_capital: float = 0.0
    fee_drag_ratio: float = 0.0

    # Break-even
    break_even_planned: int | None = None
    break_even_worst: int | None = None

    # Stop / TP
    stop_cents: int = 0
    take_profit_cents: int = 0
    max_hold_minutes: int = 0
    stop_net_usd: float = 0.0

    # Gates
    gates: dict[str, bool] = field(default_factory=dict)
    gate_reasons: list[str] = field(default_factory=list)
    all_gates_pass: bool = False


# ── Core evaluation ───────────────────────────────────────────────────────


def evaluate_trade(params: TradeParams, cfg: RiskConfig) -> TradeEvaluation:
    """Run the full doctrine evaluation on a proposed trade."""
    ev = TradeEvaluation(params=params)

    side = params.position_side
    entry = params.entry_price_cents
    exit_t = params.exit_target_cents
    ticker = params.market_ticker
    maker_fees = params.market_has_maker_fees

    # ── Sizing (Section 23) ───────────────────────────────────────────
    if params.contracts > 0:
        C = params.contracts
    else:
        C = max_contracts(
            cfg.max_capital_at_risk_per_market_usd,
            entry, side, ticker, maker_fees,
        )
        C = max(C, 1)
    ev.contracts = C

    # ── Fees (Section 7 + 8) ──────────────────────────────────────────
    ev.fee_entry_usd, ev.fee_exit_usd, ev.fee_total_usd = compute_round_trip_fees(
        C, entry, exit_t, ticker, maker_fees,
        params.entry_fill_type, params.exit_fill_type,
    )
    ev.fee_entry_worst, ev.fee_exit_worst, ev.fee_total_worst_usd = compute_worst_case_fees(
        C, entry, exit_t, ticker, maker_fees,
    )

    # ── P&L (Section 10-13) ───────────────────────────────────────────
    ev.gross_pnl = gross_pnl_usd(side, C, entry, exit_t)
    ev.slippage = slippage_usd(C, cfg.slippage_buffer_cents)
    ev.net_pnl_planned = net_pnl(ev.gross_pnl, ev.fee_total_usd, ev.slippage)
    ev.net_pnl_worst = net_pnl(ev.gross_pnl, ev.fee_total_worst_usd, ev.slippage)

    # ── Capital at risk (Section 14) ──────────────────────────────────
    ev.max_loss_usd, ev.max_gain_usd, ev.capital_at_risk_usd = capital_at_risk(
        C, entry, side, ev.fee_total_worst_usd,
    )

    # ── ROI (Section 15) ──────────────────────────────────────────────
    ev.return_on_capital = roc(ev.net_pnl_planned, ev.capital_at_risk_usd)
    ev.fee_drag_ratio = fee_drag(ev.fee_total_usd, abs(ev.gross_pnl))

    # ── Break-even (Section 16) ───────────────────────────────────────
    ev.break_even_planned = break_even_exit_cents(
        entry, side, C, ticker, maker_fees,
        params.entry_fill_type, params.exit_fill_type,
        cfg.slippage_buffer_cents,
    )
    ev.break_even_worst = break_even_exit_cents_worst(
        entry, side, C, ticker, maker_fees,
        cfg.slippage_buffer_cents,
    )

    # ── Stop / TP (Section 18) ────────────────────────────────────────
    psign = position_sign(side)

    if params.take_profit_cents > 0:
        ev.take_profit_cents = params.take_profit_cents
    else:
        ev.take_profit_cents = exit_t  # use exit target as TP

    if params.stop_cents > 0:
        ev.stop_cents = params.stop_cents
    else:
        ev.stop_cents = max(1, min(99, entry - psign * cfg.default_stop_offset_cents))

    ev.max_hold_minutes = params.max_hold_minutes or cfg.default_max_hold_minutes

    # Stop net P&L
    stop_gross = gross_pnl_usd(side, C, entry, ev.stop_cents)
    _, _, stop_fees = compute_worst_case_fees(C, entry, ev.stop_cents, ticker, maker_fees)
    ev.stop_net_usd = net_pnl(stop_gross, stop_fees, ev.slippage)

    # ── Gates (Section 17) ────────────────────────────────────────────
    _run_gates(ev, cfg)

    return ev


# ── Gate checks ───────────────────────────────────────────────────────────


def _run_gates(ev: TradeEvaluation, cfg: RiskConfig) -> None:
    """Evaluate all four trade acceptance gates."""
    gates = {}
    reasons: list[str] = []

    # GATE A — worst-case survivability
    gate_a = ev.net_pnl_worst >= 0
    gates["A_worst_case_survivability"] = gate_a
    if not gate_a:
        reasons.append(
            f"GATE A FAIL: worst-case net P&L = ${ev.net_pnl_worst:.4f} < $0"
        )

    # GATE B — margin over fees
    threshold = ev.fee_total_usd * cfg.fee_margin_multiplier
    gate_b = ev.net_pnl_planned >= threshold
    gates["B_margin_over_fees"] = gate_b
    if not gate_b:
        reasons.append(
            f"GATE B FAIL: planned net ${ev.net_pnl_planned:.4f} < "
            f"{cfg.fee_margin_multiplier}x fees ${threshold:.4f}"
        )

    # GATE C — move threshold
    psign = position_sign(ev.params.position_side)
    expected_move = psign * (ev.params.exit_target_cents - ev.params.entry_price_cents)

    if ev.break_even_worst is not None:
        be_move_worst = psign * (ev.break_even_worst - ev.params.entry_price_cents)
    else:
        be_move_worst = 99  # impossible to break even → force fail

    required_move = be_move_worst + cfg.safety_margin_cents
    gate_c = expected_move >= required_move
    gates["C_move_threshold"] = gate_c
    if not gate_c:
        reasons.append(
            f"GATE C FAIL: expected move {expected_move}c < "
            f"required {required_move}c (BE worst {be_move_worst}c + "
            f"safety {cfg.safety_margin_cents}c)"
        )

    # GATE D — microstructure sanity
    spread_ok = ev.params.spread_cents <= cfg.max_spread_cents
    depth_ok = ev.params.depth_at_price >= cfg.min_depth_contracts
    gate_d = spread_ok and depth_ok
    gates["D_microstructure"] = gate_d
    if not spread_ok:
        reasons.append(
            f"GATE D FAIL: spread {ev.params.spread_cents}c > "
            f"max {cfg.max_spread_cents}c"
        )
    if not depth_ok:
        reasons.append(
            f"GATE D FAIL: depth {ev.params.depth_at_price} contracts < "
            f"min {cfg.min_depth_contracts}"
        )

    ev.gates = gates
    ev.gate_reasons = reasons
    ev.all_gates_pass = all(gates.values())


# ── Portfolio-level risk checks (Section 22) ──────────────────────────────


@dataclass
class PortfolioState:
    """Snapshot of current portfolio for risk checks."""

    total_capital_at_risk_usd: float = 0.0
    daily_realized_loss_usd: float = 0.0
    open_position_count: int = 0
    orders_last_minute: int = 0


def check_risk_limits(
    ev: TradeEvaluation,
    portfolio: PortfolioState,
    cfg: RiskConfig,
) -> tuple[bool, list[str]]:
    """Return (allowed, list_of_reasons_if_blocked)."""
    reasons: list[str] = []

    if ev.capital_at_risk_usd > cfg.max_capital_at_risk_per_market_usd:
        reasons.append(
            f"Position capital ${ev.capital_at_risk_usd:.2f} > "
            f"per-market limit ${cfg.max_capital_at_risk_per_market_usd:.2f}"
        )

    new_total = portfolio.total_capital_at_risk_usd + ev.capital_at_risk_usd
    if new_total > cfg.max_total_capital_at_risk_usd:
        reasons.append(
            f"Total capital at risk ${new_total:.2f} > "
            f"limit ${cfg.max_total_capital_at_risk_usd:.2f}"
        )

    if portfolio.daily_realized_loss_usd >= cfg.max_daily_realized_loss_usd:
        reasons.append(
            f"Daily loss ${portfolio.daily_realized_loss_usd:.2f} >= "
            f"halt threshold ${cfg.max_daily_realized_loss_usd:.2f}"
        )

    if portfolio.open_position_count >= cfg.max_concurrent_positions:
        reasons.append(
            f"Open positions {portfolio.open_position_count} >= "
            f"max {cfg.max_concurrent_positions}"
        )

    if portfolio.orders_last_minute >= cfg.max_order_rate_per_min:
        reasons.append(
            f"Order rate {portfolio.orders_last_minute}/min >= "
            f"max {cfg.max_order_rate_per_min}/min"
        )

    return len(reasons) == 0, reasons


# ── Order ticket formatting (Section 24) ──────────────────────────────────


def format_order_ticket(ev: TradeEvaluation) -> str:
    """Produce the canonical order ticket string."""
    p = ev.params
    lines = [
        "",
        "=" * 60,
        "  ORDER TICKET",
        "=" * 60,
        f"  Market:       {p.market_ticker} — {p.market_title}",
        f"  Contract:     {p.outcome_contract}",
        f"  Side:         {p.position_side}",
        f"  Entry:        {p.entry_price_cents}¢  (fill plan: {p.entry_fill_type})",
        f"  Exit target:  {p.exit_target_cents}¢  (fill plan: {p.exit_fill_type})",
        f"  Stop:         {ev.stop_cents}¢  |  Time-stop: {ev.max_hold_minutes} min",
        f"  Size:         {ev.contracts} contracts",
        f"  Fees planned: ${ev.fee_total_usd:.4f}  |  Fees worst: ${ev.fee_total_worst_usd:.4f}",
        f"  Slippage:     {ev.params.spread_cents}¢/contract => ${ev.slippage:.4f}",
        f"  Net P&L @ target (planned): ${ev.net_pnl_planned:.4f}",
        f"  Net P&L @ target (worst):   ${ev.net_pnl_worst:.4f}",
        f"  Break-even (planned): {ev.break_even_planned or 'N/A'}¢",
        f"  Break-even (worst):   {ev.break_even_worst or 'N/A'}¢",
        f"  Capital at risk:      ${ev.capital_at_risk_usd:.4f}",
        f"  ROC: {ev.return_on_capital:+.2%}  |  Fee drag: {ev.fee_drag_ratio:.2%}",
        f"  Stop net P&L:         ${ev.stop_net_usd:.4f}",
        "-" * 60,
    ]

    # Gate summary
    for name, passed in ev.gates.items():
        status = "PASS" if passed else "FAIL"
        lines.append(f"  Gate {name}: {status}")

    if ev.gate_reasons:
        lines.append("")
        for r in ev.gate_reasons:
            lines.append(f"  !! {r}")

    verdict = "ALLOWED" if ev.all_gates_pass else "BLOCKED"
    lines.append("")
    lines.append(f"  >>> VERDICT: {verdict}")
    lines.append("=" * 60)
    lines.append("")

    return "\n".join(lines)


# ── Execution helpers ─────────────────────────────────────────────────────


def generate_client_order_id() -> str:
    """Idempotent client order ID (Section 25)."""
    return f"kb-{uuid.uuid4().hex[:16]}"


def place_limit_order(
    client: Any,
    ticker: str,
    side_sdk: str,       # "yes" or "no"
    action: str,         # "buy" or "sell"
    count: int,
    price_cents: int,
    post_only: bool = True,
) -> Any:
    """
    Section 19 — place a limit order with post_only by default (maker intent).
    Returns the order response or raises.
    """
    from kalshi_python.models.create_order_request import CreateOrderRequest

    coid = generate_client_order_id()

    price_kwargs: dict[str, int] = {}
    if side_sdk == "yes":
        price_kwargs["yes_price"] = price_cents
    else:
        price_kwargs["no_price"] = price_cents

    req = CreateOrderRequest(
        ticker=ticker,
        side=side_sdk,
        action=action,
        count=count,
        type="limit",
        client_order_id=coid,
        post_only=post_only,
        **price_kwargs,
    )
    return client.create_order(**req.to_dict())


def wait_for_fill(
    client: Any,
    order_id: str,
    timeout_s: float = 30.0,
    poll_s: float = 1.0,
) -> Any:
    """Poll order status until filled, canceled, or timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = client.get_order(order_id=order_id)
        order = resp.order if hasattr(resp, "order") else resp
        status = getattr(order, "status", "")
        if status in ("executed", "canceled"):
            return order
        remaining = getattr(order, "remaining_count", None)
        if remaining is not None and remaining == 0:
            return order
        time.sleep(poll_s)
    return None  # timed out
