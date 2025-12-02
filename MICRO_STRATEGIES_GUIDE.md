# 🚀 Micro Strategies Guide - Start All Strategies

## Quick Start

### Start All Micro Strategies (One Command)

```bash
bash scripts/start_all_micro_strategies.sh
```

This starts:
- **Scalping** on MES, MNQ (fast trading, 60s intervals)
- **Intraday Swing** on MGC, MYM (longer holds, 15min intervals)
- **SR** on MCL (support/resistance, 5min intervals)

### Stop All Micro Strategies

```bash
bash scripts/stop_all_micro_strategies.sh
```

## What Gets Started

### Strategy 1: Scalping (MES, MNQ)
- **Symbols:** MES (Micro E-mini S&P), MNQ (Micro E-mini Nasdaq)
- **Strategy:** scalping
- **Interval:** 60 seconds (1 minute)
- **Size:** 2 contracts
- **Client ID:** 10
- **Logs:** 
  - `logs/micro_scalping_trading.log`
  - `logs/micro_scalping_console.log`

### Strategy 2: Intraday Swing (MGC, MYM)
- **Symbols:** MGC (Micro Gold), MYM (Micro E-mini Dow)
- **Strategy:** intraday_swing
- **Interval:** 900 seconds (15 minutes)
- **Size:** 3 contracts
- **Client ID:** 11
- **Logs:**
  - `logs/micro_swing_trading.log`
  - `logs/micro_swing_console.log`

### Strategy 3: SR (MCL)
- **Symbols:** MCL (Micro Crude Oil)
- **Strategy:** sr (support/resistance)
- **Interval:** 300 seconds (5 minutes)
- **Size:** 2 contracts
- **Client ID:** 12
- **Logs:**
  - `logs/micro_sr_trading.log`
  - `logs/micro_sr_console.log`

## Monitoring

### Option 1: Professional Terminal (Recommended)
```bash
pearlalgo terminal
```
Shows all positions, P&L, orders, and signals in real-time.

### Option 2: Status Dashboard
```bash
python scripts/status_dashboard.py --live
```

### Option 3: Live Trading Feed
```bash
pearlalgo monitor --live-feed
```

### Option 4: View Logs
```bash
# Scalping
tail -f logs/micro_scalping_trading.log
tail -f logs/micro_scalping_console.log

# Intraday Swing
tail -f logs/micro_swing_trading.log
tail -f logs/micro_swing_console.log

# SR
tail -f logs/micro_sr_trading.log
tail -f logs/micro_sr_console.log
```

## Customization

### Edit the Script

Edit `scripts/start_all_micro_strategies.sh` to customize:

- **Symbols:** Change which micro contracts to trade
- **Strategies:** Change strategy names
- **Intervals:** Adjust signal check intervals
- **Sizes:** Change contract sizes
- **Client IDs:** Use different IB client IDs (must be unique)

### Example: Add More Strategies

Add to the script:
```bash
# Strategy 4: MA Cross on MES
nohup pearlalgo --verbosity VERBOSE trade auto \
  MES \
  --strategy ma_cross \
  --interval 300 \
  --tiny-size 2 \
  --ib-client-id 13 \
  --log-file logs/micro_ma_trading.log \
  --log-level INFO > logs/micro_ma_console.log 2>&1 &
```

## Prerequisites

1. **IB Gateway Running:**
   ```bash
   pearlalgo gateway start --wait
   ```

2. **Virtual Environment Activated:**
   ```bash
   source .venv/bin/activate
   ```

3. **Config File Exists:**
   ```bash
   ls config/micro_strategy_config.yaml
   ```

## Troubleshooting

### Strategies Not Starting

1. **Check IB Gateway:**
   ```bash
   pearlalgo gateway status
   ```

2. **Check Connection:**
   ```bash
   python scripts/test_broker_connection.py
   ```

3. **Check Logs:**
   ```bash
   tail -50 logs/micro_scalping_console.log
   ```

### Port Conflicts

If you see "client ID already in use" errors:
- Each strategy needs a unique `--ib-client-id`
- Default script uses: 10, 11, 12
- Change in the script if needed

### Strategies Stopped Unexpectedly

1. **Check if processes are running:**
   ```bash
   ps aux | grep "pearlalgo trade auto"
   ```

2. **Check logs for errors:**
   ```bash
   grep -i error logs/micro_*_console.log
   ```

3. **Restart:**
   ```bash
   bash scripts/stop_all_micro_strategies.sh
   bash scripts/start_all_micro_strategies.sh
   ```

## Manual Control

### Start Individual Strategies

```bash
# Scalping only
pearlalgo trade auto MES MNQ --strategy scalping --interval 60 --tiny-size 2 --ib-client-id 10

# Swing only
pearlalgo trade auto MGC MYM --strategy intraday_swing --interval 900 --tiny-size 3 --ib-client-id 11

# SR only
pearlalgo trade auto MCL --strategy sr --interval 300 --tiny-size 2 --ib-client-id 12
```

### Stop Individual Strategies

```bash
# Find PID
ps aux | grep "pearlalgo trade auto" | grep "scalping"

# Kill specific process
kill <PID>
```

## Performance Tips

1. **Use Terminal Dashboard:** Best way to monitor all strategies at once
2. **Check Logs Regularly:** Monitor for errors or issues
3. **Start with Small Sizes:** Use `--tiny-size 1` or `2` initially
4. **Monitor Risk:** Keep an eye on daily P&L and risk status
5. **Different Client IDs:** Each strategy needs unique IB client ID

## Quick Reference

```bash
# Start all
bash scripts/start_all_micro_strategies.sh

# Stop all
bash scripts/stop_all_micro_strategies.sh

# Monitor
pearlalgo terminal

# View logs
tail -f logs/micro_scalping_trading.log
```

---

**Happy Trading! 🚀**

