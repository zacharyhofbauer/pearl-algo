# Manual trade journal

Repurposes the existing data + dashboard to log and review **manual** MNQ trades, so the manual
model is measured against the same [`MANUAL_PIVOT.md`](MANUAL_PIVOT.md) validation bar.

Runtime journal output lives in the (gitignored) `journal/` dir at the repo root.

## What you already have to reuse

- **`../data/agent_state/MNQ/trades.db`** — the trade store the bot wrote to. Same schema works
  for hand-entered trades.
- **`../apps/pearl-algo-app/`** — the Next.js dashboard (port 3001) that already renders trades,
  P&L, and stats. Point it at your manual trades and it becomes a trade journal/review surface.
- **`../scripts/backtesting/analyze_backtest.py`** — reuse for expectancy / win-rate / drawdown
  on the manual trade set when you check the validation gate.

## What lands here

- **`journal/signals.jsonl`** — every alert that fired (written by
  [`../alerts/tv_to_discord.py`](../alerts/tv_to_discord.py)), so you can reconcile *signals that
  fired* vs *trades you actually took* (discipline check).

## Minimum viable journaling (validation phase)

You don't need code to start. For each manual trade, capture: timestamp, direction, entry, stop,
target, exit, contracts, R-multiple, and a one-line "did I follow the rules?" note — a spreadsheet
or Discord thread is fine. Roll it into `trades.db` once the loop is proven.

## What to compute at the gate

Per [`MANUAL_PIVOT.md`](MANUAL_PIVOT.md): trade count (≥30), expectancy **net of fees**, max
drawdown vs the MFF trailing-DD limit, and rule-adherence. If all four pass, take it to the
funded account.
