# Kalshi Bot

CLI tool and trading engine for [Kalshi](https://kalshi.com) prediction markets, built on the official `kalshi-python` SDK. Includes a complete fee-aware trading doctrine with acceptance gates, risk management, and automatic position sizing.

## Project Structure

```
kalshi-bot/
|-- SKILL.md                           # OpenClaw skill definition (triggers + instructions)
|-- AGENTS.md                          # Agent playbook: strategy, workflow, gate explanations
|-- agents/
|   +-- openai.yaml                    # UI metadata (display name, description, prompt)
|-- scripts/
|   |-- runner.py                      # CLI entry point - all user-facing commands
|   |-- kalshi_math.py                 # Pure math: fees, P&L, break-even, sizing (no SDK dep)
|   |-- trade_engine.py                # Trade evaluation, 4 acceptance gates, order tickets
|   |-- config.example.yaml            # Template config - credentials + risk parameters
|   |-- requirements.txt               # Python dependencies (kalshi-python, pyyaml)
|   +-- strategies/
|       |-- fee_aware_mm.py            # Full doctrine strategy: gates, sizing, execution
|       +-- example_spread.py          # Lightweight spread watcher with evaluation
|-- references/
|   |-- kalshi_api.md                  # Kalshi Python SDK quick reference
|   +-- trading_doctrine.md            # Complete formula & rules reference
|-- .gitignore
+-- README.md
```

### Module Overview

| Module | Purpose |
|---|---|
| `runner.py` | Argparse CLI dispatching all commands (`markets`, `buy`, `sell`, `cancel`, `orderbook`, `balance`, `orders`, `positions`, `fills`, `run-strategy`) |
| `kalshi_math.py` | Stateless functions implementing every formula from the trading doctrine: fee calculation, gross/net P&L, slippage, capital at risk, break-even search, position sizing. Zero SDK dependency, fully unit-testable. |
| `trade_engine.py` | Orchestrates a full trade evaluation: computes all metrics, runs the 4 acceptance gates (A-D), enforces portfolio risk limits, formats the canonical order ticket, and provides execution helpers (`place_limit_order`, `wait_for_fill`). |
| `strategies/fee_aware_mm.py` | Production strategy: reads the orderbook, auto-sizes via doctrine, evaluates through all gates, prints the order ticket, and executes with TP/stop/time-stop exits. Supports `--dry-run`, `--loop`, side/contract/price overrides. |
| `strategies/example_spread.py` | Simpler strategy: monitors the spread and prints a full evaluation whenever it tightens below a threshold. |

### Key Files for Agents

| File | When to read |
|---|---|
| `AGENTS.md` | Start here. Full playbook for the OpenClaw agent: golden rules, command reference, decision workflow, gate explanations, config tuning. |
| `SKILL.md` | Skill definition with setup instructions and architecture overview. Read by Codex to decide when to activate the skill. |
| `references/trading_doctrine.md` | Complete formula reference. Read when you need to verify or explain any calculation. |
| `references/kalshi_api.md` | SDK method signatures and response fields. Read when constructing API calls. |

### Trading Doctrine (4 Gates)

Every trade must pass all four gates before execution:

| Gate | Condition |
|---|---|
| **A** - Worst-case survivability | Net P&L under taker/taker + slippage >= $0 |
| **B** - Margin over fees | Net profit >= 2x planned fees |
| **C** - Move threshold | Expected price move >= worst-case break-even move + safety margin |
| **D** - Microstructure | Spread <= configured max, visible depth >= configured min |

After gates pass, portfolio-level hard limits are checked (per-market capital, total capital, daily loss, concurrent positions, order rate). Only then does an order go out.

## Prerequisites

- Python 3.9+
- A Kalshi account with an API key ([create one here](https://kalshi.com/account/api-keys))

## Quick Start

```bash
# 1. Clone / navigate to the skill directory
cd kalshi-bot

# 2. Create a virtual environment and install
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r scripts/requirements.txt

# 3. Configure credentials
cp scripts/config.example.yaml scripts/config.yaml
# Edit scripts/config.yaml - set api_key_id and private_key_path

# 4. Verify connection
python scripts/runner.py balance

# 5. Search markets
python scripts/runner.py markets search "bitcoin"

# 6. Evaluate a trade (dry run - no real orders)
python scripts/runner.py run-strategy fee_aware_mm --ticker KXBTC-26FEB14-T50050 -- --dry-run
```

## Configuration

Copy `scripts/config.example.yaml` to `scripts/config.yaml`. The file has two sections:

**Credentials** (required):
```yaml
api_key_id: "your-api-key-id"
private_key_path: "~/.kalshi/private_key.pem"
```

**Risk parameters** (tune to your capital/tolerance):
```yaml
risk:
  max_capital_at_risk_per_market_usd: 50.0
  max_total_capital_at_risk_usd: 200.0
  max_daily_realized_loss_usd: 100.0
  max_concurrent_positions: 5
  slippage_buffer_cents: 1.0
  safety_margin_cents: 2
  fee_margin_multiplier: 2.0
  max_spread_cents: 8
  min_depth_contracts: 5
```

Environment variables `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PATH` override the file.

## Writing Custom Strategies

1. Create `scripts/strategies/<name>.py`
2. Implement `def run(client, args) -> None`
3. Import the engine:
   ```python
   from kalshi_math import PositionSide, FillType
   from trade_engine import RiskConfig, TradeParams, evaluate_trade, format_order_ticket
   ```
4. Build a `TradeParams`, call `evaluate_trade()`, check `ev.all_gates_pass`
5. Run: `python scripts/runner.py run-strategy <name> --ticker TICKER`

Extra arguments after `--` are forwarded to your strategy's own arg parser.

## Installing as an OpenClaw Skill

This project is an [OpenClaw](https://docs.openclaw.ai/tools/skills) skill following the [AgentSkills](https://agentskills.io) format. The `SKILL.md` file contains the YAML frontmatter (`name` + `description`) that OpenClaw uses to decide when to activate the skill, and the body contains the agent instructions.

OpenClaw loads skills from three locations (highest precedence first):

| Location | Scope |
|---|---|
| `<workspace>/skills/` | Per-agent (workspace-local) |
| `~/.openclaw/skills/` | Shared across all agents on the machine |
| Bundled skills | Shipped with OpenClaw |

### Option 1: Workspace install (per-agent)

Copy the skill into your workspace's `skills/` directory:

```bash
# From your workspace root
cp -r /path/to/kalshi-bot skills/kalshi-bot
```

On Windows:
```powershell
Copy-Item -Recurse C:\path\to\kalshi-bot .\skills\kalshi-bot
```

This makes the skill available only to agents running in that workspace.

### Option 2: Managed install (shared across agents)

Copy or symlink into the managed skills directory:

```bash
# Shared across all agents
cp -r /path/to/kalshi-bot ~/.openclaw/skills/kalshi-bot

# Or symlink for development
ln -s /path/to/kalshi-bot ~/.openclaw/skills/kalshi-bot
```

On Windows:
```powershell
Copy-Item -Recurse C:\path\to\kalshi-bot "$env:USERPROFILE\.openclaw\skills\kalshi-bot"
```

### Option 3: ClawHub

If the skill is published to [ClawHub](https://clawhub.com):

```bash
clawhub install kalshi-bot
```

To update later: `clawhub update kalshi-bot`

### Option 4: Extra skills directory

Add a custom skills folder in `~/.openclaw/openclaw.json`:

```json5
{
  skills: {
    load: {
      extraDirs: ["/path/to/my-skills"]
    }
  }
}
```

Then place the `kalshi-bot` folder inside that directory.

### After installation

1. **Start a new OpenClaw session** to pick up the skill. OpenClaw snapshots eligible skills at session start; changes take effect on the next session (or on hot-reload if the skills watcher is enabled).
2. The skill triggers automatically when you mention Kalshi, prediction markets, or trading strategies. OpenClaw reads the `SKILL.md` frontmatter `description` to decide when to activate it.
3. **Set up credentials**: copy `scripts/config.example.yaml` to `scripts/config.yaml` inside the installed skill directory and fill in your Kalshi API key and private key path.
4. **Install Python dependencies**: run `pip install -r scripts/requirements.txt` inside the skill's `.venv` (see Quick Start above).
5. The agent follows `AGENTS.md` for its decision-making workflow: always dry-run first, present the order ticket, and wait for your approval before live execution.

### Verifying installation

```bash
ls ~/.openclaw/skills/kalshi-bot/SKILL.md   # managed install
# or
ls skills/kalshi-bot/SKILL.md               # workspace install
```

If the file exists and contains valid YAML frontmatter, the skill is installed. You can also check OpenClaw's session logs to confirm `kalshi-bot` appears in the eligible skills list.

### Optional: config overrides

You can toggle the skill or inject env vars via `~/.openclaw/openclaw.json`.
Because the skill declares `primaryEnv: "KALSHI_API_KEY_ID"` in its metadata,
you can use the `apiKey` shorthand:

```json5
{
  skills: {
    entries: {
      "kalshi-bot": {
        enabled: true,
        apiKey: "your-kalshi-api-key-id",
        env: {
          KALSHI_API_KEY_ID: "your-kalshi-api-key-id",
          KALSHI_PRIVATE_KEY_PATH: "/path/to/private_key.pem"
        }
      }
    }
  }
}
```

Note: the skill name contains a hyphen, so the key must be quoted (`"kalshi-bot"`).
See the [OpenClaw Skills docs](https://docs.openclaw.ai/tools/skills) for the
full config schema, gating rules, and environment injection behavior.

### Skill gating

The `SKILL.md` frontmatter includes OpenClaw metadata that gates the skill at load time:

- **`requires.anyBins: ["python3", "python"]`** -- the skill is only eligible when Python is on PATH.
- **`requires.env: ["KALSHI_API_KEY_ID"]`** -- the skill is only eligible when the API key is set (either as a real env var or via `skills.entries."kalshi-bot".env` / `apiKey` in `openclaw.json`).

If either condition is not met, OpenClaw silently skips the skill. This prevents
the agent from attempting trades when the environment isn't configured.

## License

Private - not for redistribution without permission.
