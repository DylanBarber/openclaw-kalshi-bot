# Kalshi Python SDK – API Reference

Quick reference for the `kalshi-python` package (v2.1+). Full docs: https://docs.kalshi.com/python-sdk

## API Hosts

| Host | Use |
|---|---|
| `https://api.elections.kalshi.com/trade-api/v2` | **Production** — event-based markets |
| `https://demo-api.kalshi.co/trade-api/v2` | Demo/sandbox |

**Default:** `api.elections.kalshi.com` (override via `host` in config.yaml or `KALSHI_HOST` env var)

**IMPORTANT:** `api.kalshi.com` does not resolve. `trading-api.kalshi.com` redirects to elections. The elections host is the only working production host.

## Client Setup

```python
from kalshi_python import Configuration, KalshiClient

config = Configuration(host="https://api.elections.kalshi.com/trade-api/v2")
with open("path/to/private_key.pem") as f:
    config.private_key_pem = f.read()
config.api_key_id = "your-api-key-id"

client = KalshiClient(config)
```

## Events API (Primary Market Discovery)

**WARNING: The `/markets` listing is BROKEN for market discovery.** It only returns multivariate esports combo markets (`KXMVESPORTSMULTIGAMEEXTENDED-*`). You MUST use the events endpoint to find real tradeable markets.

| Endpoint | Auth | Description |
|---|---|---|
| `GET /events?limit=100&cursor=` | No | Paginate all events |
| `GET /events/{event_ticker}` | No | Single event + nested markets array |

### Correct market discovery flow

```
1. GET /events?limit=100  → list of events with category, title, event_ticker
2. GET /events/{event_ticker}  → { "event": {...}, "markets": [...] }
3. Use market tickers from step 2 for orderbook/trading
```

This gives access to ~2,900+ active markets across categories:
- **Politics** (831), **Entertainment** (524), **Sports** (485), **Economics** (463)
- **Elections** (443), **Social** (55), **Companies** (27), **Climate & Weather** (23)
- Plus: World, Science & Technology, Health, Transportation, Financials

### Markets NOT available on this host

Daily series tickers return **404 Not Found**:
- `KXBTC-*` (Bitcoin brackets), `KXETH-*` (Ethereum)
- `KXINX-*` (S&P 500), `KXNASDAQ100-*` (Nasdaq)
- Daily weather/temperature markets

**UPDATE:** Crypto and other series markets ARE accessible via the `/series` endpoint. See Series API below.

## Series API (Crypto / Daily / Hourly Market Discovery)

The `/series` endpoint provides access to 212+ crypto series and other repeating market types.

### Endpoints (raw HTTP, no SDK needed)

| Endpoint | Description |
|---|---|
| `GET /series?category=Crypto&limit=200` | List all crypto series |
| `GET /series/{ticker}` | Detail for a single series (title, frequency, category, tags) |
| `GET /events?series_ticker={ticker}&limit=20` | Events (time windows) within a series |

### Key crypto series

| Series | Frequency | Title | Ticker Format |
|---|---|---|---|
| `KXBTC15M` | fifteen_min | BTC Up or Down - 15 minutes | `KXBTC15M-{YYMONDDHHMI}-{MI}` |
| `KXETH15M` | fifteen_min | ETH 15M price up down | `KXETH15M-{YYMONDDHHMI}-{MI}` |
| `KXSOL15M` | fifteen_min | Solana 15 minutes | `KXSOL15M-{YYMONDDHHMI}-{MI}` |
| `KXXRP15M` | fifteen_min | XRP 15 Minute | `KXXRP15M-{YYMONDDHHMI}-{MI}` |
| `KXBTC` | hourly | Bitcoin range (bracket) | `KXBTC-{YYMONDDHHMI}-B{strike}` |
| `KXETH` | hourly | Ethereum range (bracket) | `KXETH-{YYMONDDHHMI}-B{strike}` |
| `KXSOL` | hourly | Solana range (bracket) | `KXSOL-{YYMONDDHHMI}-B{strike}` |
| `KXDOGE` | hourly | Dogecoin range (bracket) | `KXDOGE-{YYMONDDHHMI}-B{strike}` |
| `KXXRP` | hourly | XRP range (bracket) | `KXXRP-{YYMONDDHHMI}-B{strike}` |
| `KXBTCD` | hourly | Bitcoin price above/below | `KXBTCD-{YYMONDDHHMI}-T{strike}` |
| `KXETHD` | hourly | Ethereum price above/below | `KXETHD-{YYMONDDHHMI}-T{strike}` |
| `KXSOLD` | hourly | SOL price above/below | `KXSOLD-{YYMONDDHHMI}-T{strike}` |
| `KXXRPD` | hourly | XRP price above/below | `KXXRPD-{YYMONDDHHMI}-T{strike}` |
| `KXBTCMAXW` | weekly | How high will Bitcoin get this week? | `KXBTCMAXW-*` |
| `KXBTCMAXM` | monthly | How high will Bitcoin get this month? | `KXBTCMAXM-*` |

