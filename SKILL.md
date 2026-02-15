---
name: kalshi-bot
description: Trade Kalshi prediction markets from the CLI using the official kalshi-python SDK with a full fee-aware trading doctrine. Use when the user wants to search markets, view orderbooks, place buy/sell orders, cancel orders, check positions/balance, evaluate trades with fee/gate analysis, or run automated trading strategies on Kalshi. Triggers on any mention of Kalshi, prediction markets, event contracts, binary options trading, or trading strategy evaluation.
metadata: {"openclaw":{"homepage":"https://kalshi.com","requires":{"anyBins":["python3","python"],"env":["KALSHI_API_KEY_ID"]},"primaryEnv":"KALSHI_API_KEY_ID"}}
---

# Kalshi Bot

CLI tool and trading engine for Kalshi prediction markets. Implements a complete fee-aware trading doctrine with acceptance gates, risk management, and position sizing.

## Setup

1. Create venv and install dependencies:

```bash
cd {baseDir}
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r scripts/requirements.txt
```

2. Copy `{baseDir}/scripts/config.example.yaml` to `{baseDir}/scripts/config.yaml` and fill in credentials:
   - `api_key_id` — from https://kalshi.com/account/api-keys
   - `private_key_path` — path to the RSA PEM file
   - Tune the `risk:` section for your capital/tolerance

## Architecture

```
scripts/
├── runner.py              CLI entry point (all commands)
├── kalshi_math.py         Pure fee/PnL/break-even formulas
├── trade_engine.py        Trade evaluation, gates, order tickets, risk checks
├── config.example.yaml    Template config with risk parameters
├── requirements.txt       Python dependencies
└── strategies/
    ├── fee_aware_mm.py    Fee-aware market-making strategy
    └── example_spread.py  Simple spread watcher
```

### Module roles

- **`kalshi_math.py`** — Stateless functions: `fee_usd()`, `gross_pnl_usd()`, `break_even_exit_cents()`, `max_contracts()`, etc. No SDK dependency.
- **`trade_engine.py`** — `evaluate_trade(TradeParams, RiskConfig) -> TradeEvaluation`, gate checks, `format_order_ticket()`, `place_limit_order()`, `check_risk_limits()`.
- **`strategies/*.py`** — Each exposes `run(client, args)`. Uses the engine for all evaluations.

## Commands

All via `python {baseDir}/scripts/runner.py <command>` (run from the skill directory or use the full path).

### Market Data

```bash
cd {baseDir} && .venv/bin/python scripts/runner.py markets search "bitcoin"
cd {baseDir} && .venv/bin/python scripts/runner.py markets get KXBTC-26FEB14-T50050
cd {baseDir} && .venv/bin/python scripts/runner.py orderbook KXBTC-26FEB14-T50050 --depth 5
```

Note: valid `--status` query filter values are `unopened`, `open`, `paused`, `closed`, `settled`. Do NOT use response-level statuses like `active` or `determined` as filter values. Omit `--status` to return all markets.

### Trading

```bash
python scripts/runner.py buy KXBTC-26FEB14-T50050 10 65
python scripts/runner.py sell KXBTC-26FEB14-T50050 5 40 --side no
python scripts/runner.py cancel <order_id>
```

### Portfolio

```bash
python scripts/runner.py balance
python scripts/runner.py orders
python scripts/runner.py positions
python scripts/runner.py fills --ticker KXBTC-26FEB14-T50050
```

### Fee-Aware Strategy

```bash
# Dry-run evaluation (no orders placed)
python scripts/runner.py run-strategy fee_aware_mm --ticker KXBTC-26FEB14-T50050 -- --dry-run

# Live execution (LONG YES, auto-sized)
python scripts/runner.py run-strategy fee_aware_mm --ticker KXBTC-26FEB14-T50050

# SHORT NO with explicit entry/exit
python scripts/runner.py run-strategy fee_aware_mm --ticker KXBTC-26FEB14-T50050 -- --side SHORT --contract NO --entry 55 --exit 45

# Continuous monitoring
python scripts/runner.py run-strategy fee_aware_mm --ticker KXBTC-26FEB14-T50050 -- --loop --interval 15
```

## Trading Doctrine

Every trade is evaluated through four mandatory gates before execution:

| Gate | Rule |
|---|---|
| A — Survivability | Worst-case net P&L (taker/taker + slippage) >= 0 |
| B — Fee margin | Net profit >= 2x planned fees |
| C — Move threshold | Expected move >= worst-case break-even move + safety margin |
| D — Microstructure | Spread <= max, depth >= min |

After gates pass, portfolio-level risk limits are checked (capital, daily loss, position count, order rate). Only then is an order placed.

Execution prefers LIMIT + POST_ONLY (maker intent). After fill, take-profit and stop exits are placed. Time-stop triggers exit if no favorable movement.

For the complete formula reference, see [references/trading_doctrine.md](references/trading_doctrine.md).

## Strategy Authoring

To add a new strategy:

1. Create `scripts/strategies/<name>.py`
2. `import` from `kalshi_math` and `trade_engine` (add `scripts/` to `sys.path`)
3. Build a `TradeParams`, call `evaluate_trade()`, check `ev.all_gates_pass`
4. Use `format_order_ticket()` for output, `place_limit_order()` for execution
5. Run: `python scripts/runner.py run-strategy <name> --ticker TICKER`

## API Reference

For SDK method signatures and response models, see [references/kalshi_api.md](references/kalshi_api.md).

## Key Concepts

- **Prices** are in cents (1-99). YES at 65c ≈ 65% implied probability.
- **Fees** use round-up-to-cent: `ceil(k * C * P * (1-P) * 100) / 100`.
- **Taker** = 7% general, 3.5% index (INX/NASDAQ100). **Maker** = 1.75% or 0.
- **Break-even** is computed by searching cent-by-cent in the profitable direction.
- **Capital at risk** = max settlement loss + worst-case fees.
