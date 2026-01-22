# Trading Bot (AutoBot) Guide

This repository keeps **trading bots** for **backtesting and analysis only**.
Runtime signal generation is provided by the core strategy in `strategies/trading_bots/pearl_bot_auto.py`.

## Runtime model (clarified)

- **Agent**: one running process for a single market (e.g., NQ).
- **Strategy**: `pearl_bot_auto` single-file strategy (runtime source of signals).
- **Trading bots (AutoBot variants)**: **backtesting-only**, used for offline evaluation.

## Backtesting (canonical usage)

Trading bots are run via the backtesting scripts:

```bash
# Backtesting scripts removed - using pearl_bot_auto only
```

## Backtesting

Backtests remain available as **variants**. Runtime is still one AutoBot per market agent.

