# Current Structure (futures-first)

```
src/pearlalgo/
  futures/
    config.py         # Prop profile defaults + optional yaml/json loader
    contracts.py      # ES/NQ/GC (+ micros) IBKR contract builders
    signals.py        # MA-cross signal helper
    risk.py           # Prop-style risk state + position sizing
    performance.py    # Structured decision/trade logging
  data_providers/     # IBKR + CSV providers
  brokers/            # IBKR broker + contract utilities
  config/             # env/settings
  strategies/         # legacy strategy examples (being phased out)
  agents/, backtesting/, live/ # legacy moon-era scaffolding (kept for now)
scripts/
  run_daily_signals.py   # daily signal generation + logging (futures)
  daily_workflow.py      # wrapper to run signals then report
  daily_report.py        # markdown report from signals/trades
  live_paper_loop.py     # paper loop using futures core + prop profile
  ibkr_download_data.py  # historical data fetch (IBKR)
  risk_monitor.py        # simple halt file watcher
  test_contracts.py      # IBKR contract discovery sanity check
legacy/
  dashboard.py, live_loop.py, live_from_signals.py, tail_brain.py  # archived scripts
tests/
docs/
```

Notes:
- IBKR systemd/service helpers stay under `scripts/` (ibgateway.service, ibgateway-ibc.service, ibc_config.ini, ibgateway_logs.sh, ibgateway_status.sh).
- Legacy moon-era agents/backtesting remain but are candidates for removal once the futures core fully replaces them.
