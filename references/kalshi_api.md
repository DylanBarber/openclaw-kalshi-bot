# Kalshi Python SDK – API Reference

Quick reference for the `kalshi-python` package (v2.1+). Full docs: https://docs.kalshi.com/python-sdk

## API Hosts

| Host | Use |
|---|---|
| `https://api.kalshi.com/trade-api/v2` | **Production** — authenticated trading, full orderbook depth |
| `https://api.elections.kalshi.com/trade-api/v2` | Public data — may omit orderbook depth for some markets |
| `https://demo-api.kalshi.co/trade-api/v2` | Demo/sandbox |

**Default:** `api.kalshi.com` (override via `host` in config.yaml or `KALSHI_HOST` env var)

## Client Setup

```python
from kalshi_python import Configuration, KalshiClient

config = Configuration(host="https://api.kalshi.com/trade-api/v2")
with open("path/to/private_key.pem") as f:
    config.private_key_pem = f.read()
config.api_key_id = "your-api-key-id"

client = KalshiClient(config)
```

## Markets API

| Method | Description |
|---|---|
| `client.get_markets(limit=, cursor=, event_ticker=, series_ticker=, status=, tickers=)` | List/search markets |
| `client.get_market(ticker)` | Single market detail |
| `client.get_market_orderbook(ticker, depth=10)` | Orderbook bids — see note below |
| `client.get_trades(limit=, cursor=, ticker=, min_ts=, max_ts=)` | Public trade history |

### get_markets filters

- `status` — **Query filter values** (what you send): `unopened`, `open`, `paused`, `closed`, `settled`
  - NOTE: These are DIFFERENT from **response status values** (what the market object returns): `initialized`, `inactive`, `active`, `closed`, `determined`, `disputed`, `amended`, `finalized`
  - Do NOT pass `active` or `determined` as a filter — the API will return "invalid status filter"
- `event_ticker` / `series_ticker` — filter by event or series
- `tickers` — comma-separated market tickers
- `min_close_ts` / `max_close_ts` — Unix timestamps

### get_market_orderbook response

The response has `.orderbook` with two level arrays:
- **Python SDK attribute names**: `var_true` (YES bids) and `var_false` (NO bids)
  - NOT `yes`/`no` — those are mapped to `true`/`false` which are reserved in Python
- Each level is an `OrderbookLevel` with `.price` (float, **dollars** e.g. 0.65) and `.count` (int, contracts)
- Levels are sorted ascending; best bid is the **last** element
- Only bids are returned. YES asks are derived: `ask_cents = 100 - no_bid_cents`

## Portfolio API

| Method | Description |
|---|---|
| `client.get_balance()` | Balance & portfolio value (in cents) |
| `client.get_positions(ticker=, event_ticker=, limit=, cursor=)` | Open positions |
| `client.get_fills(ticker=, order_id=, limit=, cursor=)` | Fill history |
| `client.get_settlements(ticker=, event_ticker=, limit=, cursor=)` | Settlements |

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
