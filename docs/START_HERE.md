## Start Here (Single Page)

This repo is a **trading platform** with three hard requirements:

- **Safety-first**: execution is guarded (dry_run/paper/live + arming + risk caps).
- **Observable**: every decision should be explainable from logs + persisted state.
- **Extensible**: new strategies, indicators, data providers, and execution adapters should plug in without rewiring the service.

The current live path is intentionally smaller than the full repo. If a module,
script, env var, or alias is not part of the operating model below, treat it as
non-canonical and check `docs/COMPATIBILITY_SURFACES.md` before using it.

### What runs in production

- **Service**: `src/pearlalgo/market_agent/service.py` (orchestrator)
- **Market data**: `src/pearlalgo/data_providers/` (IBKR provider + executor for data only)
- **Strategy**: `src/pearlalgo/strategies/composite_intraday/` (canonical live strategy bundle)
- **Execution**: `src/pearlalgo/execution/tradovate/` (Tradovate Paper only; IBKR execution is inactive)
- **Eval tracker**: `src/pearlalgo/market_agent/tv_paper_eval_tracker.py` (prop firm rule enforcement)
- **Ops/UI**: Telegram notifier + command handler, Next.js web app in `apps/pearl-algo-app/` (pearlalgo.io)

No new live trading logic should be added outside those paths unless the
operating model itself is being expanded.

### Single account (Tradovate Paper)

Pearl runs a **single active trading account**: **Tradovate Paper** (50K Rapid Evaluation). IBKR is used for **market data only**; IBKR execution is inactive.

| Account | Purpose | Execution | State Dir | Config |
|---------|---------|-----------|-----------|--------|
| **Tradovate Paper** | Prop firm eval, paper trading | Tradovate (paper) | explicit `--data-dir` for the running agent/API; keep them aligned | `config/live/tradovate_paper.yaml` |

**Config**: Canonical live runtime config in `config/live/tradovate_paper.yaml`. Start the agent with `--config config/live/tradovate_paper.yaml`.

### Canonical directory layout

- **Repo root**: `/home/pearlalgo/projects/pearl-algo`
- **Live runtime state**: `/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ`
- **Repo compatibility path**: `data/` is a symlink into `~/var/pearl-algo/state/data`
- **Repo logs path**: `logs/` is a symlink into `~/var/pearl-algo/logs`
- **Web app frontend**: `apps/pearl-algo-app/`
- **Retained web app/API wrappers**: `scripts/pearlalgo_web_app/` (non-canonical wrapper layer; see compatibility surfaces)

### What is explicitly non-canonical

- Compatibility aliases and wrapper scripts
- Legacy strategy bridges under `src/pearlalgo/trading_bots/`
- Old config shapes kept readable by migration helpers
- Frontend/API auth fallbacks retained to avoid breaking callers

These can remain in the repo, but they should be marked, contained, and kept
out of new feature work.

### Safety baseline

- Current state should be checked before any restart or re-arm:
  - `./pearl.sh quick`
  - `python3 scripts/ops/audit_runtime_paths.py`
- Trading is safe only when:
  - `positions=[]`
  - `execution.armed=false` until you intentionally re-arm
- No strategy or execution changes should be mixed with web app/UI work.

### Known single points of failure

| SPOF | Impact | Mitigation |
|------|--------|-----------|
| IBKR Gateway (localhost:4001) | Market data stops, no signals generated | Connection circuit breaker, auto-reconnect every 60s |
| Tradovate API | Orders cannot be placed, open positions can't exit | No failover; logs alert, manual kill-switch via Telegram |
| Agent process (single PID) | All trading halts | Systemd `Restart=always, RestartSec=10` |
| Local filesystem (/home/pearlalgo/var/) | State lost on crash | No redundancy; ensure reliable storage |

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
- **Wrapper scripts**: `scripts/pearlalgo_web_app/` (retained compatibility shell around the API server)
- **Status badges** in header: Agent, GW, AI, Market, Data, ML, Shadow savings (with tooltips)
- **SystemStatusPanel**: Readiness (Offline/Paused/Cooldown/Disarmed/Armed), kill switch, session P&L
- **Pull-to-refresh** on mobile

### Telegram

- `/start` shows status and dashboard; `[TV-PAPER]` prefix on notifications

### Configuration

- `config/live/tradovate_paper.yaml` (canonical Tradovate Paper runtime config)
- `~/.config/pearlalgo/secrets.env` (credentials -- never committed)

### Where to go next

- **Path/runtime truth**: `docs/PATH_TRUTH_TABLE.md`
- **Retained legacy bridges**: `docs/COMPATIBILITY_SURFACES.md`
- **Gateway operations**: `docs/GATEWAY.md`
- **Testing**: `docs/TESTING_GUIDE.md`
