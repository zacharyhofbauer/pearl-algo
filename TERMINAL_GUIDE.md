# 🚀 Professional Trading Terminal & Strategies Guide

## New Features

### 1. Professional Trading Terminal

Launch a multi-panel real-time trading terminal:

```bash
# Start terminal (default 1s refresh)
pearlalgo terminal

# Custom refresh rate (0.5s for ultra-fast updates)
pearlalgo terminal --refresh 0.5
```

**Features:**
- 📊 Real-time positions and P&L tracking
- 📋 Active orders monitoring
- 📈 Live market data (when connected to broker)
- 📊 Performance metrics dashboard
- 📡 Latest trading signals
- 📈 ASCII chart visualization

### 2. Scalping Strategy

Fast-paced trading strategy for 1-5 minute timeframes:

```bash
# Trade with scalping strategy (60 second intervals)
pearlalgo trade auto ES NQ --strategy scalping --interval 60

# With micro contracts
pearlalgo trade auto MES MNQ --strategy scalping --interval 60 --tiny-size 3
```

**Strategy Details:**
- Uses 9/21 EMA for trend direction
- RSI (14) for overbought/oversold signals
- ATR-based stop loss and take profit
- Volume spike confirmation
- Quick exits (max 5 bars hold)
- Best for: 1-5 minute timeframes

**Parameters:**
- `fast_ema`: 9 (default)
- `slow_ema`: 21 (default)
- `rsi_period`: 14 (default)
- `rsi_oversold`: 30 (default)
- `rsi_overbought`: 70 (default)
- `atr_multiplier`: 1.5 (default)
- `max_hold_bars`: 5 (default)

### 3. Intraday Swing Strategy

Holds positions for hours, targets 1-3% moves:

```bash
# Trade with intraday swing strategy (15 minute intervals)
pearlalgo trade auto ES NQ GC --strategy intraday_swing --interval 900

# With standard contracts
pearlalgo trade auto ES NQ --strategy intraday_swing --interval 900
```

**Strategy Details:**
- Uses 50 EMA for trend direction
- 20 EMA for entry timing
- ADX for trend strength (threshold: 25)
- Targets 1-3% moves
- Holds for 1-4 hours
- Best for: 15-60 minute timeframes

**Parameters:**
- `trend_ema`: 50 (default)
- `entry_ema`: 20 (default)
- `adx_threshold`: 25 (default)
- `min_move_target`: 0.01 (1% default)
- `stop_loss_pct`: 0.005 (0.5% default)
- `max_hold_bars`: 16 (default)

### 4. Enhanced Execution Agent

Advanced order types with stop loss and take profit:

The `ExecutionAgent` now supports:
- Market orders (default)
- Limit orders
- Stop loss orders (automatic)
- Take profit orders (automatic)

When using strategies that return `stop_loss` and `take_profit` in the signal, the execution agent will automatically place these orders.

## Quick Start Examples

### Scalping Setup (Fast Trading)
```bash
# 1. Start terminal in one window
pearlalgo terminal

# 2. Start scalping in another window
pearlalgo trade auto MES MNQ --strategy scalping --interval 60 --tiny-size 2
```

### Intraday Swing Setup (Longer Holds)
```bash
# 1. Start terminal
pearlalgo terminal

# 2. Start swing trading
pearlalgo trade auto ES NQ GC --strategy intraday_swing --interval 900
```

### Multi-Strategy Setup
```bash
# Terminal 1: Terminal dashboard
pearlalgo terminal

# Terminal 2: Scalping on micro contracts
pearlalgo trade auto MES MNQ --strategy scalping --interval 60

# Terminal 3: Swing trading on standard contracts
pearlalgo trade auto ES NQ --strategy intraday_swing --interval 900
```

## Strategy Comparison

| Feature | Scalping | Intraday Swing |
|---------|----------|----------------|
| **Timeframe** | 1-5 min | 15-60 min |
| **Hold Time** | 5 bars max | 1-4 hours |
| **Target** | ATR-based | 1-3% moves |
| **Stop Loss** | ATR-based | 0.5% |
| **Best For** | Fast markets, high volatility | Trending markets |
| **Risk** | Lower per trade, more trades | Higher per trade, fewer trades |

## Tips

1. **Start with Micro Contracts**: Always test new strategies with micro contracts (MES, MNQ, etc.) first
2. **Monitor Terminal**: Keep the terminal open to watch positions and P&L in real-time
3. **Use Appropriate Intervals**: 
   - Scalping: 60-300 seconds (1-5 min)
   - Swing: 900-3600 seconds (15-60 min)
4. **Risk Management**: Both strategies include automatic stop loss and take profit
5. **Volume Matters**: Scalping strategy requires volume confirmation

## Troubleshooting

### Terminal shows "No data"
- Make sure trading is running in another terminal
- Check that signals are being generated: `ls signals/`
- Verify performance log exists: `ls data/performance/`

### Strategies not found
- Make sure you've activated the virtual environment: `source .venv/bin/activate`
- Reinstall the package: `pip install -e .`

### Orders not executing
- Check IB Gateway is running: `pearlalgo gateway status`
- Verify connection: `python scripts/test_broker_connection.py`
- Check logs: `tail -f logs/micro_trading.log`

## Next Steps

1. **Customize Strategies**: Edit parameters in the strategy files to match your trading style
2. **Add More Strategies**: Use the `@register_strategy` decorator to add your own
3. **Enhance Terminal**: Add more panels, charts, or custom metrics
4. **Backtest First**: Always backtest strategies before live trading

---

*Happy Trading! 🚀*

