# ATS (Automated Trading System) Rollout Guide

This guide describes the safe rollout process for PearlAlgo's execution and learning layers.

## Overview

The ATS adds two capabilities to PearlAlgo:

1. **Execution Layer**: IBKR bracket order placement with bracket orders (entry + stop loss + take profit)
2. **Learning Layer**: Adaptive bandit policy that adjusts execution decisions based on signal type performance

Both are designed with **safety-first defaults**:
- Execution is **disabled** and **disarmed** by default
- Learning starts in **shadow mode** (observe only)

## Architecture

```
MarketData → Strategy → Signals → BanditPolicy → ExecutionAdapter → IBKR
                          ↓            ↓                ↓
                      State         State            State
                          ↓            ↓                ↓
                      Telegram     Telegram         Telegram
```

## Configuration

### Execution Configuration (`config/config.yaml`)

```yaml
execution:
  enabled: false                    # Master toggle
  armed: false                      # Runtime toggle (use /arm command)
  mode: "dry_run"                   # "dry_run", "paper", or "live"
  
  max_positions: 1                  # Maximum concurrent positions
  max_orders_per_day: 20            # Daily order limit
  max_daily_loss: 500.0             # Kill switch threshold ($)
  cooldown_seconds: 60              # Cooldown between orders per signal type
  
  symbol_whitelist:
    - MNQ
  
  ibkr_trading_client_id: 20        # Separate from data client
```

### Learning Configuration (`config/config.yaml`)

```yaml
learning:
  enabled: true                     # Master toggle
  mode: "shadow"                    # "shadow" (observe) or "live" (affects execution)
  
  min_samples_per_type: 10          # Minimum trades before policy has opinion
  explore_rate: 0.1                 # Random exploration rate (10%)
  decision_threshold: 0.3           # Skip signal if P(win) < 30%
  
  max_size_multiplier: 1.5          # Max size boost for high-confidence types
  min_size_multiplier: 0.5          # Min size reduction for low-confidence types
  
  prior_alpha: 2.0                  # Beta prior (optimistic start)
  prior_beta: 2.0
```

## Rollout Stages

### Stage A: Shadow Learning (Recommended Start)

**Settings:**
```yaml
execution:
  enabled: false
learning:
  enabled: true
  mode: "shadow"
```

**What Happens:**
- No orders are placed
- Policy learns from virtual PnL outcomes
- Decisions are logged but not acted upon
- Monitor via `/policy` command

**Duration:** 1-2 weeks or until 50+ virtual outcomes

**Verify:**
- Policy state file growing: `data/agent_state/<MARKET>/policy_state.json`
- Signal types being tracked
- Win rates aligning with expectations

### Stage B: Execution Dry Run

**Settings:**
```yaml
execution:
  enabled: true
  mode: "dry_run"
learning:
  enabled: true
  mode: "shadow"
```

**What Happens:**
- Execution adapter initializes
- All preconditions are checked
- Orders are **logged but not placed**
- Policy continues learning in shadow

**Duration:** 3-5 days

**Verify:**
- Logs show "DRY_RUN: Would place bracket order"
- Precondition checks working correctly
- No actual orders in IBKR

### Stage C: Paper Trading (Disarmed)

**Settings:**
```yaml
execution:
  enabled: true
  mode: "paper"
learning:
  enabled: true
  mode: "shadow"
```

**What Happens:**
- Execution connects to IBKR paper account
- Starts **disarmed** (no orders until `/arm`)
- Policy still in shadow mode

**Duration:** 1-2 weeks

**Steps:**
1. Deploy with above settings
2. Verify connection via `/positions`
3. When ready: `/arm` to start placing orders
4. Monitor via Telegram

**Verify:**
- Paper account shows orders
- Bracket orders (entry + SL + TP) placed correctly
- `/disarm` stops new orders

### Stage D: Paper Trading with Live Policy

**Settings:**
```yaml
execution:
  enabled: true
  mode: "paper"
learning:
  enabled: true
  mode: "live"
```

**What Happens:**
- Policy decisions **affect execution**
- Low-scoring signal types may be skipped
- Position sizes may be adjusted