### Series response structure

```json
{
  "series": {
    "ticker": "KXBTC15M",
    "title": "Bitcoin price up down",
    "category": "Crypto",
    "frequency": "fifteen_min",
    "fee_type": "quadratic",
    "tags": ["15 min", "BTC"],
    "settlement_sources": [{"name": "CF Benchmarks", "url": "..."}]
  }
}
```

### Frequency values

`fifteen_min`, `hourly`, `daily`, `weekly`, `monthly`, `annual`, `custom`, `one_off`

### 15-minute market notes

- Each 15-minute event contains ONE binary market: "BTC price up in next 15 mins?" (YES/NO)
- Markets cycle through statuses: `initialized` -> `active` (tradeable) -> `closed` -> `settled`
- Only `active` markets have orderbook data and accept orders
- Markets show `initialized` until their time slot activates (Kalshi crypto trades 24/7)

### Hourly market notes

Hourly crypto markets come in two types:

**Directional (above/below)** — `KXBTCD`, `KXETHD`, `KXSOLD`, `KXXRPD`:
- Each event has 50-75 strike prices (e.g., "BTC above $68,749.99?")
- Ticker format: `KXBTCD-{YYMONDDHHMI}-T{strike}` (e.g., `KXBTCD-26FEB2017-T68749.99`)
- YES = price above strike at expiry; NO = price below
- Best liquidity: BTC ($30k+ volume per popular strike), ETH ($10k+)
- Real L2 data with tight spreads (1-3c on BTC)

**Range (bracket)** — `KXBTC`, `KXETH`, `KXSOL`, `KXDOGE`, `KXXRP`:
- Each event has 50+ brackets (e.g., "BTC in $68,500-$68,999.99?")
- Ticker format: `KXBTC-{YYMONDDHHMI}-B{strike}` (e.g., `KXBTC-26FEB2017-B68500`)
- YES = price lands in that range; generally lower liquidity than directional
- Settlement source: CF Benchmarks

Both types:
- Events show `initialized` until their time slot activates, then become `active` (Kalshi trades 24/7)
- Multiple events may be live at once (e.g., 1 hour, 5 hours, and 24 hours out)
- The further-out event typically has the most volume/liquidity

## Markets API

| Method | Description |
|---|---|
| `client.get_markets(limit=, cursor=, event_ticker=, series_ticker=, status=, tickers=)` | List markets — **BROKEN: only returns esports combos** |
| `client.get_market(ticker)` | Single market detail — **works for all tickers** |
| `client.get_market_orderbook(ticker, depth=10)` | Orderbook bids — see note below |
| `client.get_trades(limit=, cursor=, ticker=, min_ts=, max_ts=)` | Public trade history |

### get_markets filters

**IMPORTANT:** `get_markets()` only returns multivariate esports combo markets when listing. For market discovery, use the Events API above instead.

- `status` — **Query filter values** (what you send): `unopened`, `open`, `paused`, `closed`, `settled`
  - NOTE: These are DIFFERENT from **response status values** (what the market object returns): `initialized`, `inactive`, `active`, `closed`, `determined`, `disputed`, `amended`, `finalized`
  - Do NOT pass `active` or `determined` as a filter — the API will return "invalid status filter"
- `event_ticker` / `series_ticker` — filter by event or series
- `tickers` — comma-separated market tickers
- `min_close_ts` / `max_close_ts` — Unix timestamps

### get_market_orderbook response

**WARNING: SDK bug in kalshi-python v2.1.4** — The SDK Pydantic model uses
aliases `var_true -> "true"` and `var_false -> "false"`, but the API returns
`"yes"` and `"no"` keys.  The SDK silently drops all orderbook data
(`var_true = None, var_false = None`).  Our code bypasses the SDK for this
endpoint and uses raw HTTP via `fetch_orderbook_raw()`.

Raw JSON format (from the API):
```json
{"orderbook": {"yes": [[price_cents, qty], ...], "no": [[price_cents, qty], ...]}}
```

- `yes` = YES bids, `no` = NO bids.  Each is `[[price_cents, qty], ...]`
- Prices are integers in **cents** (1-99)
- Levels are sorted ascending; best (highest) bid is the **last** element
- Only bids are returned.  YES asks are derived: `ask_cents = 100 - no_bid_cents`
- Combo/multivariate markets return `null` for both arrays (no standalone book)

