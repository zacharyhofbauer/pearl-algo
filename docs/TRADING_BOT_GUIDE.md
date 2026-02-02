# Trading Bot (AutoBot) Guide

This repository keeps **trading bots** for **backtesting and analysis only**.
Runtime signal generation is provided by the core strategy in `trading_bots/pearl_bot_auto.py`.

## Runtime model (clarified)

- **Agent**: one running process for a single market (e.g., NQ).
- **Strategy**: `pearl_bot_auto` single-file strategy (runtime source of signals).
- **Trading bots (AutoBot variants)**: **backtesting-only**, used for offline evaluation.

## Backtesting (canonical usage)

Backtesting scripts are located in `scripts/backtesting/`:

- **`strategy_selection.py`** - Generate drawdown-aware strategy selection reports from historical trade outcomes
- **`train_ml_filter.py`** - Train/update the ML signal filter artifact (offline only)

Example usage:

```bash
python3 scripts/backtesting/strategy_selection.py --signals-path data/agent_state/NQ/signals.jsonl
python3 scripts/backtesting/train_ml_filter.py
```

## Backtesting

Backtests remain available as **variants**. Runtime is still one AutoBot per market agent.

