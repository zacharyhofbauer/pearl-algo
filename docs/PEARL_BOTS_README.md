# PEARL Trading Bot (AutoBot)

Complete, self-contained automated trading bots for the PEARLalgo system.

## Overview

The PEARL Trading Bot (AutoBot) is a complete automated trading system that combines:
- Custom technical indicators and analysis
- Automated entry/exit logic with risk management
- Real-time performance tracking and optimization
- Telegram integration for remote control
- Comprehensive backtesting capabilities

## Available Bots

These are **variants** for backtesting or future AutoBot options. Runtime uses **one selected AutoBot**.

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
trading_bot:
  enabled: true
  selected: "PearlAutoBot"
  available:
    PearlAutoBot:
      class: "PearlAutoBot"
      enabled: true
      parameters: {}
```

**Notes**
- `trading_bot` is the canonical key.
- Legacy `pearl_bots` / `lux_algo_bots` are still accepted and normalized at startup.

### 2. Telegram Control
Use the **🤖 Bots** menu in Telegram:
- 🤖 **Trading Bot**: Active bot status (singular)
- 📊 **Bot Performance**: View real-time metrics

### 3. Backtesting
Run backtests from Telegram:

- Open **Telegram** → **🤖 Bots** → **🧪 Backtest (Advanced)**
- Choose **💎 PearlBot (All‑in‑One)** (recommended) or a variant, then pick a historical period (1w/2w/4w/6w)
- View saved artifacts in **Telegram** → **🤖 Bots** → **📑 Reports**

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
from pearlalgo.strategies.pearl_bots import PearlBot, BotConfig, TradeSignal

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

# Backtesting (programmatic)
from pearlalgo.strategies.pearl_bots.backtest_adapter import backtest_pearl_bot

# Example:
# result = backtest_pearl_bot(my_bot, df_ohlcv)
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
- Ensure only one AutoBot is selected under `trading_bot`
- Verify the bot is enabled in `trading_bot.available`

## Support

### Documentation
- `docs/PROJECT_SUMMARY.md` - Architecture + module boundaries (source of truth)
- `docs/TELEGRAM_GUIDE.md` - Telegram command handler + menus
- `docs/TESTING_GUIDE.md` - Validation + backtesting workflows

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