# PEARL Automated Trading Bots

Complete, self-contained automated trading bots for the PEARLalgo system.

## Overview

PEARL Bots are complete automated trading systems that combine:
- Custom technical indicators and analysis
- Automated entry/exit logic with risk management
- Real-time performance tracking and optimization
- Telegram integration for remote control
- Comprehensive backtesting capabilities

## Available Bots

### 🤖 TrendFollowerBot
**Strategy**: Trend following with pullback entries
**Best For**: Trending markets
**Features**:
- Moving average trend identification
- Pullback entry timing
- Volatility-adjusted stops
- Momentum confirmation

### 📈 BreakoutBot
**Strategy**: Breakout trading from consolidation patterns
**Best For**: Ranging markets with clear breakouts
**Features**:
- Volatility contraction detection
- Volume confirmation
- Pattern-based targets
- Risk management stops

### 📊 MeanReversionBot
**Strategy**: Oscillator-based mean reversion
**Best For**: Ranging markets (higher risk)
**Features**:
- Multiple oscillator analysis
- Divergence detection
- Bollinger Band positioning
- Time-based exits

## Quick Start

### 1. Configuration
Add to `config/config.yaml`:

```yaml
lux_algo_bots:  # TODO: Rename to pearl_bots
  enabled: true
  bots:
    trend_follower:
      enabled: true
      description: "Trend-following bot"
      bot_class: "TrendFollowerBot"
      risk_per_trade: 0.01
      min_confidence: 0.7
```

### 2. Telegram Control
Use the Strategies menu in Telegram:
- 🤖 **Manage Bots**: Enable/disable individual bots
- 📊 **Bot Performance**: View real-time metrics
- 🚀 **Start All Bots**: Bulk activation
- 🛑 **Stop All Bots**: Emergency shutdown

### 3. Backtesting
Run comprehensive backtests:

```bash
# Backtest individual bot
python scripts/backtesting/backtest_pearl_bot.py --bot trend_follower --period 3mo

# Compare all bots
python scripts/backtesting/compare_pearl_bots.py --period 6mo
```

## Architecture

### Core Components
- **PearlBot**: Abstract base class for all bots
- **BotConfig**: Configuration management
- **TradeSignal**: Standardized signal format
- **PearlBotManager**: Bot coordination and monitoring

### Integration Points
- **PEARLalgo Strategy System**: Native integration
- **Telegram Interface**: Remote management
- **Performance Tracking**: Real-time metrics
- **Risk Management**: Built-in position sizing

## Key Features

### ✅ Complete Automation
- Zero-code deployment
- Automated signal generation
- Risk-managed execution
- Performance optimization

### ✅ Professional Monitoring
- Real-time P&L tracking
- Win rate and Sharpe ratio
- Drawdown monitoring
- Health status indicators

### ✅ Flexible Configuration
- Per-bot parameter tuning
- Market condition adaptation
- Risk level customization
- Strategy combination

### ✅ Enterprise-Grade
- Comprehensive logging
- Error handling and recovery
- Performance analytics
- Audit trail maintenance

## Performance Metrics

Each bot tracks comprehensive metrics:
- **Win Rate**: Percentage profitable trades
- **Profit Factor**: Gross profit / Gross loss
- **Sharpe Ratio**: Risk-adjusted returns
- **Maximum Drawdown**: Peak-to-valley decline
- **Total P&L**: Cumulative profit/loss
- **Active Positions**: Current open trades

## Risk Management

Built-in risk controls:
- **Position Sizing**: Risk-based contract allocation
- **Stop Losses**: Volatility-adjusted exit points
- **Take Profits**: Pattern-based target levels
- **Drawdown Limits**: Maximum loss thresholds
- **Exposure Limits**: Maximum concurrent positions

## Development

### Creating Custom Bots

```python
from pearl_bots import PearlBot, BotConfig, TradeSignal

class MyCustomBot(PearlBot):
    def get_indicator_suite(self):
        return MyCustomIndicators()

    def generate_signal_logic(self, df, indicators):
        # Your trading logic
        return TradeSignal(...)
```

### Testing Framework

```python
# Unit testing
python -m pytest tests/test_pearl_bots/

# Backtesting
python scripts/backtesting/backtest_pearl_bot.py --bot my_custom_bot

# Performance analysis
python scripts/backtesting/analyze_pearl_bot_performance.py
```

## Deployment Checklist

- [ ] Configuration added to `config/config.yaml`
- [ ] Bots enabled in Telegram Strategies menu
- [ ] Risk parameters set appropriately
- [ ] Backtesting completed for new bots
- [ ] Performance monitoring configured
- [ ] Emergency stop procedures tested

## Troubleshooting

### Common Issues

**Bots not loading:**
- Check configuration syntax in `config.yaml`
- Verify bot class names match imports
- Review telegram handler logs

**Poor performance:**
- Adjust confidence thresholds
- Tune risk parameters
- Review market conditions vs strategy type

**Signal conflicts:**
- Check bot overlap in same market conditions
- Adjust bot priorities
- Use market regime filtering

## Support

### Documentation
- `docs/PEARL_BOTS_DEPLOYMENT.md` - Complete deployment guide
- `docs/PEARL_BOTS_INTEGRATION.md` - Technical integration details
- `docs/TELEGRAM_MENU_LAYOUT.md` - Menu system documentation

### Configuration Files
- `config/pearl_bots_example.yaml` - Sample configurations
- `src/pearlalgo/strategies/pearl_bots_config_example.yaml` - Extended examples

## Roadmap

### Planned Enhancements
- **Machine Learning Integration**: AI-optimized parameters
- **Multi-Timeframe Analysis**: Cross-timeframe signal confirmation
- **Portfolio Optimization**: Automated bot allocation
- **Market Regime Detection**: Dynamic bot activation
- **Advanced Backtesting**: Walk-forward optimization

### Research Areas
- **Alternative Indicators**: Custom technical analysis
- **Entry Timing**: Advanced entry signal optimization
- **Exit Strategies**: Dynamic exit logic improvement
- **Risk Parity**: Advanced risk management techniques

---

**PEARL Bots**: Professional automated trading systems for modern quantitative finance.