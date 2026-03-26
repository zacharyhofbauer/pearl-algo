# Verify pearl_bot_auto Sends Trades to Tradovate

## Quick checklist

1. **Config** — Tradovate Paper uses `config/accounts/tradovate_paper.yaml`:
   - `execution.enabled: true`
   - `execution.armed: true`
   - `execution.adapter: tradovate`
   - `execution.symbol_whitelist: [MNQ]`

2. **Agent running** — Tradovate Paper agent must be up and not paused:
   ```bash
   ./scripts/lifecycle/tv_paper_eval.sh status
   tail -5 logs/agent_TV_PAPER.log   # no "Service paused"
   ```

3. **Follower mode** — On startup you should see in `logs/agent_TV_PAPER.log`:
   ```
   Tradovate Paper: signal follower mode ON — strategy signals execute via follower_execute -> place_bracket (Tradovate)
   ```
   If that line appears, every signal from `pearl_bot_auto` is sent to Tradovate (no ML/bandit gating).

4. **Strategy must generate signals** — Trades only occur when the strategy returns a signal (e.g. EMA crossover). In logs you’ll see either:
   - `Processing N signal(s) from strategy analysis` then `Signal 1/N: ...` → execution path runs.
   - `No signals generated` or `NoOpportunity` → no trade this cycle (normal when there’s no setup).

5. **Confirm orders on Tradovate** — When a signal is executed you should see in `logs/agent_TV_PAPER.log`:
   - `Tradovate place_oso request: signal=... action=Buy/Sell symbol=MNQ...`
   - `✅ Order placed: <type> <direction> | order_id=...`
   Or if skipped: `Order skipped: <reason>`

## Commands to confirm flow

```bash
# 1. Config has execution enabled + armed + tradovate
grep -A2 '^execution:' config/accounts/tradovate_paper.yaml
grep -E 'enabled|armed|adapter' config/accounts/tradovate_paper.yaml | head -5

# 2. Agent is running and follower mode is on
./scripts/lifecycle/tv_paper_eval.sh status
grep -E "signal follower mode ON|Execution adapter initialized.*tradovate" logs/agent_TV_PAPER.log | tail -2

# 3. Watch for signals and Tradovate orders (run during session)
tail -f logs/agent_TV_PAPER.log | grep -E "Processing.*signal|place_oso|Order placed|Order skipped|No signals"
```

## If no trades appear

- **No signals** — Strategy has no setup (e.g. no crossover). Wait for session and conditions; no code change needed.
- **Order skipped** — Check the reason in the log (e.g. `not_armed`, `cooldown_active`, `symbol_not_whitelisted`, `max_positions_reached`). Fix config or wait for cooldown.
- **place_oso REJECTED/ERROR** — Tradovate API or risk rule (e.g. position conflict). Check log line for details.
