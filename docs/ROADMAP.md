## Roadmap (Build a Forever Platform)

### Now (next 1–3 days)

- **Paper-trade hardening**: run `execution.mode: paper` (or dry_run) with the full decision stack on, and validate:
  - signals/day stays in your target band
  - stop distances match regime/session expectations
  - sizing reacts to streaks/volatility as intended
  - every decision is explainable from `_adaptive_sizing`, `_ml_prediction`, diagnostics
- **Model training path**: add a repeatable “train → save → load → evaluate” loop for the ML filter.

### Next (next 1–2 weeks)

- **Unify “signal policy”**: one rules engine for:
  - enabled/disabled signal types
  - per-signal min confidence + min R:R
  - per-signal allowed regimes/sessions
  - ML filter thresholds
- **Unify “risk policy”**: one engine for:
  - stop placement (ATR + structure)
  - take-profit shaping
  - Kelly/context sizing
  - kill-switches + prop-firm guardrails
- **Single CLI**: replace scattered script entrypoints with one command surface:
  - `pearlalgo run`, `pearlalgo backtest`, `pearlalgo train`, `pearlalgo doctor`

### Later (1–3 months)

- **Single state store (SQLite)**: trades/signals/performance/policy_state in one DB (schema + migrations).
- **Strategy plugin registry**: register strategies/indicators via entrypoints for clean extensibility.
- **Multi-symbol support**: rename `nq_agent` concepts to “agent runtime”, and treat MNQ/NQ as config, not package names.

### Non-negotiables (forever rules)

- Every execution decision must be reproducible from persisted inputs + config + model version.
- Every new feature must ship with a rollback switch and a test.


