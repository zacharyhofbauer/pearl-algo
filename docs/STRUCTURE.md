# Current Structure (futures-first)

# Current Structure (Futures Desk)

```
src/pearlalgo/
  futures/
    config.py         # Prop profile defaults + overrides (yaml/json), tick values, taper
    contracts.py      # ES/NQ/GC contract builders and metadata
    signals.py        # MA-cross (strategy-agnostic interface)
    risk.py           # Prop-style risk state + position sizing (taper/limits)
    performance.py    # Structured decision/trade logging and loaders
  data_providers/     # IBKR + CSV providers
  brokers/            # IBKR broker + contract utilities
  config/             # env/settings

scripts/
  run_daily_signals.py   # daily signal generation + performance log (futures)
  daily_workflow.py      # wrapper to run signals then report
  daily_report.py        # markdown report from signals/performance
  live_paper_loop.py     # prop-style paper loop (IBKR/dummy) with risk/logging
  status_dashboard.py    # ANSI dashboard (gateway + files + perf stats)
  ibkr_download_data.py  # historical data fetch (IBKR)
  risk_monitor.py        # simple halt file watcher
  test_contracts.py      # IBKR contract discovery sanity check

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
