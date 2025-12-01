# ⚡ Micro Contracts Fast-Paced Strategy Guide

## Overview

This setup allows you to trade **micro futures contracts** at a faster pace with higher contract counts (3-5 contracts at a time).

### Micro Contracts Available:
- **MGC** - Micro Gold (1/10th of GC)
- **MYM** - Micro E-mini Dow (1/5th of YM)
- **MRTY** - Micro Russell 2000 (1/10th of RTY)
- **MCL** - Micro Crude Oil (1/10th of CL)
- **MNQ** - Micro NASDAQ (1/10th of NQ)
- **MES** - Micro S&P 500 (1/10th of ES)

## Why Micro Contracts?

✅ **Lower Risk**: Smaller tick values = smaller dollar moves
✅ **Higher Contract Counts**: Can trade 3-5 contracts safely
✅ **Faster Pace**: Shorter intervals (1 minute vs 5 minutes)
✅ **More Opportunities**: More frequent signals and trades

## Quick Start

### Option 1: Just Micro Contracts (Fast Pace)
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Run micro strategy
bash scripts/run_micro_strategy.sh
```

Or manually:
```bash
python scripts/automated_trading.py \
  --symbols MGC MYM MRTY MCL \
  --strategy sr \
  --interval 60 \
  --tiny-size 3 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 10
```

### Option 2: Both Regular + Micro (Recommended)
```bash
# Runs both strategies in separate screen sessions
bash scripts/run_all_strategies.sh
```

This starts:
- **Regular contracts** (ES, NQ, GC, YM, RTY, CL) - 5min intervals, 1-2 contracts
- **Micro contracts** (MGC, MYM, MRTY, MCL) - 1min intervals, 3-5 contracts

## Configuration

### Micro Strategy Config (`config/micro_strategy_config.yaml`)

```yaml
name: micro_fast
max_trades: 50  # Higher for faster pace
cooldown_minutes: 30  # Shorter cooldown

# Micro contracts: 3-5 contracts
max_contracts_by_symbol:
  MGC: 5
  MYM: 5
  MRTY: 5
  MCL: 5

# Smaller tick values (less risk per contract)
tick_values_by_symbol:
  MGC: 1.0   # $1 per tick (vs GC: $10)
  MYM: 0.5   # $0.50 per tick (vs YM: $5)
  MRTY: 0.50 # $0.50 per tick (vs RTY: $5)
  MCL: 1.0   # $1 per tick (vs CL: $10)
```

## Strategy Comparison

| Feature | Regular Contracts | Micro Contracts |
|---------|-------------------|-----------------|
| **Symbols** | ES, NQ, GC, YM, RTY, CL | MGC, MYM, MRTY, MCL |
| **Interval** | 300s (5 min) | 60s (1 min) |
| **Contracts** | 1-2 | 3-5 |
| **Tick Value** | $5-$20 per tick | $0.50-$1 per tick |
| **Risk per Contract** | Higher | Lower |
| **Pace** | Slower, more deliberate | Faster, more frequent |

## Running Both Strategies

### Using Screen Sessions

```bash
# Start regular contracts
screen -S regular
python scripts/automated_trading.py \
  --symbols ES NQ GC YM RTY CL \
  --strategy sr \
  --interval 300 \
  --tiny-size 1 \
  --ib-client-id 1

# In new terminal, start micro contracts
screen -S micro
python scripts/automated_trading.py \
  --symbols MGC MYM MRTY MCL \
  --strategy sr \
  --interval 60 \
  --tiny-size 3 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 10
```

### Using the Helper Script

```bash
bash scripts/run_all_strategies.sh
```

This automatically starts both in screen sessions.

## Monitoring

### View Regular Contracts
```bash
screen -r regular-contracts
```

### View Micro Contracts
```bash
screen -r micro-contracts
```

### List All Sessions
```bash
screen -ls
```

### Health Check
```bash
python scripts/health_check.py
```

## Contract Details

### Micro Gold (MGC)
- **Full Contract**: GC (Gold)
- **Size**: 1/10th of GC
- **Tick Value**: $1 per tick (vs GC: $10)
- **Max Contracts**: 5 (vs GC: 2)

### Micro Dow (MYM)
- **Full Contract**: YM (E-mini Dow)
- **Size**: 1/5th of YM
- **Tick Value**: $0.50 per tick (vs YM: $5)
- **Max Contracts**: 5 (vs YM: 2)

### Micro Russell (MRTY)
- **Full Contract**: RTY (Russell 2000)
- **Size**: 1/10th of RTY
- **Tick Value**: $0.50 per tick (vs RTY: $5)
- **Max Contracts**: 5 (vs RTY: 2)

### Micro Crude (MCL)
- **Full Contract**: CL (Crude Oil)
- **Size**: 1/10th of CL
- **Tick Value**: $1 per tick (vs CL: $10)
- **Max Contracts**: 5 (vs CL: 2)

## Risk Management

### Micro Contracts Advantages:
- **Lower dollar risk per contract**: $0.50-$1 per tick vs $5-$20
- **Can trade more contracts**: 3-5 micro = same risk as 1 regular
- **Faster pace**: More opportunities, quicker decisions

### Example Risk Comparison:

**Regular Contract (ES):**
- 1 contract, $12.50 per tick
- 10 tick move = $125

**Micro Contract (MES):**
- 5 contracts, $1.25 per tick
- 10 tick move = $62.50 (5 contracts × $12.50)

**Same market move, half the risk!**

## Performance Tracking

Both strategies log to separate files:
- Regular: `logs/regular_trading.log`
- Micro: `logs/micro_trading.log`

Performance data: `data/performance/futures_decisions.csv`

## Tips

1. **Start with micro only** to get comfortable with faster pace
2. **Monitor both** if running simultaneously
3. **Adjust contract counts** in config based on performance
4. **Use different client IDs** to avoid conflicts
5. **Watch risk limits** - micro allows more trades but still respect daily limits

## Troubleshooting

### "Symbol not found" errors
- Verify micro contract symbols are correct: MGC, MYM, MRTY, MCL
- Check IB Gateway has access to micro contracts
- Some brokers require separate permissions for micro contracts

### Too many trades
- Reduce `max_trades` in config
- Increase `cooldown_minutes`
- Increase `interval` (e.g., 120s instead of 60s)

### Connection conflicts
- Use different `--ib-client-id` values (1 for regular, 10 for micro)
- Ensure IB Gateway allows multiple client connections

---

**Ready to trade faster? Start with micro contracts!** ⚡

```bash
bash scripts/run_micro_strategy.sh
```

