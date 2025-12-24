# Mock Data Warning (Synthetic Prices)

This repository includes a **mock data provider** for testing (`tests/mock_data_provider.py`).

It generates **synthetic OHLCV** designed to exercise *logic* (strategy, service loop, notifications) without requiring a live IBKR connection.

---

## What mock data is (and is not)

- **Is**: deterministic-ish synthetic bars for exercising code paths
- **Is not**: real market data
- **Is not**: a backtest dataset
- **Is not**: a safety net for production

Mock prices can look plausible (e.g., MNQ around ~17,500) while still being fundamentally unrealistic:

- no real spreads / slippage / microstructure
- no true volatility clustering
- no session/holiday behavior
- no real entitlements or API constraints

---

## Rules (non‑negotiable)

- **Never** use mock data outputs to make live trading decisions.
- **Never** interpret mock-derived metrics as strategy performance.
- **Always** validate on live data (Gateway + service) before trusting signals.

---

## How to use it safely

Run the unified test runner modes that use the mock provider:

```bash
python3 scripts/testing/test_all.py signals
python3 scripts/testing/test_all.py service
```

If you see warnings that you are using mock data in a production run, treat that as a **configuration error** (fix `PEARLALGO_DATA_PROVIDER` and/or Gateway).

---

## More detail

See `docs/TESTING_GUIDE.md` (Mock Data Provider section) for deeper guidance and suggested testing levels.









