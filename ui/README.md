# Kalshi Trading Dashboard

Local web UI for monitoring your Kalshi positions, browsing markets, and tracking price movements.

## Setup

### 1. Create a virtual environment

```bash
cd kalshi-bot/ui
python -m venv venv
```

Activate it:

```bash
# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install flask pyyaml kalshi-python cryptography requests
```

Or install from the shared requirements file:

```bash
pip install -r ../scripts/requirements.txt
```

### 3. Configure credentials

The dashboard reads credentials from `scripts/config.yaml`. If you haven't set that up yet:

```bash
cp ../scripts/config.example.yaml ../scripts/config.yaml
```

Edit `scripts/config.yaml` and fill in:

- `api_key_id` -- your Kalshi API key (from https://kalshi.com/account/api-keys)
- `private_key_path` -- path to your RSA PEM private key file

### 4. Start the server

```bash
python api_server.py
```

The dashboard opens at **http://127.0.0.1:5123**.

Options:

```bash
python api_server.py --port 8080        # custom port
python api_server.py --host 0.0.0.0     # listen on all interfaces
python api_server.py --debug            # Flask debug mode
```

## What it shows

- **Market Browser** -- browse all ~2,900+ markets by category or text search, view orderbooks, start watchers
- **Active Watchers** -- live bid/ask/spread, gross P&L, fees, net P&L for watched positions
- **Price Chart** -- click any watcher to see its price history over time
- **Orderbook** -- L2 depth visualization for the selected market
- **Resting Orders** -- your open orders on Kalshi
- **Positions** -- your current positions with cost basis and realized P&L

The dashboard auto-refreshes every 3 seconds. A background poller keeps watcher prices updated even when the browser tab is closed.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'flask'` | Activate the venv and run `pip install flask` |
| `Could not import Configuration/KalshiClient` | Run `pip install cryptography kalshi-python` -- the SDK needs `cryptography` but doesn't declare it |
| Balance/positions show "Kalshi client not configured" | Check that `scripts/config.yaml` exists with valid credentials |
| Market browser shows no results | Select a category from the dropdown or type a search query and press Enter |
| Watcher prices show `--` | The market may have no resting orders (empty book) or may have expired |
