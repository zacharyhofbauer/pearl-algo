# 🚀 Quick Start: How to Start Trading Strategies

## Prerequisites

1. **Activate your environment:**
   ```bash
   cd ~/pearlalgo-dev-ai-agents
   source .venv/bin/activate
   ```

2. **Start IB Gateway:**
   ```bash
   pearlalgo gateway start --wait
   ```

3. **Verify connection:**
   ```bash
   python scripts/test_broker_connection.py
   ```

## Available Strategies

### 1. Scalping Strategy (Fast Trading)
- **Best for:** 1-5 minute timeframes
- **Hold time:** 5 bars maximum
- **Use with:** Micro contracts (MES, MNQ, etc.)

### 2. Intraday Swing Strategy (Longer Holds)
- **Best for:** 15-60 minute timeframes  
- **Hold time:** 1-4 hours
- **Use with:** Standard contracts (ES, NQ, GC, etc.)

### 3. Support/Resistance (SR) - Original
- **Best for:** 15 minute timeframes
- **Use with:** Any contracts

### 4. Moving Average Crossover (MA Cross) - Original
- **Best for:** 15 minute timeframes
- **Use with:** Any contracts

## Starting Strategies

### Basic Command Format

```bash
pearlalgo trade auto [SYMBOLS] --strategy [STRATEGY] --interval [SECONDS] [OPTIONS]
```

### Example 1: Scalping with Micro Contracts

```bash
# Fast scalping on micro E-mini contracts (60 second intervals)
pearlalgo trade auto MES MNQ --strategy scalping --interval 60 --tiny-size 2
```

**What this does:**
- Trades MES (Micro E-mini S&P) and MNQ (Micro E-mini Nasdaq)
- Uses scalping strategy (fast entries/exits)
- Checks for signals every 60 seconds
- Uses 2 contracts per trade (micro size)

### Example 2: Intraday Swing with Standard Contracts

```bash
# Swing trading on standard contracts (15 minute intervals = 900 seconds)
pearlalgo trade auto ES NQ GC --strategy intraday_swing --interval 900
```

**What this does:**
- Trades ES (E-mini S&P), NQ (E-mini Nasdaq), GC (Gold)
- Uses intraday swing strategy (holds for hours)
- Checks for signals every 15 minutes (900 seconds)
- Uses standard contract sizes

### Example 3: Original SR Strategy

```bash
# Support/Resistance strategy (5 minute intervals)
pearlalgo trade auto ES NQ GC --strategy sr --interval 300
```

### Example 4: Multiple Symbols with Options

```bash
# Using --symbols flag instead of positional arguments
pearlalgo trade auto --symbols ES --symbols NQ --symbols GC --strategy scalping --interval 60 --tiny-size 3
```

## Recommended Setups

### Setup 1: Scalping Day Trading (Fast Pace)

**Terminal 1 - Terminal Dashboard:**
```bash
pearlalgo terminal
```

**Terminal 2 - Scalping Strategy:**
```bash
pearlalgo trade auto MES MNQ MYM --strategy scalping --interval 60 --tiny-size 2
```

**Settings:**
- Symbols: MES, MNQ, MYM (micro contracts)
- Strategy: scalping
- Interval: 60 seconds (1 minute)
- Size: 2 contracts

### Setup 2: Swing Trading (Longer Holds)

**Terminal 1 - Terminal Dashboard:**
```bash
pearlalgo terminal
```

**Terminal 2 - Swing Strategy:**
```bash
pearlalgo trade auto ES NQ GC --strategy intraday_swing --interval 900
```

**Settings:**
- Symbols: ES, NQ, GC (standard contracts)
- Strategy: intraday_swing
- Interval: 900 seconds (15 minutes)
- Size: Default (risk-adjusted)

### Setup 3: Multi-Strategy (Advanced)

**Terminal 1 - Terminal Dashboard:**
```bash
pearlalgo terminal
```

**Terminal 2 - Scalping (Micro):**
```bash
pearlalgo trade auto MES MNQ --strategy scalping --interval 60 --tiny-size 2
```

**Terminal 3 - Swing (Standard):**
```bash
pearlalgo trade auto ES NQ --strategy intraday_swing --interval 900
```

## Command Options

### Required Options
- `--strategy`: Strategy name (scalping, intraday_swing, sr, ma_cross)
- `--interval`: How often to check for signals (in seconds)

### Optional Options
- `--symbols`: Trading symbols (can repeat multiple times)
- `--tiny-size`: Contract size for micro contracts
- `--profile-config`: Custom risk profile config file
- `--ib-client-id`: Override IB Gateway client ID
- `--log-file`: Custom log file path
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR)

## Interval Recommendations

| Strategy | Recommended Interval | Timeframe |
|----------|---------------------|-----------|
| **scalping** | 60-300 seconds | 1-5 minutes |
| **intraday_swing** | 900-3600 seconds | 15-60 minutes |
| **sr** | 300-900 seconds | 5-15 minutes |
| **ma_cross** | 300-900 seconds | 5-15 minutes |

## Monitoring Your Strategies

### View Terminal Dashboard
```bash
pearlalgo terminal
```

### View Live Trading Feed
```bash
pearlalgo monitor --live-feed
```

### View Status Dashboard
```bash
python scripts/status_dashboard.py --live
```

### Check Logs
```bash
# Trading logs
tail -f logs/micro_trading.log
tail -f logs/standard_trading.log

# Console output
tail -f logs/micro_console.log
```

## Stopping Strategies

### Stop All Trading
```bash
bash scripts/kill_my_processes.sh
```

### Or manually:
```bash
pkill -f "pearlalgo trade auto"
```

## Troubleshooting

### Strategy Not Found
```bash
# Check available strategies
python -c "from pearlalgo.strategies.base import list_strategies; print(list_strategies())"
```

### Gateway Not Connected
```bash
# Check gateway status
pearlalgo gateway status

# Start gateway
pearlalgo gateway start --wait

# Test connection
python scripts/test_broker_connection.py
```

### No Signals Generated
- Check that market is open
- Verify data is being fetched (check logs)
- Ensure strategy parameters are appropriate for current market conditions

## Quick Reference

```bash
# Start scalping
pearlalgo trade auto MES MNQ --strategy scalping --interval 60 --tiny-size 2

# Start swing trading
pearlalgo trade auto ES NQ GC --strategy intraday_swing --interval 900

# Start original SR strategy
pearlalgo trade auto ES NQ --strategy sr --interval 300

# View terminal
pearlalgo terminal

# Stop all trading
bash scripts/kill_my_processes.sh
```

---

**Happy Trading! 🚀**

