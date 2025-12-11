# Backtesting Guide

This guide explains how to use the options backtesting framework with historical ES/NQ data for correlation analysis.

## Overview

The backtesting framework supports:
- Options-specific backtesting with time progression
- Historical ES/NQ data integration for correlation
- Parameter optimization
- Performance metrics calculation

## Quick Start

### Basic Backtest

```python
from pearlalgo.backtesting.options_backtest_engine import OptionsBacktestEngine
from pearlalgo.backtesting.historical_data_loader import HistoricalFuturesDataLoader
from datetime import datetime, timedelta
from pearlalgo.data_providers.massive_provider import MassiveDataProvider

# Initialize components
data_provider = MassiveDataProvider(api_key="your_key")
loader = HistoricalFuturesDataLoader(data_provider)
engine = OptionsBacktestEngine(initial_cash=100000.0)

# Load historical ES/NQ data
start_date = datetime(2024, 1, 1)
end_date = datetime(2024, 12, 1)
es_data = loader.load_es_data(start_date, end_date, timeframe="15m")
nq_data = loader.load_nq_data(start_date, end_date, timeframe="15m")

# Run backtest
results = engine.run_backtest(
    strategy=your_strategy,
    start_date=start_date,
    end_date=end_date,
    underliers=["QQQ", "SPY"],
    historical_data={"ES": es_data, "NQ": nq_data},
)

# View results
print(f"Total Return: {results['total_return']:.2%}")
print(f"Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {results['metrics']['max_drawdown']:.2%}")
```

## Historical Data Loading

### Loading ES/NQ Data

```python
from pearlalgo.backtesting.historical_data_loader import HistoricalFuturesDataLoader

loader = HistoricalFuturesDataLoader(
    data_provider=data_provider,
    cache_dir="data/backtesting",
)

# Load single symbol
es_data = loader.load_es_data(
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 1),
    timeframe="15m",
)

# Load multiple symbols
data = loader.load_multiple_symbols(
    symbols=["ES", "NQ"],
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 1),
    timeframe="15m",
    align=True,  # Align timestamps
)
```

### Data Caching

Historical data is automatically cached in Parquet format:
- Location: `data/backtesting/`
- Format: `{SYMBOL}_{TIMEFRAME}_{START}_{END}.parquet`
- Cache is reused if file exists and date range matches

### Contract Roll Handling

The loader automatically handles futures contract rolls:
- Detects large price gaps (>5%)
- Adjusts subsequent prices to maintain continuity
- Logs roll events for review

## Backtesting Engine

### Options-Specific Features

The `OptionsBacktestEngine` handles:
- **Options Expiration**: Marks expired contracts to zero value
- **Time Progression**: Bar-by-bar simulation
- **P&L Tracking**: Realized and unrealized P&L
- **Stop Loss/Take Profit**: Automatic exit triggers
- **Time-Based Exits**: Exit after specified hours

### Performance Metrics

The engine calculates:
- **Total Return**: Overall return percentage
- **Win Rate**: Percentage of winning trades
- **Max Drawdown**: Maximum peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted return
- **Profit Factor**: Gross profit / gross loss

## Parameter Optimization

### Grid Search

```python
from pearlalgo.backtesting.parameter_optimizer import ParameterOptimizer

optimizer = ParameterOptimizer()

# Define parameter grid
param_grid = {
    "momentum_threshold": [0.01, 0.02, 0.03],
    "volume_threshold": [1.5, 2.0, 2.5],
    "stop_loss_pct": [0.15, 0.20, 0.25],
}

# Run optimization
results = optimizer.optimize_parameters(
    strategy=your_strategy,
    data=historical_data,
    param_grid=param_grid,
)

# Compare results
comparison_df = optimizer.compare_results(results)
print(comparison_df)

# Generate report
report = optimizer.generate_report(results)
print(report)
```

### Comparing Expiration Selections

```python
# Test different DTE ranges
dte_ranges = [
    {"min_dte": 0, "max_dte": 7},   # Intraday
    {"min_dte": 7, "max_dte": 45},  # Swing
]

results = []
for dte_range in dte_ranges:
    # Modify strategy parameters
    strategy.params.update(dte_range)
    
    # Run backtest
    result = engine.run_backtest(...)
    results.append(result)

# Compare
comparison = optimizer.compare_results(results)
```

## Using ES/NQ Data for Correlation

ES (S&P 500 futures) and NQ (Nasdaq futures) can be used for:
- **Correlation Analysis**: Compare options performance with futures trends
- **Market Regime Detection**: Identify trending vs. ranging markets
- **Entry Timing**: Use futures momentum to time options entries

### Example: Correlation-Based Entry

```python
# Load ES/NQ data
es_data = loader.load_es_data(start_date, end_date)
nq_data = loader.load_nq_data(start_date, end_date)

# Align data
aligned = loader.align_timestamps({"ES": es_data, "NQ": nq_data})

# Use ES momentum for QQQ options entries
for timestamp in aligned["ES"].index:
    es_price = aligned["ES"].loc[timestamp, "close"]
    es_momentum = calculate_momentum(aligned["ES"], timestamp)
    
    # Enter QQQ options if ES shows strong momentum
    if es_momentum > threshold:
        # Generate QQQ options signal
        ...
```

## Best Practices

1. **Data Quality**: Always verify historical data completeness
2. **Timeframe Selection**: Use appropriate timeframe for strategy (1m for intraday, 15m for swing)
3. **Commission**: Include realistic commission costs (default: $0.85 per contract)
4. **Slippage**: Consider adding slippage model for realistic results
5. **Out-of-Sample Testing**: Reserve recent data for validation

## Troubleshooting

### No Data Returned

- Check Massive API key validity
- Verify date range is within available data
- Check symbol format (ES, NQ not ESU5, NQU5)

### Contract Roll Issues

- Review roll detection logs
- Adjust `roll_threshold` if needed
- Manually verify roll dates

### Performance Issues

- Use caching for repeated backtests
- Reduce date range for initial testing
- Use lower timeframe resolution (15m instead of 1m)

## Advanced Usage

### Custom Strategy Integration

```python
class MyOptionsStrategy:
    def generate_signals(self, timestamp, market_data, positions):
        # Your strategy logic
        return signals

# Use in backtest
results = engine.run_backtest(
    strategy=MyOptionsStrategy(),
    ...
)
```

### Custom Metrics

Extend `OptionsBacktestEngine.calculate_metrics()` to add custom metrics:
- Sortino ratio
- Calmar ratio
- Average trade duration
- Maximum consecutive losses

## CLI Usage

```bash
# Run backtest via CLI (if implemented)
pearlalgo backtest \
    --strategy swing_momentum \
    --underliers QQQ,SPY \
    --start 2024-01-01 \
    --end 2024-12-01 \
    --use-es-nq-data
```

## Next Steps

1. Start with small date ranges for testing
2. Validate strategy logic with paper trading
3. Optimize parameters using grid search
4. Test on out-of-sample data
5. Deploy to live trading with small size