## Portfolio API

| Method | Description |
|---|---|
| `client.get_balance()` | Balance & portfolio value (in cents) |
| `client.get_positions(ticker=, event_ticker=, limit=, cursor=)` | Open positions — **BROKEN: see note below** |
| `client.get_fills(ticker=, order_id=, limit=, cursor=)` | Fill history |
| `client.get_settlements(ticker=, event_ticker=, limit=, cursor=)` | Settlements |

### get_positions response

**WARNING: SDK bug in kalshi-python v2.1.4** — The SDK's `GetPositionsResponse`
Pydantic model expects a `"positions"` JSON key, but the Kalshi API returns
`"market_positions"` and `"event_positions"`.  The SDK silently drops ALL
position data (`resp.positions` is always `None`).

Our code bypasses the SDK for this endpoint and uses authenticated raw HTTP
via `_fetch_authed_json()` in both `runner.py` and `api_server.py`.

Raw JSON format (from the API):
```json
{
  "cursor": "",
  "market_positions": [
    {
      "ticker": "KXPRESPERSON-28-GNEWS",
      "position": 48,
      "market_exposure": 1008,
      "market_exposure_dollars": "10.0800",
      "fees_paid": 58,
      "fees_paid_dollars": "0.5800",
      "realized_pnl": 0,
      "realized_pnl_dollars": "0.0000",
      "resting_orders_count": 0,
      "total_traded": 1008,
      "total_traded_dollars": "10.0800",
      "last_updated_ts": "2026-02-16T01:17:25.949347Z"
    }
  ],
  "event_positions": [
    {
      "event_ticker": "KXPRESPERSON-28",
      "event_exposure": 1736,
      "event_exposure_dollars": "17.3600",
      "total_cost": 1736,
      "total_cost_dollars": "17.3600",
      "fees_paid": 58,
      "fees_paid_dollars": "0.5800",
      "realized_pnl": 0,
      "realized_pnl_dollars": "0.0000"
    }
  ]
}
```

- `position` > 0 = net long YES; < 0 = net short YES (long NO)
- `market_exposure` / `event_exposure` = current dollar exposure in cents
- `total_traded` = total volume traded in cents
- Values with `_dollars` suffix are pre-formatted string dollar amounts

## Order Management

| Method | Description |
|---|---|
| `client.create_order(CreateOrderRequest(...))` | Place an order |
| `client.cancel_order(order_id)` | Cancel a resting order |
| `client.get_orders(ticker=, status=, limit=, cursor=)` | List orders |
| `client.get_order(order_id)` | Single order detail |
| `client.amend_order(order_id, ...)` | Modify an order |
| `client.decrease_order(order_id, ...)` | Reduce order size |
| `client.batch_create_orders(...)` | Create multiple orders |
| `client.batch_cancel_orders(...)` | Cancel multiple orders |

### CreateOrderRequest fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `ticker` | str | yes | Market ticker |
| `side` | str | yes | `"yes"` or `"no"` |
| `action` | str | yes | `"buy"` or `"sell"` |
| `count` | int | yes | Number of contracts |
| `type` | str | no | `"limit"` (default) or `"market"` |
| `yes_price` | int | no | Price in cents (1-99) |
| `no_price` | int | no | Price in cents (1-99) |
| `time_in_force` | str | no | `"good_till_canceled"`, `"fill_or_kill"`, `"immediate_or_cancel"` |
| `expiration_ts` | int | no | Unix timestamp |
| `post_only` | bool | no | Maker-only order |
| `reduce_only` | bool | no | Only reduces position |

### Order response fields

Key fields on the `Order` object: `order_id`, `ticker`, `side`, `action`, `type`, `status` (`resting`/`canceled`/`executed`), `yes_price`, `no_price`, `initial_count`, `remaining_count`, `fill_count`, `taker_fees`, `maker_fees`, `created_time`.

## Exchange API

| Method | Description |
|---|---|
| `client.get_exchange_status()` | Exchange open/closed status |
| `client.get_exchange_schedule()` | Trading schedule |

## Prices

All prices in the SDK are in **cents** (1-99). A YES contract at 65 cents means the market implies ~65% probability. Balances and costs are also in cents.

## Pagination

Most list endpoints return a `cursor` field. Pass it back to get the next page:

```python
resp = client.get_markets(limit=100)
while resp.cursor:
    resp = client.get_markets(limit=100, cursor=resp.cursor)
```

## Error Handling

SDK methods raise exceptions on HTTP errors. Wrap calls in try/except:

```python
from kalshi_python.rest import ApiException

try:
    client.create_order(req)
except ApiException as e:
    print(f"API error {e.status}: {e.body}")
```