**Duration:** 1-2 weeks

**Verify:**
- Skipped signals logged with policy reason
- Size adjustments happening
- Overall performance improving

### Stage E: Live Trading (Optional)

**⚠️ Only proceed if paper results are satisfactory**

**Settings:**
```yaml
execution:
  enabled: true
  mode: "live"
learning:
  enabled: true
  mode: "live"
```

**What Happens:**
- Real orders placed in live IBKR account
- Real money at risk
- Policy actively gating/adjusting

**Requirements before Stage E:**
- [ ] Minimum 100 paper trades completed
- [ ] Win rate > 50%
- [ ] Daily P&L positive on average
- [ ] Kill switch tested and working
- [ ] Backup disarm procedure documented

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/arm` | Arm execution adapter for order placement |
| `/disarm` | Disarm execution (stops new orders) |
| `/kill` | Cancel all orders AND disarm (emergency) |
| `/positions` | Show current positions and execution status |
| `/policy` | Show bandit policy status and signal type stats |

## Safety Features

### Hard Limits (Config-Enforced)
- `max_positions`: Prevents over-leveraging
- `max_orders_per_day`: Limits daily activity
- `max_daily_loss`: Kill switch triggers auto-disarm
- `cooldown_seconds`: Prevents rapid-fire orders

### Runtime Controls
- **Disarmed by default**: Must explicitly `/arm`
- **Kill switch**: `/kill` cancels all and disarms
- **Flag files**: Telegram commands write flag files for service to pick up

### Learning Safeguards
- **Shadow mode default**: Policy learns but doesn't affect execution
- **Minimum samples**: No opinion until enough data
- **Exploration**: Random execution prevents over-fitting

## Monitoring

### Log Indicators

**Execution:**
```
✅ Order placed: sr_bounce long | order_id=123
⚠️ Order placement failed: reason
Order skipped: not_armed | signal_id=abc123
```

**Policy:**
```
Policy decision: sr_bounce -> execute=True | score=0.72 | mode=shadow
BanditPolicy: WIN recorded for sr_bounce | pnl=$150.00 | new_win_rate=67%
```

### State Files
- `data/agent_state/<MARKET>/state.json`: Includes execution and learning status
- `data/agent_state/<MARKET>/policy_state.json`: Per-signal-type statistics
- `data/agent_state/<MARKET>/signals.jsonl`: Signal history with execution status

## Troubleshooting

### "Not connected to IBKR"
1. Check IBKR Gateway is running
2. Verify `ibkr_trading_client_id` differs from data client
3. Check port matches Gateway settings

### "execution_disabled"
- Set `execution.enabled: true` in config
- Restart service

### "not_armed"
- Use `/arm` command in Telegram
- Check that `execution.enabled: true`

### "symbol_not_whitelisted"
- Add symbol to `execution.symbol_whitelist`
- Restart service

### "max_positions_reached"
- Wait for existing position to close
- Or increase `max_positions`

### "daily_loss_limit_hit"
- Kill switch triggered
- Service will auto-disarm
- Reset with `/arm` next day

## Rollback Procedure

If issues occur:

1. **Immediate**: `/kill` to cancel all orders and disarm
2. **Config**: Set `execution.enabled: false`
3. **Restart**: Service will start with execution disabled
4. **Investigate**: Check logs and state files

## Best Practices

1. **Start slow**: Stage A shadow learning first
2. **Paper before live**: Always validate on paper
3. **Small positions**: Start with `max_positions: 1`
4. **Monitor actively**: Check Telegram regularly
5. **Keep kill switch ready**: `/kill` should be muscle memory
6. **Document everything**: Note changes and outcomes

## Files Reference

| File | Purpose |
|------|---------|
| `src/pearlalgo/execution/` | Execution adapter layer |
| `src/pearlalgo/learning/` | Bandit policy layer |
| `config/config.yaml` | Configuration (execution + learning blocks) |
| `data/agent_state/<MARKET>/policy_state.json` | Persisted policy statistics |
| `tests/test_bandit_policy.py` | Bandit policy tests |
| `tests/test_execution_adapter.py` | Execution adapter tests |


