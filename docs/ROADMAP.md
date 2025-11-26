# Roadmap (Options + Futures + Prop)

## Current state
- IB Gateway headless via IBC; data download script working for SPY/ES.
- IBKR broker/provider in place; risk/sizing stubs added.
- Service files and IBC config set up; repo structure needs further restructuring.

## Next milestones
1) Repo structure
   - Move packages into target layout (core, data, brokers, risk, backtesting, live).
   - Add prop-firm adapter scaffold (REST/WS).
2) Risk & sizing
   - Wire RiskGuard into execution agents; add PnL tracking and daily loss stop.
   - Add capital allocation per strategy; vol-based sizing defaults.
3) Strategies
   - Implement baseline: ES/NQ breakout; short-premium defined-risk spreads; simple mean-revert.
   - Add contract builders for options (chains, greeks).
   - Daily signals loop: backtest CLI + signals writer + live (paper) consumer.
4) Backtest parity
   - Ensure backtest/live share contract builders and risk checks.
   - Add slippage/fee models; walk-forward tests.
5) Execution
   - Robust order router with retries/timeouts; alerting; health checks for Gateway/prop API.
6) Monitoring
   - Journaling (trades/fills), metrics export (Prometheus), dashboards.
7) Production hardening
   - Systemd logging to files; cron/runner scripts; kill-switch; daily reset logic.
   - Metrics/log aggregation (Prometheus/Grafana or ELK).
   - Alerting on disconnects, failed auth, and risk breach.
   - Repo hygiene: ignore data/logs/ib artifacts; keep private configs out of git.

## Risks/warnings
- IBKR single-session rule: avoid concurrent logins.
- Prop-firm rule violations: enforce daily loss and max position sizes.
- Data quality: bad inputs → bad signals; add QC and validation.
