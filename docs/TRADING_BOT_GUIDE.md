# Trading Bot (AutoBot) Guide

This repository keeps **trading bots** for **backtesting and analysis only**.
Runtime signal generation is provided by the core strategy pipeline in `strategies/nq_intraday`.

## Runtime model (clarified)

- **Agent**: one running process for a single market (e.g., NQ).
- **Strategy**: `nq_intraday` scanner + signal generator (runtime source of signals).
- **Trading bots (AutoBot variants)**: **backtesting-only**, used for offline evaluation.

## Backtesting (canonical usage)

Trading bots are run via the backtesting scripts:

```bash
python3 scripts/backtesting/backtest_trading_bot.py --bot PearlAutoBot --data-path data/historical/<file>.parquet
python3 scripts/backtesting/compare_trading_bots.py --data-path data/historical/<file>.parquet
```

## Backtesting

Backtests remain available as **variants**. Runtime is still one AutoBot per market agent.

