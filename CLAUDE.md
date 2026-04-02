# PearlAlgo - Claude Code Instructions

**WARNING: This is a LIVE 24/7 automated futures trading system. Every code change can cause real financial loss.**

## Architecture

- **Market data:** IBKR gateway (data only, NOT used for execution)
- **Order execution:** Tradovate (paper account = source of truth for trades)
- **Notifications:** Telegram
- **Entry point:** `pearl.sh` (master control), `python -m pearlalgo.market_agent.main`
- **Canonical runtime config:** `config/live/tradovate_paper.yaml`
- **Prop firm:** MFF compliance via TraderSyncer (copies demo -> live)

## Critical Safety Rules

**NEVER change these without explicit user approval:**

| Setting | Required Value | Why |
|---------|---------------|-----|
| `execution.armed` | current value | Controls live order submission |
| `execution.enabled` | current value | Master execution switch |
| `execution.mode` | current value | Paper vs live |
| `max_positions` | current value | Position limit |
| `max_position_size_per_order` | 1 | 1 contract per order, adds allowed |
| `max_position_size` | 5 | MFF max 5 MNQ total |
| `guardrails.*` | current values | Minimal execution safety without legacy signal gating |
| `virtual_pnl.*` | disabled | Not used, Tradovate is source of truth |
| `ibkr.execution` | inactive | IBKR is data-only |

## Config Rules

- **YAML duplicate keys are SILENT** — last key wins, no error.
- Canonical runtime edits belong in `config/live/tradovate_paper.yaml`.
- Always validate YAML after editing: `python -c "import yaml; yaml.safe_load(open('config/live/tradovate_paper.yaml'))"`

## Forbidden Actions

1. Do NOT re-enable IBKR execution
2. Do NOT increase contract sizes above 1
3. Do NOT disable execution guardrails or drawdown limits
4. Do NOT enable virtual PnL
5. Do NOT reintroduce legacy time / direction / regime signal gates without user approval
6. Do NOT restart the trading service without user approval

## Testing

- Run `python -m pytest tests/ -x -q` before any changes
- Validate YAML configs after editing
- Check `logs/` for errors after changes

## Key Files

| File | Purpose |
|------|---------|
| `src/pearlalgo/market_agent/service.py` | Main service orchestrator |
| `src/pearlalgo/market_agent/service_loop.py` | Core trading loop |
| `src/pearlalgo/market_agent/performance_tracker.py` | Trade tracking + trades.db |
| `src/pearlalgo/market_agent/signal_handler.py` | Signal processing |
| `src/pearlalgo/execution/tradovate/adapter.py` | Order execution adapter |
| `src/pearlalgo/execution/tradovate/client.py` | Tradovate API client |
| `src/pearlalgo/strategies/composite_intraday/engine.py` | Canonical live strategy bundle |
| `src/pearlalgo/trading_bots/pearl_bot_auto.py` | Legacy implementation bridge behind the canonical strategy wrappers |
| `src/pearlalgo/market_agent/state_manager.py` | Signal state machine |
| `config/live/tradovate_paper.yaml` | Canonical live runtime configuration |
| `config/accounts/tradovate_paper.yaml` | Legacy compatibility overlay; canonical live config is `config/live/tradovate_paper.yaml` |
| `apps/pearl-algo-app/` | Next.js web dashboard (standalone mode, port 3001) |
| `src/pearlalgo/api/server.py` | FastAPI API server (port 8001) |

## Data Insights

- Legacy signal gating is intentionally OFF on the canonical live path.
- Execution should remain disarmed until you explicitly re-arm it.
- Tradovate Paper is the sole live execution account; IBKR remains data-only.

## Pearl Algo Memory Bridge (REQUIRED at session end)

Write what was built to Pearl Algo's memory so the agent stays in sync with code changes:

**From px-core, the bridge runs remotely:**
```bash
# At end of every session, SSH to Mac and write journal entry:
ssh pearlassistant@$(tailscale ip -4 2>/dev/null || echo 'PEARL-Macbook')   "bash ~/.openclaw/pearl-workspace/scripts/cc-session-bridge.sh '$(cat <<SUMMARY
- [what was built/changed]
- [key decisions]
- [files changed]
- [status: tests passing/failing]
SUMMARY
)' 'pearl-algo'" 2>/dev/null || echo 'Bridge unavailable - manually update Pearl Algo MEMORY.md'
```

**What to include:**
- Algorithm changes and why
- Risk/circuit breaker logic changes
- Test results
- Anything Pearl Algo agent needs to know
