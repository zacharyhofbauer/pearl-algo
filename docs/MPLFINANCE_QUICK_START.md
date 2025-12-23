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
    timeframe="1m",
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




