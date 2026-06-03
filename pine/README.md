# pine/ — TradingView Pine Script alert strategies

These are the **signal source** for the manual model. Each strategy fires a TradingView alert
that gets delivered to your phone via Discord (see `../alerts/`). You read it and place the MNQ
order by hand on MFF.

## Strategies

| File | What it does |
|---|---|
| `mnq_rth_long_bias.pine` | EMA(9/21) cross + VWAP filter, **RTH-only**, **long-biased**, ATR stop/target. **v2** adds a rich JSON alert payload + **MFF discipline guardrails** (max trades/day, daily-loss limit, one-shot `DAILY_STOP` alert). The **signal is unchanged and unproven** — see the status note below. |

> ⚠️ **Honest status (2026-06-03):** this EMA/VWAP signal **failed** cost-viability validation
> (`docs/audits/validation-trial-ledger.md`). v2 deliberately does **not** add more indicator
> confluence (that curve-fitting cost the auto-bot −2,026 pts). It only makes the *alerts* richer
> and adds *discipline* guardrails. Paper-trade the validation gate before risking funded capital.

The original indicator library (Volume, VWAP_AA, EMA_Crossover, Supply & Demand, key levels,
sessions) lives in `../resources/pinescript/pearlbot/` — use those as building blocks.

## How to wire an alert (per strategy)

1. Paste the `.pine` into TradingView → **Pine Editor** → *Add to chart* (use an **MNQ** chart,
   your trading timeframe).
2. Check the **Strategy Tester** tab — this is your first, free backtest. If it's not green on a
   meaningful sample, fix the strategy *before* trading it.
3. Create an alert: **Condition = the strategy**, trigger = **"Any alert() function call"**,
   **Webhook URL** = your receiver (or Discord webhook directly — see `../alerts/`).
   *(Prefer condition-based alerts? The script also exposes `alertcondition()` triggers
   "PearlAlgo MNQ — Long/Short" with a minimal placeholder payload.)*
4. The alert body is auto-filled by the strategy's `alert()` JSON (v2):
   ```json
   {"strat":"mnq-rth-long-bias","v":2,"action":"BUY","symbol":"MNQ1!","tf":"5",
    "bar_time":"2026-06-03 10:15 ET","entry":21850.25,"stop":21835.0,"target":21880.75,
    "atr":10.17,"rr":2.0,"risk_pts":15.25,"risk_usd_per_contract":30.5,"risk_usd_total":30.5,
    "contracts":1,"max_contracts":5,"trades_today":1,"reason":"EMA9>21 cross, above VWAP"}
   ```
   A `DAILY_STOP` payload (`action`,`reason`,`daily_pnl_usd`,`trades_today`) fires once when a
   guardrail trips. The `../alerts/` receiver renders all of these as Discord embeds.

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

## MFF discipline guardrails (v2 — robust levers, not signal)

These mute alerts/entries to protect the funded account; tune in the "MFF guardrails" input group:

- **Max trades / day** (default 3, `0` = off) — after N entries, further signals are muted until
  the next RTH session.
- **Daily loss limit $** (default off) — when realized session P&L breaches `-$X`, signals mute.
- **`DAILY_STOP` alert** — fires **once** when either cap trips, so you get a "stop for the day" ping.
- **Risk context** — every entry alert carries `risk_pts` and `risk_usd_per_contract` (using
  TradingView's real point value) so you size against the MFF trailing drawdown, not by guesswork.
