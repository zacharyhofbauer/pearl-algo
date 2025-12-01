# 📊 Running Multiple Symbols (ES, NQ, GC)

## Quick Answer

The agent **already supports multiple symbols**! Just add them to the command:

```bash
python scripts/automated_trading.py --symbols ES NQ --strategy sr --interval 300
```

## Full Examples

### Run ES and NQ Together
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

python scripts/automated_trading.py \
  --symbols ES NQ \
  --strategy sr \
  --interval 300 \
  --tiny-size 1
```

### Run All Three (ES, NQ, GC)
```bash
python scripts/automated_trading.py \
  --symbols ES NQ GC \
  --strategy sr \
  --interval 300
```

### Run with Different Strategies (Advanced)
Currently, all symbols use the same strategy. If you want different strategies per symbol, you'd need to run separate instances (see below).

## How It Works

The agent processes **each symbol sequentially** in every cycle:

```
Cycle #1
  🔍 Analyzing ES
    [Analysis and trade decision]
  
  🔍 Analyzing NQ
    [Analysis and trade decision]
  
  📊 Cycle Summary
    Symbols Processed: 2
    Trades Today: 2
```

## Running Separate Instances (Different Strategies)

If you want ES and NQ to use **different strategies**, run them in separate terminals:

### Terminal 1: ES with sr strategy
```bash
python scripts/automated_trading.py \
  --symbols ES \
  --strategy sr \
  --interval 300 \
  --ib-client-id 1
```

### Terminal 2: NQ with ma_cross strategy
```bash
python scripts/automated_trading.py \
  --symbols NQ \
  --strategy ma_cross \
  --interval 300 \
  --ib-client-id 2
```

**Important**: Use different `--ib-client-id` values (1, 2, 3...) to avoid connection conflicts!

## Using Screen/Tmux for Multiple Instances

### Option 1: Separate Screen Sessions
```bash
# Terminal 1: ES
screen -S trading-es
python scripts/automated_trading.py --symbols ES --strategy sr --interval 300 --ib-client-id 1
# Detach: Ctrl+A then D

# Terminal 2: NQ
screen -S trading-nq
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 300 --ib-client-id 2
# Detach: Ctrl+A then D

# Later, reattach:
screen -r trading-es
screen -r trading-nq
```

### Option 2: Tmux with Multiple Windows
```bash
# Start tmux
tmux new -s trading

# Window 1: ES
python scripts/automated_trading.py --symbols ES --strategy sr --interval 300 --ib-client-id 1

# Create new window: Ctrl+B then C
# Window 2: NQ
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 300 --ib-client-id 2

# Switch windows: Ctrl+B then 0 or 1
# Detach: Ctrl+B then D
```

## Recommended Setup

### For Same Strategy (Easiest)
**Run both in one command:**
```bash
python scripts/automated_trading.py --symbols ES NQ --strategy sr --interval 300
```

### For Different Strategies
**Run in separate screen/tmux sessions:**
```bash
# Screen session 1: ES
screen -S es-sr
python scripts/automated_trading.py --symbols ES --strategy sr --interval 300 --ib-client-id 1

# Screen session 2: NQ  
screen -S nq-ma
python scripts/automated_trading.py --symbols NQ --strategy ma_cross --interval 300 --ib-client-id 2
```

## What You'll See

When running multiple symbols, each cycle processes all symbols:

```
Cycle #1 - 2025-01-27 14:30:00 UTC

┌─────────────────────────────────────────────┐
│  🔍 Analyzing ES                             │
└─────────────────────────────────────────────┘

📊 Fetching market data for ES...
✅ Data received: 192 bars, latest price: $6,853.50
🧠 Generating sr signal...

🤔 Analysis: ES
[Analysis table]

✅ EXECUTING: LONG 1 contract(s) @ $6,853.50

┌─────────────────────────────────────────────┐
│  🔍 Analyzing NQ                             │
└─────────────────────────────────────────────┘

📊 Fetching market data for NQ...
✅ Data received: 192 bars, latest price: $25,473.50
🧠 Generating sr signal...

🤔 Analysis: NQ
[Analysis table]

⚪ NQ: FLAT signal - No trade opportunity

📊 Cycle Summary
✅ Cycle #1 Complete
Symbols Processed: 2
Trades Today: 1
Daily P&L: $0.00
Open Positions: 1
Next cycle in 300s
```

## Configuration Tips

### Risk Limits Per Symbol
The risk profile applies to **all symbols combined**. If you set:
- `daily_loss_limit: 2500.0`
- `max_contracts_by_symbol: {ES: 2, NQ: 2}`

Then:
- Total daily loss limit: $2,500 (shared across all symbols)
- Max ES contracts: 2
- Max NQ contracts: 2

### Interval Timing
All symbols are processed in the **same cycle**. If you set `--interval 300`:
- Every 5 minutes, it processes ES, then NQ, then waits 5 minutes
- Both symbols use the same cycle timing

## Quick Start Commands

### Same Strategy (Recommended)
```bash
# ES and NQ with sr strategy
python scripts/automated_trading.py --symbols ES NQ --strategy sr --interval 300
```

### All Three Symbols
```bash
# ES, NQ, and GC
python scripts/automated_trading.py --symbols ES NQ GC --strategy sr --interval 300
```

### Different Strategies (Separate Instances)
```bash
# Terminal 1
screen -S es
python scripts/automated_trading.py --symbols ES --strategy sr --interval 300 --ib-client-id 1

# Terminal 2  
screen -S nq
python scripts/automated_trading.py --symbols NQ --strategy ma_cross --interval 300 --ib-client-id 2
```

---

**Easiest way: Just add both symbols to one command!** 🚀

```bash
python scripts/automated_trading.py --symbols ES NQ --strategy sr --interval 300
```

