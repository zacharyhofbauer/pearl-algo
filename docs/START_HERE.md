## Start Here (Single Page)

This repo is a **trading platform** with three hard requirements:

- **Safety-first**: execution is guarded (dry_run/paper/live + arming + risk caps).
- **Observable**: every decision should be explainable from logs + persisted state.
- **Extensible**: new strategies, indicators, data providers, and execution adapters should plug in without rewiring the service.

### What runs in production

- **Service**: `src/pearlalgo/market_agent/service.py` (orchestrator)
- **Market data**: `src/pearlalgo/data_providers/` (IBKR provider + executor for data only)
- **Strategy**: `src/pearlalgo/strategies/composite_intraday/` (canonical live strategy bundle)
- **Execution**: `src/pearlalgo/execution/tradovate/` (Tradovate Paper only; IBKR execution is inactive)
- **Eval tracker**: `src/pearlalgo/market_agent/tv_paper_eval_tracker.py` (prop firm rule enforcement)
- **Ops/UI**: Telegram notifier + command handler, Next.js web app in `apps/pearl-algo-app/` (pearlalgo.io)

### Single account (Tradovate Paper)

Pearl runs a **single active trading account**: **Tradovate Paper** (50K Rapid Evaluation). IBKR is used for **market data only**; IBKR execution is inactive.

| Account | Purpose | Execution | State Dir | Config |
|---------|---------|-----------|-----------|--------|
| **Tradovate Paper** | Prop firm eval, paper trading | Tradovate (paper) | explicit `--data-dir` for the running agent/API; keep them aligned | `config/live/tradovate_paper.yaml` |

**Config**: Canonical live runtime config in `config/live/tradovate_paper.yaml`. Start the agent with `--config config/live/tradovate_paper.yaml`.

### Audit the live runtime layout

Before trusting a dashboard, health check, or historical query after a revamp, verify which
state directory the live processes are actually using:

```bash
python3 scripts/ops/audit_runtime_paths.py
```

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

- **Frontend path**: `apps/pearl-algo-app/`
- **Wrapper scripts**: `scripts/pearlalgo_web_app/`
- **Status badges** in header: Agent, GW, AI, Market, Data, ML, Shadow savings (with tooltips)
- **SystemStatusPanel**: Readiness (Offline/Paused/Cooldown/Disarmed/Armed), kill switch, session P&L
- **Pull-to-refresh** on mobile

### Telegram

- `/start` shows status and dashboard; `[TV-PAPER]` prefix on notifications

### Configuration

- `config/live/tradovate_paper.yaml` (canonical Tradovate Paper runtime config)
- `config/accounts/tradovate_paper.yaml` (legacy overlay kept only for migration compatibility)
- `~/.config/pearlalgo/secrets.env` (credentials -- never committed)

### Where to go next

- **Current operating model**: `docs/CURRENT_OPERATING_MODEL.md`
- **Path/runtime truth**: `docs/PATH_TRUTH_TABLE.md`
- **Gateway operations**: `docs/GATEWAY.md`
- **Testing**: `docs/TESTING_GUIDE.md`
- **Historical context only**: `docs/archive/`
