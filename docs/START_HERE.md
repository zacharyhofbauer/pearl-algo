## Start Here (Single Page)

This repo is a **trading platform** with three hard requirements:

- **Safety-first**: execution is guarded (dry_run/paper/live + arming + risk caps).
- **Observable**: every decision should be explainable from logs + persisted state.
- **Extensible**: new strategies, indicators, data providers, and execution adapters should plug in without rewiring the service.

### What runs in production

- **Service**: `src/pearlalgo/market_agent/service.py` (orchestrator)
- **Market data**: `src/pearlalgo/data_providers/` (IBKR provider + executor)
- **Strategy**: `src/pearlalgo/trading_bots/pearl_bot_auto.py` (single-file strategy from Pine Scripts)
- **Execution adapters**:
  - `src/pearlalgo/execution/ibkr/` (IBKR -- inception account)
  - `src/pearlalgo/execution/tradovate/` (Tradovate -- MFFU prop firm account)
- **MFFU tracker**: `src/pearlalgo/market_agent/mffu_eval_tracker.py` (prop firm rule enforcement)
- **Ops/UI**: Telegram notifier + command handler, Web app (pearlalgo.io)

### Two accounts

Pearl runs two isolated accounts simultaneously:

| Account | Purpose | Execution | State Dir | API Port |
|---------|---------|-----------|-----------|----------|
| **Inception** | Since-inception data collection | IBKR (dry_run) | `data/agent_state/NQ/` | 8000 |
| **MFFU Eval** | MyFundedFutures 50K prop firm | Tradovate (paper) | `data/agent_state/MFFU_EVAL/` | 8001 |

### Quick operational checklist

```bash
./pearl.sh start          # Start everything
./pearl.sh stop           # Stop everything
./pearl.sh restart        # Restart everything
./pearl.sh quick          # One-liner status
./pearl.sh mffu restart   # Restart MFFU independently
./pearl.sh mffu logs      # Tail MFFU agent log
```

### Web app (pearlalgo.io)

- Hard refresh shows account selector (Inception vs MFFU)
- Header dropdown to switch accounts anytime
- `pearlalgo.io` = inception, `pearlalgo.io?account=mffu` = MFFU

### Telegram

- `/start` shows both accounts (inception + MFFU section)
- `[MFFU]` prefix on all MFFU notifications

### Configuration

- `config/config.yaml` (inception base config)
- `config/markets/mffu_eval.yaml` (MFFU overlay)
- `~/.config/pearlalgo/secrets.env` (credentials -- never committed)

### Where to go next

- **Daily operations**: `docs/CHEAT_SHEET.md`
- **Architecture**: `docs/PROJECT_SUMMARY.md`
- **Runbooks**: `docs/MARKET_AGENT_GUIDE.md`, `docs/GATEWAY.md`, `docs/TELEGRAM_GUIDE.md`
