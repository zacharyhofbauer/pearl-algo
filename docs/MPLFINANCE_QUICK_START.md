# Charting (Canonical Quick Start)

This document is the **canonical reference** for chart generation in this repository.

- **Implementation**: `src/pearlalgo/nq_agent/chart_generator.py`
- **API**: `ChartGenerator` + `ChartConfig`
- **Backend**: `mplfinance` (candles/volume/styling)

> Note: `mplfinance` uses `matplotlib` under the hood. We do not use `matplotlib` directly in this codebase.

---

## Installation

Install the repo in editable mode (recommended):

```bash
pip install -e .
```

If you only need charting in an existing environment:

```bash
pip install mplfinance
```

---

## Usage

```python
from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

generator = ChartGenerator(ChartConfig())

chart_path = generator.generate_entry_chart(
    signal=signal_dict,
    buffer_data=dataframe,
    symbol="MNQ",
    timeframe="5m",
)
```

### Chart types

- `generate_entry_chart(...)`
- `generate_exit_chart(...)`
- `generate_backtest_chart(..., timeframe=...)`

---

## Data contract (OHLCV)

Input data should include:

- columns: `open`, `high`, `low`, `close`, `volume`
- timestamps: either a `timestamp` column **or** a `DatetimeIndex`

Notes:

- The **input** contract uses **lowercase** OHLCV (`open/high/low/close/volume`).
- The chart generator normalizes internally for `mplfinance` (which expects an OHLCV index + specific column names).
- If VWAP is enabled, VWAP calculations expect the same lowercase OHLCV contract.

---

## Local verification

Generate a sample chart image:

```bash
python3 scripts/testing/test_mplfinance_chart.py
```

---

## Troubleshooting

### `ImportError: mplfinance required...`

- Ensure dependencies are installed: `pip install -e .`
- Or install charting directly: `pip install mplfinance`

### Missing columns / empty charts

- Ensure OHLCV columns exist and timestamps are present (see data contract above).

---

## Visual Regression Testing

All chart types have **visual regression tests** to prevent unintended visual changes.

### Running all chart visual regression tests

```bash
# Dashboard chart tests (11 tests)
pytest tests/test_dashboard_chart_visual_regression.py -v

# Entry/Exit chart tests (13 tests)
pytest tests/test_entry_exit_chart_visual_regression.py -v

# Backtest chart tests (8 tests)
pytest tests/test_backtest_chart_visual_regression.py -v

# Run all chart visual regression tests
pytest tests/test_dashboard_chart_visual_regression.py tests/test_entry_exit_chart_visual_regression.py tests/test_backtest_chart_visual_regression.py -v
```

Test coverage includes:
- **Baseline validity tests** – verify baseline PNGs are not corrupted
- **Visual regression tests** – compare rendered output against baselines
- **Determinism tests** – verify same inputs produce identical outputs
- **Edge case tests** – verify charts handle stress scenarios

### Updating baseline images

If you intentionally change chart appearance:

```bash
# Dashboard chart baseline
python3 scripts/testing/generate_dashboard_baseline.py

# Entry/Exit chart baselines
python3 scripts/testing/generate_entry_exit_baselines.py

# Entry only
python3 scripts/testing/generate_entry_exit_baselines.py --entry-only

# Exit only
python3 scripts/testing/generate_entry_exit_baselines.py --exit-only

# Backtest chart baseline
python3 scripts/testing/generate_backtest_baseline.py

# On-demand (/chart) baseline (12h lookback)
python3 scripts/testing/generate_on_demand_chart_baseline.py
```

Baseline images are stored in: `tests/fixtures/charts/`
- `dashboard_baseline.png`
- `entry_baseline.png`
- `exit_baseline.png`
- `backtest_baseline.png`
- `on_demand_chart_12h_baseline.png`

### Visual Schema Reference

See `docs/CHART_VISUAL_SCHEMA.md` for the authoritative reference on:
- Color semantics (candles, signals, indicators)
- Z-order layering rules
- Right-label priority hierarchy
- Implicit trader contracts (do not violate)

### Determinism hooks

For testing, the dashboard chart supports a `title_time` parameter to fix the timestamp in the title:

```python
chart_path = generator.generate_dashboard_chart(
    data=data,
    symbol="MNQ",
    timeframe="5m",
    title_time="12:00 UTC",  # Fixed for deterministic testing
)
```

---

## Z-Order (Layering)

Chart elements are rendered with explicit z-order for predictable layering:

1. **Session shading** (lowest) - background
2. **Zones** (supply/demand, power channel) - behind candles
3. **Level lines** (key levels, VWAP bands) - above zones
4. **Candles** - main content
5. **Text labels** (highest) - always visible


