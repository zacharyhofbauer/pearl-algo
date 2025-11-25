# Target Project Structure

```
pearlalgo/
  core/          # events, portfolio, common models
  data/
    providers/   # ibkr, csv, rest
    pipelines.py
    loaders.py
  brokers/       # ibkr, prop, backtest, contracts
  strategies/    # base + concrete
  agents/        # execution, backtest, research, risk
  backtesting/   # engines, slippage/fee models
  live/          # live orchestrators, health checks
  risk/          # limits, sizing, pnl tracking
  config/        # settings, symbols, profiles
  utils/         # logging, dates, misc
scripts/
  ibgateway/     # systemd templates, status, ops
  data/          # downloaders
tests/
docs/
```

## Current gaps
- No dedicated backtesting or live orchestration modules.
- Risk is minimal; add PnL tracking, daily loss stops, and sizing integration.
- Broker adapters: IBKR present; prop-firm adapter is stub only.
- Options/futures utilities: missing greeks, chains, roll logic.
- Monitoring/metrics: missing Prometheus/log aggregation.
