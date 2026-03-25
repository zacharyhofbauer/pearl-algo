# PearlAlgo - Claude Code Instructions

**WARNING: This is a LIVE 24/7 automated futures trading system. Every code change can cause real financial loss.**

## Architecture

- **Market data:** IBKR gateway (data only, NOT used for execution)
- **Order execution:** Tradovate (paper account = source of truth for trades)
- **Notifications:** Telegram
- **Entry point:** `pearl.sh` (master control), `python -m pearlalgo.market_agent.main`
- **Config hierarchy:** `config/base.yaml` (defaults) + `config/accounts/tradovate_paper.yaml` (overrides)
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
| `circuit_breaker.*` | current values | Drawdown protection |
| `virtual_pnl.*` | disabled | Not used, Tradovate is source of truth |
| `ibkr.execution` | inactive | IBKR is data-only |

## Config Rules

- **YAML duplicate keys are SILENT** — last key wins, no error. Always check BOTH config files for duplicates before editing.
- Override hierarchy: `tradovate_paper.yaml` values override `base.yaml` values.
- Always validate YAML after editing: `python -c "import yaml; yaml.safe_load(open('config/base.yaml'))"`

## Forbidden Actions

1. Do NOT re-enable IBKR execution
2. Do NOT increase contract sizes above 1
3. Do NOT disable circuit breaker or drawdown limits
4. Do NOT enable virtual PnL
5. Do NOT change session filter settings without user approval
6. Do NOT restart the trading service without user approval
7. Do NOT change circuit breaker mode back to shadow/warn_only without user approval
8. Do NOT disable direction gating or regime avoidance without user approval

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
| `src/pearlalgo/trading_bots/pearl_bot_auto.py` | Signal generation (PineScript logic) |
| `src/pearlalgo/market_agent/state_manager.py` | Signal state machine |
| `config/base.yaml` | Base configuration |
| `config/accounts/tradovate_paper.yaml` | Account-specific overrides |
| `pearlalgo_web_app/` | Next.js web dashboard (standalone mode, port 3001) |
| `src/pearlalgo/api/server.py` | FastAPI API server (port 8001) |

## Data Insights (from 1,617-trade backtest, 2026-02-17 to 2026-03-25)

- Circuit breaker is in **enforce** mode — it will block trades that violate risk limits
- Direction gating is ON — longs blocked in downtrends, shorts blocked in uptrends
- Regime avoidance is ON — trades blocked in ranging/volatile regimes
- 3-loss cooldown (30-min pause) is the most impactful filter (accounts for 70% of drawdown reduction)
- Session filter is intentionally OFF — user wants all hours open for OpenClaw agent decisions
- `min_confidence` stays at 0.40 — raising it interacts badly with regime multipliers

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
)' 'pearl-algo-workspace'" 2>/dev/null || echo 'Bridge unavailable - manually update Pearl Algo MEMORY.md'
```

**What to include:**
- Algorithm changes and why
- Risk/circuit breaker logic changes
- Test results
- Anything Pearl Algo agent needs to know
