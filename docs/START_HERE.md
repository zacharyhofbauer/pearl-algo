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
  - `src/pearlalgo/execution/ibkr/` (IBKR -- IBKR Virtual account)
  - `src/pearlalgo/execution/tradovate/` (Tradovate -- Tradovate Paper account)
- **Eval tracker**: `src/pearlalgo/market_agent/tv_paper_eval_tracker.py` (prop firm rule enforcement)
- **Ops/UI**: Telegram notifier + command handler, Web app (pearlalgo.io)

### Two accounts

Pearl runs two isolated accounts simultaneously:

| Account | Purpose | Execution | State Dir | API Port |
|---------|---------|-----------|-----------|----------|
| **IBKR Virtual** | Live market data, virtual P&L tracking | IBKR (dry_run) | `data/agent_state/NQ/` | 8000 |
| **Tradovate Paper** | MyFundedFutures 50K prop firm | Tradovate (paper) | `data/agent_state/TV_PAPER_EVAL/` | 8001 |

**Signal flow**: IBKR Virtual generates all signals via `strategy.analyze()`. Tradovate Paper reads signals from `data/shared_signals.jsonl` (written by IBKR Virtual) instead of running its own strategy. This guarantees both accounts trade the same signals. Tradovate Paper's circuit breaker eval gate still enforces prop firm rules (max contracts, trading hours, hedging, news blackout).

**Isolation rule**: `config/config.yaml` changes affect IBKR Virtual only. `config/markets/tv_paper_eval.yaml` changes affect Tradovate Paper only. `service.py` code changes affect both (Tradovate Paper-specific paths are gated by `self._tv_paper_enabled`).

### Quick operational checklist

```bash
./pearl.sh start          # Start everything
./pearl.sh stop           # Stop everything
./pearl.sh restart        # Restart everything
./pearl.sh quick          # One-liner status
./pearl.sh tv_paper restart   # Restart Tradovate Paper independently
./pearl.sh tv_paper logs      # Tail Tradovate Paper agent log
```

### Web app (pearlalgo.io)

- Hard refresh shows account selector (IBKR Virtual vs Tradovate Paper)
- Header dropdown to switch accounts anytime
- `pearlalgo.io` = IBKR Virtual, `pearlalgo.io?account=tv_paper` = Tradovate Paper

### Telegram

- `/start` shows both accounts (IBKR Virtual + Tradovate Paper section)
- `[TV-PAPER]` prefix on all Tradovate Paper notifications

### Configuration

- `config/config.yaml` (IBKR Virtual base config)
- `config/markets/tv_paper_eval.yaml` (Tradovate Paper overlay)
- `~/.config/pearlalgo/secrets.env` (credentials -- never committed)

### Where to go next

- **Daily operations**: `docs/CHEAT_SHEET.md`
- **Architecture**: `docs/PROJECT_SUMMARY.md`
- **Runbooks**: `docs/MARKET_AGENT_GUIDE.md`, `docs/GATEWAY.md`, `docs/TELEGRAM_GUIDE.md`
