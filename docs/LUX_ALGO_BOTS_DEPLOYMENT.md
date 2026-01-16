# Lux Algo Chart Prime Style Automated Trading Bots

## Overview

This implementation provides **Lux Algo Chart Prime style automated trading bots** for your PEARLalgo NQ trading system. Each "agent" (as you referred to them) is a **complete, self-contained automated trading strategy** inspired by Lux Algo's AI Strategy Alerts system.

Unlike simple indicators, these are **full trading systems** with:
- Complete indicator suites (PAC/S&O/OSC equivalent)
- Automated entry/exit logic
- Risk management and position sizing
- Performance tracking and optimization
- Webhook alerts for automation

## Available Bots

### 1. TrendFollowerBot - Trend Following Strategy
**Inspired by Lux Algo's Signals & Overlays (S&O) toolkit**
- Identifies strong trends using moving averages and momentum
- Enters on pullbacks within trending markets
- Uses volatility-adjusted stops and targets
- Best for: Trending market conditions

### 2. BreakoutBot - Breakout Trading Strategy
**Inspired by Lux Algo's Price Action Concepts (PAC) toolkit**
- Identifies consolidation patterns with volatility contraction
- Trades breakouts with volume and momentum confirmation
- Uses pattern-based stops and measured targets
- Best for: Ranging markets with clear breakouts

### 3. MeanReversionBot - Mean Reversion Strategy
**Inspired by Lux Algo's Oscillator Matrix (OSC) toolkit**
- Identifies overbought/oversold conditions using multiple oscillators
- Detects divergence patterns for higher-probability entries
- Uses volatility-based targets and time-based exits
- Best for: Ranging markets (higher risk)

## Quick Start Deployment

### Step 1: Enable Lux Algo Bots in Configuration

Add this to your `config/config.yaml`:

```yaml
lux_algo_bots:
  enabled: true
  bots:
    trend_follower:
      enabled: true
      description: "Trend-following bot"
      bot_class: "TrendFollowerBot"
      risk_per_trade: 0.01
      min_confidence: 0.7
      parameters:
        min_trend_strength: 25.0
```

### Step 2: Restart Your Trading System

```bash
# Stop the current system
./scripts/lifecycle/stop_nq_agent_service.sh

# Start with Lux Algo bots enabled
./scripts/lifecycle/start_nq_agent_service.sh
```

### Step 3: Monitor Bot Performance

Check the Telegram bot for new commands:
- `/lux_algo_status` - View bot performance
- `/lux_algo_signals` - View recent signals
- `/lux_algo_enable <bot_name>` - Enable specific bot
- `/lux_algo_disable <bot_name>` - Disable specific bot

## Configuration Details

### Basic Bot Configuration

Each bot requires these core settings:

```yaml
trend_follower:
  enabled: true                    # Enable/disable this bot
  bot_class: "TrendFollowerBot"   # Must match the bot class name
  risk_per_trade: 0.01            # Risk per trade (1% of capital)
  min_confidence: 0.7             # Minimum signal confidence (0-1)
  max_positions: 1                # Maximum concurrent positions
```

### Advanced Parameters

Each bot has strategy-specific parameters:

```yaml
# Trend Follower parameters
parameters:
  min_trend_strength: 25.0      # Minimum trend strength (ADX-like)
  max_pullback_pct: 0.02        # Maximum pullback in trend (2%)
  momentum_threshold: 0.005     # Minimum momentum confirmation

# Breakout parameters
parameters:
  min_pattern_strength: 0.6     # Minimum consolidation strength
  require_volume_confirmation: true  # Require volume on breakout

# Mean Reversion parameters
parameters:
  min_mr_strength: 0.7          # Minimum reversion strength
  require_divergence: false     # Require divergence patterns
```

## Integration with Existing System

### Signal Combination Modes

Choose how Lux Algo bots integrate with your existing strategy:

```yaml
lux_algo_integration:
  signal_combination: "parallel"  # Options: parallel, lux_algo_only, hybrid

  # parallel: Run both Lux Algo bots AND existing strategy
  # lux_algo_only: Use ONLY Lux Algo bots (disable existing strategy)
  # hybrid: Use Lux Algo bots, fall back to existing strategy if no signals
```

### Risk Management

Global risk limits across all bots:

```yaml
global_risk_limits:
  max_total_positions: 3      # Maximum positions across ALL bots
  max_risk_per_bot: 0.05     # Maximum risk per bot (5%)
  max_total_risk: 0.15       # Maximum total risk (15%)
```

## Automation and Webhooks

### Webhook Integration

Enable automated execution via webhooks:

```yaml
automation:
  enable_webhooks: true
  webhook_url: "https://your-trading-platform-webhook.com"

  broker_integration:
    enabled: true
    broker_type: "ibkr"  # Interactive Brokers
    api_key: "your_api_key"
    api_secret: "your_secret"
```

