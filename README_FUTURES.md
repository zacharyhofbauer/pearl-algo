# PearlAlgo Futures Desk (ES / NQ / GC)

Focused, prop-style futures workflow for ES, NQ, and GC using IBKR paper Gateway. Built for clear signals, risk-aware sizing, and structured performance logs.

## Symbols & Contracts
- Supported roots: ES (GLOBEX), NQ (GLOBEX), GC (COMEX)
- Contract builders: `fut_contract`, `es_contract`, `nq_contract`, `gc_contract` (`src/pearlalgo/futures/contracts.py`)
- Tick values (configurable): ES=12.5, NQ=20.0, GC=10.0

## Strategies
- **ma_cross**: Moving-average cross (default fast=20, slow=50).
- **sr**: Support/Resistance + VWAP with optional MA filter:
  - Detect pivot highs/lows, compute VWAP, and pull in optional external S/R (stub in `sr.py`).
  - Long when price > VWAP and near support; short when price < VWAP and near resistance; MA filter can force flat.

## Risk Management (Prop-style)
- `PropProfile` (`config.py`): starting balance, daily_loss_limit, target_profit, max_contracts_by_symbol, tick_values_by_symbol, risk_taper_threshold.
- `risk.py`: `RiskState`, `compute_risk_state` (OK/NEAR_LIMIT/HARD_STOP), `compute_position_size` (tapers size as buffer shrinks, caps per symbol).

## Performance Logging
- `performance.py`: `PerformanceRow` schema (side, requested_size, filled_size, PnL, risk_status, indicators) and helpers `log_performance_row`, `load_performance`.
- Default path: `data/performance/futures_decisions.csv`.

## Daily Batch
- Generate signals + report:
  ```bash
  source .venv/bin/activate
  python scripts/daily_workflow.py --strategy ma_cross   # or --strategy sr
  ```
  Outputs: `signals/YYYYMMDD_signals.csv`, `reports/YYYYMMDD_report.md`.

## Live Paper Loop
- Tiny prop-style paper trading (IBKR paper Gateway):
  ```bash
  source .venv/bin/activate
  python scripts/live_paper_loop.py \
    --symbols ES NQ GC \
    --sec-types FUT FUT FUT \
    --strategy sr \
    --interval 60 \
    --tiny-size 1 \
    --mode ibkr-paper
  ```
- Fetches data → generates signals → computes risk state/size → routes tiny orders → logs to `data/performance/`.

## Status Dashboard
- ANSI-only terminal dashboard:
  ```bash
  source .venv/bin/activate
  python scripts/status_dashboard.py
  ```
- Shows gateway status/version, latest signals/report, performance totals/today/per-symbol (ES/NQ/GC).

## Reviewing Performance
- Inspect CSV: `data/performance/futures_decisions.csv`
- Summary via dashboard (today/total rows and realized PnL).
- You can load via `performance.load_performance` for custom analytics.

## Notes
- IB Gateway systemd/IBC files live under `scripts/` (do not edit service files).
- Legacy moon-era agents/backtesting are archived under `legacy/` and ignored by pytest.
