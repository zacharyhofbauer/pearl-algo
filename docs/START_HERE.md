## Start Here (Single Page)

This repo is a **trading platform** with three hard requirements:

- **Safety-first**: execution is guarded (dry_run/paper/live + arming + risk caps).
- **Observable**: every decision should be explainable from logs + persisted state.
- **Extensible**: new strategies, indicators, data providers, and execution adapters should plug in without rewiring the service.

### What runs in production

- **Service**: `src/pearlalgo/market_agent/service.py` (orchestrator)
- **Market data**: `src/pearlalgo/data_providers/` (IBKR provider + executor for data only)
- **Strategy**: `src/pearlalgo/trading_bots/pearl_bot_auto.py` (single-file strategy from Pine Scripts)
- **Execution**: `src/pearlalgo/execution/tradovate/` (Tradovate Paper only; IBKR execution is inactive)
- **Eval tracker**: `src/pearlalgo/market_agent/tv_paper_eval_tracker.py` (prop firm rule enforcement)
- **Ops/UI**: Telegram notifier + command handler, Web app (pearlalgo.io)

### Single account (Tradovate Paper)

Pearl runs a **single active trading account**: **Tradovate Paper** (50K Rapid Evaluation). IBKR is used for **market data only**; IBKR execution is inactive.

| Account | Purpose | Execution | State Dir | Config |
|---------|---------|-----------|-----------|--------|
| **Tradovate Paper** | Prop firm eval, paper trading | Tradovate (paper) | `data/tradovate/paper` (or per `--data-dir`) | `config/accounts/tradovate_paper.yaml` |

**Config**: Base settings in `config/base.yaml`; account overlay in `config/accounts/tradovate_paper.yaml`. Start the agent with `--config config/accounts/tradovate_paper.yaml`.

### Quick operational checklist

```bash
./pearl.sh start          # Start everything
./pearl.sh stop           # Stop everything
./pearl.sh restart        # Restart everything
./pearl.sh quick          # One-liner status
./pearl.sh start --no-chart   # Start without web app
./pearl.sh chart deploy   # Build + restart web app (after frontend changes)
./pearl.sh tv_paper restart   # Restart Tradovate Paper independently
./pearl.sh tv_paper logs      # Tail Tradovate Paper agent log
```

### Web app (pearlalgo.io)

- **Status badges** in header: Agent, GW, AI, Market, Data, ML, Shadow savings (with tooltips)
- **SystemStatusPanel**: Readiness (Offline/Paused/Cooldown/Disarmed/Armed), kill switch, session P&L
- **Pull-to-refresh** on mobile

### Telegram

- `/start` shows status and dashboard; `[TV-PAPER]` prefix on notifications

### Configuration

- `config/base.yaml` (shared defaults)
- `config/accounts/tradovate_paper.yaml` (Tradovate Paper account overlay; use with `--config`)
- `~/.config/pearlalgo/secrets.env` (credentials -- never committed)

### Where to go next

- **Daily operations**: `docs/CHEAT_SHEET.md`
- **Architecture**: `docs/PROJECT_SUMMARY.md`
- **Runbooks**: `docs/MARKET_AGENT_GUIDE.md`, `docs/GATEWAY.md`, `docs/TELEGRAM_GUIDE.md`
