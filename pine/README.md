# pine/ — TradingView Pine Script alert strategies

These are the **signal source** for the manual model. Each strategy fires a TradingView alert
that gets delivered to your phone via Discord (see `../alerts/`). You read it and place the MNQ
order by hand on MFF.

## Strategies

| File | What it does |
|---|---|
| `mnq_rth_long_bias.pine` | EMA(9/21) cross + VWAP filter, **RTH-only**, **long-biased**, ATR stop/target. Encodes the 922-trade edges (overnight loses, shorts weak). The starting template to validate. |

The original indicator library (Volume, VWAP_AA, EMA_Crossover, Supply & Demand, key levels,
sessions) lives in `../resources/pinescript/pearlbot/` — use those as building blocks.

## How to wire an alert (per strategy)

1. Paste the `.pine` into TradingView → **Pine Editor** → *Add to chart* (use an **MNQ** chart,
   your trading timeframe).
2. Check the **Strategy Tester** tab — this is your first, free backtest. If it's not green on a
   meaningful sample, fix the strategy *before* trading it.
3. Create an alert: **Condition = the strategy**, trigger = **"Any alert() function call"**,
   **Webhook URL** = your receiver (or Discord webhook directly — see `../alerts/`).
4. The alert body is auto-filled by the strategy's `alert()` JSON:
   `{"strat":...,"action":"BUY","symbol":"MNQ...","entry":...,"stop":...,"target":...,"max_contracts":5}`

## Two delivery modes

- **Structured (recommended):** point the webhook at `../alerts/tv_to_discord.py`. It parses the
  JSON, formats a clean Discord message, and logs the signal so the journal can reconcile it.
- **Zero-server:** point the webhook straight at a Discord channel webhook and set the TV alert
  *message* to Discord's format, e.g. `{"content":"BUY MNQ @ {{close}} — manual entry"}`. No
  server/tunnel, but no journaling. Good enough for the first validation pass.

## Rules baked in (don't override without a reason)

- **Max 5 MNQ total** (MFF compliance) — in the payload as `max_contracts`.
- **RTH only** — strategy flattens at the RTH close; never hold overnight.
- **Long bias** — shorts are off by default.
