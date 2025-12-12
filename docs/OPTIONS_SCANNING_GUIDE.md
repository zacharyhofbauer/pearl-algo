# Options Scanning Guide

## Overview

This guide covers the options swing-trade scanning system for equity options.

## Architecture

The options scanning system consists of:

1. **Options Swing Scanner** (`src/pearlalgo/options/swing_scanner.py`)
   - Broad-market equity scanning
   - Lower frequency (15-60 minute intervals)
   - Options chain integration

2. **Equity Universe Manager** (`src/pearlalgo/options/universe.py`)
   - Maintains scan target lists
   - Index ETFs (SPY, QQQ, etc.)
   - Liquid stocks

3. **Options Chain Filter** (`src/pearlalgo/options/chain_filter.py`)
   - Liquidity filtering (volume, open interest)
   - Strike selection (ATM, OTM, ITM)
   - Expiration filtering
   - IV rank thresholds

4. **Options Strategies** (`src/pearlalgo/options/strategies.py`)
   - Swing momentum strategy
   - Volatility expansion (placeholder)
   - Options-specific indicators

## Configuration

### Equity Universe

Edit `config/config.yaml`:

```yaml
monitoring:
  workers:
    options:
      enabled: true
      universe: ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL"]
      interval: 900  # 15 minutes
      strategy: "swing_momentum"
```

### Options Chain Filtering

```yaml
options:
  scanning:
    min_volume: 100
    min_open_interest: 50
    max_dte: 45  # days to expiration
    min_iv_rank: 20  # IV rank threshold (0-100)
    strike_selection: "atm"  # atm, otm, itm
```

### Options Strategies

```yaml
options:
  strategies:
    swing_momentum:
      lookback: 20
      volume_multiplier: 1.5
      min_move: 0.02  # 2%
      rsi_period: 14
      rsi_oversold: 30
      rsi_overbought: 70
```

## Usage

### Manual Scanning

```python
from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.swing_scanner import OptionsSwingScanner

# Create universe
universe = EquityUniverse(
    symbols=["SPY", "QQQ", "AAPL"],
    include_etfs=True,
    include_stocks=True,
)

# Create scanner
scanner = OptionsSwingScanner(
    universe=universe,
    strategy="swing_momentum",
)

# Run single scan
results = await scanner.scan()
```

### Continuous Scanning

```python
# Run continuously
await scanner.scan_continuous(interval=900)  # 15 minutes
```

## Options Chain Filtering

### Liquidity Filters

- **Min Volume**: Minimum daily volume (default: 100)
- **Min Open Interest**: Minimum open interest (default: 50)

### Strike Selection

- **ATM (At-The-Money)**: Within 5% of underlying price
- **OTM (Out-of-The-Money)**: Calls above, puts below underlying
- **ITM (In-The-Money)**: Calls below, puts above underlying

### Expiration Filtering

- **Max DTE**: Maximum days to expiration (default: 45)
- Filters out options expiring too far in the future

### IV Rank Filtering

- **Min IV Rank**: Minimum IV rank threshold (default: 20)
- IV rank: 0-100, where 100 = highest IV in last year

## Strategies

### Swing Momentum

**Description**: Momentum breakout strategy for options

**Parameters**:
- `lookback`: Lookback period for recent high/low (default: 20)
- `volume_multiplier`: Volume confirmation multiplier (default: 1.5)
- `min_move`: Minimum move percentage (default: 0.02 = 2%)
- `rsi_period`: RSI period (default: 14)
- `rsi_oversold`: RSI oversold threshold (default: 30)
- `rsi_overbought`: RSI overbought threshold (default: 70)

**Entry Rules**:
- Long: Breakout above recent high with volume, RSI < 70
- Short: Breakdown below recent low with volume, RSI > 30

**Targets**:
- Stop loss: 2% from entry
- Take profit: 3% from entry (1.5x risk/reward)

## Data Requirements

### 

Options chain data requires 
- Free tier: Limited options data
- Paid tier: Full options chains with Greeks

**Note**: Confirm . If not, use Tradier API (already in codebase).

### Historical Data

- Minimum: 50 bars for indicators
- Recommended: 1000 bars (30 days at 15min)
- Automatic backfill on startup

## Rate Limits

### 

- Free tier: 5 calls/second
- With 500 symbols × 1 scan/15min = 33 scans/min = manageable

### Recommendations

- Start with 20-50 symbols
- Use 15-minute intervals
- Monitor rate limit usage

## Troubleshooting

### No Options Data

1. Check 
   ```bash
   echo $POLYGON_API_KEY
   ```

2. Test options chain API:
   ```python
   from pearlalgo.data_providers.
   provider = 
   chain = await provider.get_options_chain("SPY")
   print(chain)
   ```

3. Check 
   - Free tier may not support options
   - Consider Tradier API alternative

### No Signals Generated

1. Check strategy parameters
2. Verify historical data available
3. Check market hours (options trade during regular hours)
4. Review logs for errors

### High Memory Usage

1. Reduce universe size
2. Increase scan interval
3. Reduce buffer size
4. Filter options chain more aggressively

## Best Practices

1. **Start Small**: Begin with 10-20 symbols
2. **Monitor Rate Limits**: Track API usage
3. **Filter Aggressively**: Use strict liquidity filters
4. **Test Strategies**: Backtest before live scanning
5. **Review Signals**: Monitor signal quality regularly

## Future Enhancements

- IV rank calculation from historical data
- Greeks-based filtering
- Earnings play detection
- Volatility expansion strategies
- Multi-leg option strategies
