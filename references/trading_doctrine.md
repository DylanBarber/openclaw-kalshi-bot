# Trading Doctrine — Canonical Formulas & Rules

Complete reference for fee calculation, P&L, gates, risk management, and execution doctrine.

## Table of Contents

1. [Unit Conversions & Rounding](#1-unit-conversions)
2. [Fee Coefficients & Calculation](#2-fees)
3. [P&L Formulas](#3-pnl)
4. [Capital at Risk & ROI](#4-capital)
5. [Break-Even Search](#5-break-even)
6. [Trade Acceptance Gates](#6-gates)
7. [Position Management (TP/Stop/Time-Stop)](#7-exits)
8. [Execution Doctrine](#8-execution)
9. [Risk Management Hard Limits](#9-risk)
10. [Sizing](#10-sizing)
11. [Order Ticket Format](#11-ticket)

---

## 1. Unit Conversions

- `price_cents` ∈ {1..99} — Kalshi quotes in integer cents
- `P = price_cents / 100.0` — implied probability proxy
- `C` = contracts (positive integer)
- $1 payout per contract at settlement if outcome occurs
- `round_up_cent(x) = ceil(x * 100) / 100`

## 2. Fees

### Coefficients

| Type | Symbol | Value |
|---|---|---|
| Taker (general) | `k_taker_general` | 0.07 |
| Taker (S&P/Nasdaq) | `k_taker_index` | 0.035 |
| Maker (if market charges) | `k_maker` | 0.0175 |

Index markets: tickers starting with `INX` or `NASDAQ100`.

### Formula

```
fee_usd(C, P, k) = round_up_cent(k * C * P * (1 - P))
```

### Fill-type rules

- Immediate execution against resting liquidity = **TAKER** → use `k_taker_*`
- Resting order later matched:
  - `market_has_maker_fees == true` → use `k_maker`
  - else → fee = 0

### Round-trip fees

```
fee_total = fee_usd(C, P_entry, k_entry) + fee_usd(C, P_exit, k_exit)
```

### Worst-case fees

Always assume TAKER/TAKER for both legs.

## 3. P&L

```
position_sign = +1 if LONG, -1 if SHORT

gross_pnl = position_sign * C * (exit_cents - entry_cents) / 100

slippage = C * slippage_buffer_cents / 100

net_pnl = gross_pnl - fee_total - slippage
net_pnl_worst = gross_pnl - fee_total_worst - slippage
```

## 4. Capital at Risk

```
If LONG:  max_loss = C * P_entry,        max_gain = C * (1 - P_entry)
If SHORT: max_loss = C * (1 - P_entry),  max_gain = C * P_entry

capital_at_risk = max_loss + fee_total_worst
```

ROI metrics:
- `roc = net_pnl / max(capital_at_risk, 0.01)`
- `fee_drag = fee_total / max(|gross_pnl|, 0.01)`

## 5. Break-Even

Search from entry in the profitable direction (1 cent at a time) for the first exit price where `net_pnl >= 0`. Also compute worst-case break-even under TAKER/TAKER.

Returns `None` if no break-even achievable within 1-99.

## 6. Trade Acceptance Gates

**ALL must pass. Do not bypass.**

| Gate | Condition |
|---|---|
| A — Worst-case survivability | `net_pnl_worst >= 0` |
| B — Margin over fees | `net_pnl_planned >= fee_total * 2` |
| C — Move threshold | `expected_move >= break_even_worst_move + safety_margin` |
| D — Microstructure | `spread <= max_spread` AND `depth >= min_depth` |

## 7. Exit Management

Every trade must define:
- **Take-profit**: exit where `net_pnl` satisfies Gate B comfortably
- **Stop**: max acceptable loss exit price
- **Time-stop**: `max_hold_minutes` — if no favorable move beyond break-even, exit/reduce

Stop net P&L:
```
stop_gross = position_sign * C * (stop_cents - entry_cents) / 100
stop_net = stop_gross - fees(entry + exit@stop) - slippage
```

## 8. Execution Doctrine

- **Prefer** `LIMIT + POST_ONLY` (maker intent) for entries and exits
- Allow taker only if Gates A+B still pass under taker/taker worst case
- **Partial fills**: immediate portion = TAKER fees, resting portion = MAKER fees (or 0)
- After fill: immediately place TP + stop exits
- If book degrades (spread widens, depth vanishes, price reverses): exit
- Never "hold and hope"

## 9. Risk Hard Limits

| Parameter | Default |
|---|---|
| `max_capital_at_risk_per_market_usd` | 50 |
| `max_total_capital_at_risk_usd` | 200 |
| `max_daily_realized_loss_usd` | 100 |
| `max_concurrent_positions` | 5 |
| `max_order_rate_per_min` | 30 |

## 10. Sizing

```
C <= floor(max_capital / (max_loss_per_contract + fee_per_contract_worst))
```

## 11. Order Ticket Format

Every proposed or executed trade outputs:

```
Market / Contract / Side / Entry / Exit target / Stop / Time-stop
Size / Fees planned & worst / Slippage / Net P&L / Break-even
Gate results / Verdict
```

See `trade_engine.format_order_ticket()` for the canonical implementation.
