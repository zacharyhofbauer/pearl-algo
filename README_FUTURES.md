# PearlAlgo Futures Desk (ES / NQ / GC)

Focused, prop-style futures workflow for ES, NQ, and GC using IBKR paper Gateway. Built for clear signals, risk-aware sizing, and structured performance logs.

## Symbols & Contracts
- Supported roots: ES (GLOBEX), NQ (GLOBEX), GC (COMEX)
- Contract builders: `fut_contract`, `es_contract`, `nq_contract`, `gc_contract` (`src/pearlalgo/futures/contracts.py`)
- Tick values (configurable): ES=12.5, NQ=20.0, GC=10.0

## Strategies
- **ma_cross**: Moving-average cross (fast=20, slow=50).
- **sr** (default): Support/Resistance + VWAP + EMA filter:
  - **Daily pivots**: Floor-trader pivots (P, R1-3, S1-3) from previous day's high/low/close.
  - **VWAP**: Volume-weighted average price computed from recent bars.
  - **Pre-market levels**: High/low from bars before main session (configurable session start hour).
  - **Swing high/low**: Recent significant highs/lows from last N bars (default 20).
  - **EMA filter**: 20-period EMA trend filter (long only when price > EMA, short only when price < EMA).
  - **Signal logic**: 
    - Long: Price > VWAP, near support1, and price > 20-EMA → "Bullish pivot + above VWAP + 20EMA"
    - Short: Price < VWAP, near resistance1, and price < 20-EMA → "Bearish pivot + below VWAP + below 20EMA"

## Risk Management (Prop-style)
- `PropProfile` (`config.py`): 
  - `starting_balance`, `daily_loss_limit`, `target_profit`
  - `max_contracts_by_symbol`, `tick_values_by_symbol`
  - `risk_taper_threshold`: Fraction of loss limit remaining where sizing starts to taper (default 0.3)
  - `max_trades`: Maximum trades per session (None = unlimited)
  - `cooldown_minutes`: Cooldown period after HARD_STOP or max_trades reached (default 60)
  - `min_contract_size`: Minimum contract size (default 1, futures don't allow fractional)
- `risk.py`: 
  - `RiskState` with status: `OK`, `NEAR_LIMIT`, `HARD_STOP`, `COOLDOWN`, `PAUSED`
  - `compute_risk_state`: Automatically sets cooldown_until after HARD_STOP or when max_trades reached
  - `compute_position_size`: Tapers sizing by:
    - Remaining drawdown buffer (starts tapering at risk_taper_threshold)
    - Remaining trades (tapers when < 30% of max_trades remain)
    - Caps at per-symbol max_contracts and enforces min_contract_size

## Performance Logging
- `performance.py`: `PerformanceRow` schema with comprehensive fields:
  - Trade details: `symbol`, `side`, `requested_size`, `filled_size`, `entry_price`, `exit_price`
  - Timestamps: `timestamp`, `entry_time`, `exit_time` (timezone-aware)
  - P&L: `realized_pnl`, `unrealized_pnl`
  - Risk context: `risk_status`, `drawdown_remaining`, `emotion_state` (normal/COOLDOWN/PAUSED)
  - Strategy context: `strategy_name`, `trade_reason` (e.g., "Bullish pivot + above VWAP + 20EMA"), `fast_ma`, `slow_ma`
  - Metadata: `notes`, `sec_type`
- Helpers: `log_performance_row`, `load_performance`, `summarize_daily_performance` (win rate, avg P&L, worst drawdown, avg time in trade)
- Default path: `data/performance/futures_decisions.csv`

## Daily Batch
- Generate signals + report (default strategy: `sr`):
  ```bash
  source .venv/bin/activate
  python scripts/daily_workflow.py --strategy sr   # or --strategy ma_cross
  ```
  Outputs: `signals/YYYYMMDD_signals.csv`, `reports/YYYYMMDD_report.md`.
  - Fetches data from IBKR (or CSV), generates signals, computes risk state and position sizes
  - Logs all decisions to `data/performance/futures_decisions.csv` with trade_reason and risk context

## Live Paper Loop
- Prop-style paper trading loop with cooldown handling and entry/exit tracking (default strategy: `sr`):
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
- Features:
  - Fetches data → generates signals → computes risk state/size → routes tiny orders
  - **Cooldown handling**: Skips trading when status is COOLDOWN/PAUSED but continues logging
  - **Entry/exit tracking**: Records `entry_time` when order placed, `exit_time` when position closes
  - **Tapered sizing**: Uses `--tiny-size` as base but adjusts by risk taper logic
  - **Position management**: Automatically exits positions on opposite signals or risk-based exits
  - Logs all decisions to `data/performance/futures_decisions.csv` with full context

## Status Dashboard
- ANSI-only terminal dashboard:
  ```bash
  source .venv/bin/activate
  python scripts/status_dashboard.py
  ```
- Displays:
  - **IB Gateway**: Status (active/inactive), version from logs
  - **Workflow files**: Latest signals CSV, report MD, performance CSV paths
  - **Performance metrics**: 
    - Total/today rows and realized P&L
    - Win rate, average P&L per trade, worst drawdown, average time in trade
    - Per-symbol (ES/NQ/GC) trades and realized P&L
    - Last trade_reason for each symbol
  - **Risk state**: 
    - Current status (OK/NEAR_LIMIT/HARD_STOP/COOLDOWN/PAUSED)
    - Remaining loss buffer
    - Trades today vs max_trades, remaining trades
    - Cooldown until timestamp (if in cooldown)

## Reviewing Performance
- Inspect CSV: `data/performance/futures_decisions.csv`
- Summary via dashboard (today/total rows and realized PnL).
- You can load via `performance.load_performance` for custom analytics.

## Notes
- IB Gateway systemd/IBC files live under `scripts/` (do not edit service files).
- Legacy moon-era agents/backtesting are archived under `legacy/` and ignored by pytest.
