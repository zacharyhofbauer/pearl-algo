# Legacy automated bot (dormant, preserved)

The fully-automated MNQ trading bot is **not deleted** — it is parked and recoverable.

## What's dormant

The automation stack stays on disk and runnable, just not used by the active manual model:

- `src/pearlalgo/market_agent/` — service orchestrator + trading loop
- `src/pearlalgo/execution/tradovate/` — auto order execution
- `src/pearlalgo/data_providers/` — IBKR data feed
- `src/pearlalgo/strategies/composite_intraday/` — the automated strategy bundle
- systemd services + `./pearl.sh` control + `scripts/ops/deploy-from-mac.sh`

`execution.armed` is **false** in `config/live/tradovate_paper.yaml`; the strategy was parked at
Phase E (no candidate cleared the re-arm gate).

## Why it's dormant

Backtest/live track record: **−2,026 pts over 717 trades** (−2.83 pt/trade). The signal family
did not survive out-of-sample. See [`../MANUAL_PIVOT.md`](../MANUAL_PIVOT.md).

## Full snapshot

The complete automated build at the moment of the pivot is tagged and pushed:

```
git checkout legacy/automated-mnq-2026-06-02
```

## How to re-arm it (if you ever want the bot back)

1. `git checkout legacy/automated-mnq-2026-06-02` (or cherry-pick from it).
2. Set `execution.armed: true` in `config/live/tradovate_paper.yaml` (read the warnings in
   [`../../CLAUDE.md`](../../CLAUDE.md) → "Settings to Handle With Care" first).
3. `./pearl.sh soft-restart`, then `./scripts/ops/deploy-from-mac.sh --tv-paper`.

Do **not** re-arm casually — every flip starts real order flow and the strategy is unproven.