### Alert Destinations

Configure where alerts are sent:

```yaml
alerts:
  telegram: true     # Telegram notifications
  email: false       # Email alerts
  webhook: true      # Webhook for automation
  log_file: true     # File logging
```

## Performance Monitoring

### Real-time Performance

Monitor bot performance via Telegram commands:
- `/lux_algo_performance` - View detailed performance metrics
- `/lux_algo_win_rate` - View win rates by bot
- `/lux_algo_pnl` - View P&L by bot and time period

### Performance Metrics Tracked

Each bot tracks comprehensive metrics like Lux Algo strategies:

- **Win Rate**: Percentage of winning trades
- **Profit Factor**: Gross profit / Gross loss
- **Sharpe Ratio**: Risk-adjusted returns
- **Maximum Drawdown**: Largest peak-to-valley decline
- **Average R:R**: Average risk-to-reward ratio
- **Total P&L**: Cumulative profit/loss

### Health Monitoring

Automatic health checks alert you to:
- Bots with no signals (stale strategies)
- High error rates
- Performance degradation
- Risk limit violations

## Backtesting and Optimization

### Historical Testing

Backtest bots against historical data:

```bash
# Backtest specific bot
python scripts/backtesting/backtest_lux_algo_bot.py --bot trend_follower --period 3mo

# Compare all bots
python scripts/backtesting/compare_lux_algo_bots.py --period 6mo
```

### Walk-Forward Optimization

Enable automatic parameter optimization:

```yaml
backtesting:
  optimization:
    enabled: true
    optimization_window: "1mo"    # Optimize on 1 month of data
    validation_window: "1wk"      # Validate on 1 week
    reoptimize_interval: "weekly" # Re-optimize weekly
```

## Creating Custom Bots

### Bot Template Structure

Create new bots by extending the template:

```python
from lux_algo_bots import LuxAlgoBot, BotConfig, TradeSignal

class MyCustomBot(LuxAlgoBot):
    @property
    def name(self) -> str:
        return "MyCustomBot"

    def get_indicator_suite(self):
        return MyCustomIndicators()

    def generate_signal_logic(self, df, indicators):
        # Your trading logic here
        return TradeSignal(...)
```

### Registering New Bots

Register your bot for automatic loading:

```python
from lux_algo_bots import register_bot
register_bot(MyCustomBot)
```

## Best Practices

### Risk Management
1. Start with small position sizes (0.5-1% risk per trade)
2. Use multiple bots for diversification
3. Monitor correlation between bot strategies
4. Set maximum drawdown limits per bot

### Performance Monitoring
1. Review weekly performance reports
2. Disable underperforming bots
3. Re-optimize parameters quarterly
4. Track metrics beyond just P&L (win rate, R:R, drawdown)

### Market Conditions
1. Trend bots work best in trending markets
2. Breakout bots excel in ranging markets with clear patterns
3. Mean reversion bots are higher risk - use cautiously
4. Enable/disable bots based on market regime

## Troubleshooting

### Common Issues

**No Signals Generated:**
- Check `min_confidence` threshold (may be too high)
- Verify market data quality
- Check bot-specific parameters

**Poor Performance:**
- Review risk management settings
- Check for overfitting in backtesting
- Validate indicator calculations

**Webhook Failures:**
- Verify webhook URL is accessible
- Check network connectivity
- Review webhook payload format

### Debug Commands

```bash
# View detailed logs
tail -f logs/lux_algo_bots.log

# Test bot individually
python -c "from lux_algo_bots import create_bot; bot = create_bot('TrendFollowerBot', config); print(bot.get_performance_report())"
```

## Comparison to Lux Algo Chart Prime

| Feature | Lux Algo Chart Prime | This Implementation |
|---------|---------------------|-------------------|
| Strategy Types | PAC, S&O, OSC toolkits | Trend, Breakout, Mean Reversion bots |
| AI Generation | Searches millions of combinations | Hand-crafted strategies with parameters |
| Backtesting | Built-in with performance metrics | Comprehensive backtesting framework |
| Automation | Webhook alerts to bots/brokers | Direct broker integration support |
| Cost | $39.99-$59.99/month | Included in PEARLalgo |
| Customization | Limited to their indicators | Fully customizable Python code |

## Next Steps

1. **Start Small**: Enable one bot with conservative settings
2. **Paper Trade**: Test with virtual trading first
3. **Scale Up**: Add more bots as confidence grows
4. **Optimize**: Use backtesting to refine parameters
5. **Automate**: Enable webhooks for full automation

This implementation gives you the power of Lux Algo Chart Prime's automated strategies within your existing PEARLalgo system, with full customization and control.