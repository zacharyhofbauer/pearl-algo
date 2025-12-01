# Current Structure (futures-first)

# Current Structure (Futures Desk)

```
src/pearlalgo/
  futures/
    config.py         # Prop profile defaults + overrides (yaml/json), tick values, taper, max_trades, cooldown_minutes
    contracts.py      # ES/NQ/GC contract builders and metadata
    signals.py        # MA-cross and S/R strategy (daily pivots + VWAP + EMA filter)
    sr.py             # Support/Resistance: pivots, VWAP, pre-market levels, swing high/low
    risk.py           # Prop-style risk state (OK/NEAR_LIMIT/HARD_STOP/COOLDOWN/PAUSED) + tapered position sizing
    performance.py    # Structured trade logging (entry/exit times, P&L, drawdown, trade_reason, emotion_state)
  data_providers/     # IBKR + CSV providers
  brokers/            # IBKR broker + contract utilities
  config/             # env/settings

scripts/
  run_daily_signals.py   # daily signal generation (default: sr strategy) + performance log
  daily_workflow.py      # wrapper to run signals then generate markdown report
  daily_report.py        # markdown report from signals/performance CSV
  live_paper_loop.py     # prop-style paper loop with cooldown handling, entry/exit tracking, tiny-size
  status_dashboard.py    # ANSI dashboard (gateway status, performance metrics, risk state, cooldown)
  ibkr_download_data.py  # historical data fetch from IBKR Gateway
  risk_monitor.py        # simple halt file watcher for daily loss limits
  test_contracts.py      # IBKR contract discovery sanity check for ES/NQ/GC

legacy/
  src/pearlalgo/backtesting, live, cli.py, agents/  # archived moon-era scaffold
  dashboard.py, live_loop.py, live_from_signals.py, tail_brain.py  # archived scripts
  tests/  # archived moon-era tests (pytest ignores legacy/)

tests/   # current futures-focused tests
docs/
```

Notes:
- IBKR systemd/service helpers stay under `scripts/` (ibgateway.service, ibgateway-ibc.service, ibc_config.ini, ibgateway_logs.sh, ibgateway_status.sh).
- Legacy moon-era components are archived under `legacy/`; pytest is configured to ignore `legacy/`.
- Legacy tests are skipped by default via `pytest.ini` (norecursedirs=legacy); run them manually if you need to resurrect moon-era functionality.
