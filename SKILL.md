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
├── watcher.py             Position price watcher daemon
├── config.example.yaml    Template config with risk parameters
├── requirements.txt       Python dependencies
└── strategies/
    ├── fee_aware_mm.py    Fee-aware market-making strategy (auto-starts watcher on fill)
    ├── example_spread.py  Simple spread watcher
    └── crypto_sentinel.py External-price-triggered crypto position manager
ui/
├── api_server.py          Flask REST API for the dashboard
└── static/
    ├── index.html         Dashboard page
    ├── app.js             Client-side logic + charts
    └── style.css          Dark terminal theme
```

### Module roles

- **`kalshi_math.py`** — Stateless functions: `fee_usd()`, `gross_pnl_usd()`, `break_even_exit_cents()`, `max_contracts()`, etc. No SDK dependency.
- **`trade_engine.py`** — `evaluate_trade(TradeParams, RiskConfig) -> TradeEvaluation`, gate checks, `format_order_ticket()`, `place_limit_order()`, `check_risk_limits()`.
- **`strategies/*.py`** — Each exposes `run(client, args)`. Uses the engine for all evaluations.

## Commands

All via `python {baseDir}/scripts/runner.py <command>` (run from the skill directory or use the full path).

### Market Discovery (events-based)

The `/markets` listing only returns esports combos. Real markets (~2,900+ active across Politics, Economics, Sports, Financials, etc.) are discovered through the **events** endpoint. The `events` and `markets search` commands use raw HTTP — no SDK auth required.

```bash
# Browse all event categories
cd {baseDir} && .venv/bin/python scripts/runner.py events

# Search events by text
cd {baseDir} && .venv/bin/python scripts/runner.py events "fed"

# Filter by category
cd {baseDir} && .venv/bin/python scripts/runner.py events --category Economics

# Search markets across all events
cd {baseDir} && .venv/bin/python scripts/runner.py markets search "deel ipo"

# Search within a category
cd {baseDir} && .venv/bin/python scripts/runner.py markets search "trump" --category Politics

# List all markets in a specific event
cd {baseDir} && .venv/bin/python scripts/runner.py markets search --event KXDEELRIP-40

# Get full detail on a specific market
cd {baseDir} && .venv/bin/python scripts/runner.py markets get KXDEELRIP-40-DEEL

# Inspect the orderbook (L2 depth)
cd {baseDir} && .venv/bin/python scripts/runner.py orderbook KXDEELRIP-40-DEEL --depth 10
```

**Available categories:** Politics, Economics, Elections, Sports, Entertainment, Financials, Companies, Social, Climate and Weather, World, Science and Technology, Health, Transportation.

**Crypto series discovery:** Use the `series` command to find 15-minute, hourly, daily, weekly, and monthly crypto markets (212+ series).

Valid `--status` query filter values: `unopened`, `open`, `paused`, `closed`, `settled`. Do NOT use response-level statuses like `active` or `determined` as filter values. Omit `--status` to return all markets.

### Series Discovery (Crypto, Daily, etc.)

```bash
# List all crypto series (212+ series across 15min, hourly, daily, weekly, monthly)
python scripts/runner.py series --category Crypto

# List only 15-minute crypto series
python scripts/runner.py series --category Crypto --frequency fifteen_min

# Detail for a specific series + its upcoming events
python scripts/runner.py series KXBTC15M

# Show events WITH individual market tickers and prices
python scripts/runner.py series KXBTC15M --events

# Hourly BTC brackets
python scripts/runner.py series KXBTC --events
```

**15-Minute series:** `KXBTC15M`, `KXETH15M`, `KXSOL15M`, `KXXRP15M`

**Ticker format:** `KXBTC15M-{YYMONDDHHMI}-{MI}` (e.g., `KXBTC15M-26FEB170000-00`)

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

### Position Watcher

```bash
# Watch a position (polls orderbook, tracks price history, alerts on stop/TP)
python scripts/runner.py watch KXBTC-26FEB15-B68375 --entry 40 --side LONG --contracts 10 --stop 36 --tp 46

# List active watchers
python scripts/runner.py watch --list

# Remove a watcher
python scripts/runner.py watch --remove KXBTC-26FEB15-B68375
```

The `fee_aware_mm` strategy auto-starts a watcher after a successful fill.

### Trading Dashboard (Web UI)

```bash
python ui/api_server.py          # starts at http://localhost:5123
python ui/api_server.py --port 8080  # custom port
```

Shows balance, active watchers with live P&L, price charts, orderbook depth, and positions.

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

### Crypto Sentinel Strategy

Two modes: (1) trade 15-minute crypto up/down markets, (2) monitor prices with stop/TP triggers.

**Mode 1: 15-Minute Trading (`--mode 15min`)**

Trades binary "BTC up or down in 15 minutes?" markets using external price momentum:

```bash
# Scan available 15-minute series
python scripts/runner.py run-strategy crypto_sentinel --ticker BTC -- --scan-series

# Dry-run: find active market, determine direction, show order
python scripts/runner.py run-strategy crypto_sentinel --ticker BTC -- --mode 15min --dry-run

# Trade 10 contracts on the current BTC 15-minute market
python scripts/runner.py run-strategy crypto_sentinel --ticker BTC -- --mode 15min --contracts 10

# ETH 15-minute markets
python scripts/runner.py run-strategy crypto_sentinel --ticker ETH -- --mode 15min --dry-run
```

**Mode 2: Price Watch with Stop/TP (`--mode watch`, default)**

Uses external spot price as trigger signal for managing existing positions:

```bash
# Watch BTC with stop-loss and take-profit
python scripts/runner.py run-strategy crypto_sentinel --ticker BTC -- --stop 65000 --tp 72000 --dry-run

# Scan for crypto-related events
python scripts/runner.py run-strategy crypto_sentinel --ticker BTC -- --scan-events

# Use Coinbase as price source
python scripts/runner.py run-strategy crypto_sentinel --ticker BTC -- --stop 65000 --tp 72000 --price-source coinbase
```

**Supported assets:** BTC, ETH, SOL, XRP, DOGE, ADA, AVAX, MATIC, DOT, LINK

**Limitations:**
- 15-minute markets are only `active` during Kalshi trading hours
- Direction detection is momentum-based (short price sample), not predictive
- Exit orders are limit orders; fills not guaranteed on thin books
- Price sources: Binance US (default, best rate limits), Coinbase, CoinGecko (~10-30 req/min)

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

## SDK Pitfalls (kalshi-python v2.1.4)

- **kwargs only**: All SDK methods use Pydantic `validate_call` and reject positional args. Use `client.create_order(**req.to_dict())` not `client.create_order(req)`.
- **Missing dependency**: The SDK imports `cryptography` at module level but doesn't declare it as a dependency. Install it explicitly: `pip install cryptography`.
- **Orderbook alias bug**: The SDK's Pydantic model expects JSON keys `"true"`/`"false"` but the API returns `"yes"`/`"no"`. All orderbook fetches in this skill use raw HTTP to bypass this. See `fetch_orderbook_raw()` in `runner.py`.
- **Positions response bug**: The SDK's `GetPositionsResponse` model expects a `"positions"` key, but the API returns `"market_positions"` and `"event_positions"`. The SDK silently drops ALL position data (`resp.positions` is always `None`). All position fetches in this skill use authenticated raw HTTP via `_fetch_authed_json()`. The `positions` command and UI dashboard both bypass the SDK for this endpoint.
- **Status filter values**: Query filters accept `unopened`, `open`, `paused`, `closed`, `settled`. Do NOT use response-level values like `active`.
- **Broken `/markets` listing**: The `get_markets()` call / `/markets` endpoint only returns multivariate esports combo markets. All real tradeable markets are only discoverable via the `/events` endpoint. Use `runner.py events` and `runner.py markets search` (events-based discovery) instead.
- **Crypto/daily series discovery**: Use the `/series` endpoint (`runner.py series`) to discover crypto markets (15-min, hourly, daily, weekly, monthly — 212+ series). Do NOT guess ticker patterns.

## Key Concepts

- **Prices** are in cents (1-99). YES at 65c ≈ 65% implied probability.
- **Fees** use round-up-to-cent: `ceil(k * C * P * (1-P) * 100) / 100`.
- **Taker** = 7% general, 3.5% index (INX/NASDAQ100). **Maker** = 1.75% or 0.
- **Break-even** is computed by searching cent-by-cent in the profitable direction.
- **Capital at risk** = max settlement loss + worst-case fees.
