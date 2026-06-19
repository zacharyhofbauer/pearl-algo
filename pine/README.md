# pine/ — TradingView Pine Script alert strategies

These are the **signal source** for the manual model. Each strategy fires a TradingView alert
that gets delivered to your phone via Discord (see `../alerts/`). You read it and place the MNQ
order by hand on MFF.

## Strategies

| File | What it does |
|---|---|
| `mnq_rth_long_bias.pine` | **Manual v4 / honesty build.** EMA(9/21) cross + VWAP, **RTH-only**, **long-biased**, ATR stop/target. Commercial-grade visuals (trend ribbon, VWAP σ-bands, huge BUY/SELL markers, full-candle alert pinstripes, drawn entry/stop/target rays, trend bar-coloring, on-chart dashboard) + a rich JSON alert payload + **MFF discipline guardrails** (max trades/day, daily-loss limit, one-shot `DAILY_STOP`). **The signal is KILLED and entry alerts are MUTED by default** — see the status note below. v4 adds honest Strategy Tester costs, the KILLED-mute switch, and a dev-window Tester gate. Uses **no `request.security()`** (repaint class structurally absent). |
| `mnq_1h_4h_defender.pine` | **Research candidate — alerts MUTED, NOT ledger-registered.** 1h execution / 4h regime: a long-biased breakout-or-pullback entry filtered by the last **confirmed** 4h EMA trend, read via `request.security(..., [close[1], …], lookahead=barmerge.lookahead_off)` — anti-repaint by construction (conservative/stale, never future-leaking; see the file header). **RTH-only**, shorts off by default, ATR stop/target (R=2.5), max-trades/day cap, MFF 5-contract echo, dev-window Tester gate + honest costs (same as the long-bias file), and a `mnq-1h-4h-defender` JSON alert payload. Mirrors the Python `hourly_defender_signals` validation candidate. **Unlike the long-bias file it DOES use `request.security`** — its repaint safety rests on the `lookahead_off` discipline, not on structural absence. |

## On-chart visuals (Manual v4 / pinstripe)

**Two visual postures (v4.1).** While `Signal status` is **KILLED — alerts muted** (the
shipped default), the chart stays *quiet*: tiny direction-tinted study triangles at signal bars,
plus ribbon/VWAP/bar-coloring and the dashboard (which still carries Entry/Stop/Target
numbers). The loud manual-alert kit — huge BUY/SELL markers, big callouts, pinstripe,
signal flash, and trade-level rays — renders **only** when status is flipped to
**Candidate — alerts on**. A killed signal does not shout trade instructions. The
pinstripe and callout are also single-instance managed drawings now (the prior one is
deleted on each new signal), fixing the v3 bug where they accumulated forever and
buried the chart under stacked boxes and giant stripes.

All toggleable in the **Style** input group (colors are pickers):

- **Dashboard** — compact, semi-transparent status table (position selectable, default middle-right) with trend, session, signal status, explicit `HTF Filter: OFF`, active signal, last signal, entry/stop/target, trades-today, and validation state.
- **EMA ribbon** — fill between fast/slow EMAs, green/red by trend.
- **VWAP** (+ optional ±1σ bands).
- **Signal markers** — huge BUY MNQ / SELL MNQ triangles at the exact bar that fires.
- **Alert pinstripe** — default-on bright full-candle stripe on every manual alert event. Entry alerts get green/red BUY/SELL stripes; guardrail alerts get an orange DAILY STOP stripe.
- **Big signal callouts** — default-on labels that print direction, entry, stop, and target directly on the signal candle.
- **Signal flash** — default-on green/red/orange background wash on the firing bar so the trigger is obvious even on a crowded chart.
- **Trade levels** — entry (solid) + stop/target (dashed) rays drawn forward with price labels; only the current setup is shown.
- **Trend bar-coloring** — candles tinted by EMA trend.
- Session shading: grey outside RTH, red wash when entries are muted by a guardrail.

> ⚠️ **Honest status (updated 2026-06-12):** this EMA/VWAP signal **failed** cost-honest
> validation (trial 11: **−4.46 pt/trade, n=152**, dev-clean). The pre-registered replacement
> family — overnight-gap conditioning (small-gap fade / all-gaps fade / large-gap continuation,
> trials 16–18) — **also failed**: −25.61 / −1.25 / −220.07 pt/trade, all KILL at Tier-0. Per the
> pre-registered gate, **no signal swap shipped and entry alerts are muted by default** (the
> `Signal status` input). Full record: `docs/audits/validation-trial-ledger.md`. Flip alerts on
> ONLY when a future pre-registered family clears the ledger's promotion gate.

The original indicator library (Volume, VWAP_AA, EMA_Crossover, Supply & Demand, key levels,
sessions) lives in `../resources/pinescript/pearlbot/` — use those as building blocks.

## If markers are not visible

- Make sure the chart label starts with **PearlAlgo PINSTRIPE MNQ — Manual v4**. If TradingView still shows **Manual v3**, **RTH Long-Bias EMA/VWAP**, or any non-pinstripe name, the chart is running an older saved script.
- In the strategy settings, keep **Signal markers**, **Alert pinstripe**, **Big signal callouts**, and **Signal flash** enabled in the Style group.
- Use **Condition = PearlAlgo PINSTRIPE MNQ — Manual v4** and trigger **Any alert() function call** so chart signals, strategy entries, and Discord payloads stay tied to the same Pine source. Avoid strategy order-fill placeholders like `{{strategy.order.action}}`; those can notify on fills/exits that are not manual entry alerts.
- **No alerts arriving is the DEFAULT.** The `Signal status` input ships as "KILLED — alerts muted" because the signal failed validation. Markers/visuals still draw; only `alert()` delivery is muted.

## How to wire an alert (per strategy)

1. Paste the `.pine` into TradingView → **Pine Editor** → *Add to chart* (use an **MNQ** chart,
   your trading timeframe).
2. Check the **Strategy Tester** tab — this is your first, free backtest. A green report is
   NOT a go signal: run the **Strategy Tester honesty checklist** below before believing
   anything it says, and remember the binding verdicts live in
   `docs/audits/validation-trial-ledger.md`, not in the Tester.
3. Create an alert: **Condition = PearlAlgo PINSTRIPE MNQ — Manual v4**, trigger = **"Any alert() function call"**,
   **Webhook URL** = your receiver (or Discord webhook directly — see `../alerts/`).
   *(There are no `alertcondition()` triggers — Pine cannot create alerts from
   `alertcondition()` inside a strategy script, so v4.1 removed those dead lines. The
   "Any alert() function call" wiring above is the only working path.)*
4. The alert body is auto-filled by the strategy's `alert()` JSON (v3 — adds `status`):
   ```json
   {"strat":"mnq-rth-long-bias","v":3,"status":"Candidate — alerts on","action":"BUY","symbol":"MNQ1!","tf":"5",
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

## Strategy Tester honesty checklist (run BEFORE believing any Tester report)

TradingView's Strategy Tester defaults to a fantasy: zero commission, zero slippage, and a
synthetic intrabar price path. v4 bakes the honest settings into the code; this checklist is
how you verify nothing has un-baked them and the report means what it appears to mean.

1. **Costs are in code, not the UI.** The declaration sets
   `commission_type = strategy.commission.cash_per_contract`, `commission_value = 0.95`
   (Tradovate free-tier all-in per side, 2025-11 schedule: $0.39 commission + $0.35 CME
   exchange + $0.02 NFA + $0.19 clearing), `slippage = 1` (1 tick = $0.50 adverse on
   market/stop fills; limit targets never slip), `backtest_fill_limits_assumption = 1` (no
   touch-fills). That models ~$2.40–$2.90 per round trip — at/above the engine's modeled
   costs and the real broker bill. ⚠️ Values changed in the chart's **Properties** tab
   silently OVERRIDE the code for that chart — reset to defaults before reading any report.
2. **Cost sensitivity.** Re-run with commission/slippage zeroed vs the honest settings. If
   the edge dies between the two, there is no edge — that exact failure killed all four
   2026-06-03 families and the gap family (trial 17 was break-even gross, dead net).
3. **Frozen stops/targets.** Stops/targets are structure-derived (ATR at signal, gap
   geometry) and registered in the ledger. Tuning ANY input against the Tester and re-reading
   is a new trial that needs a new ledger pre-registration — `n_trials` exists because every
   peek is a draw from the multiple-testing well.
4. **Dev-window discipline.** The `Limit Strategy Tester to dev window` input (default ON)
   restricts order placement to 2025-10-26 → 2026-04-19 — the same registered window the
   validation engine reads. The held-out slice (2026-04-20+) is a ONE-SHOT Tier-5 resource:
   reading it casually in the Tester spends it forever. Deep Backtesting (Premium+) must use
   the same date range.
5. **Repaint checks.** `calc_on_every_tick = false`, `process_orders_on_close = true`, all
   `alert()` calls fire once per bar close, and **`mnq_rth_long_bias.pine` uses NO
   `request.security()`** — for that file the whole HTF-lookahead repaint class is
   structurally absent. (Its sibling `mnq_1h_4h_defender.pine` DOES read a 4h regime via
   `request.security`; that file's anti-repaint safety instead rests on the `close[1]` +
   `lookahead=barmerge.lookahead_off` discipline documented in its header — conservative/stale,
   never future-leaking, so bar-replay it across a few 4h transitions to confirm the regime
   EMAs never revise intrabar.) Verify the Tester shows no warning icon, and bar-replay a few
   sessions: signals must appear only at bar close and never vanish.
6. **Broker-emulator skepticism.** Without Bar Magnifier the emulator invents the intrabar
   path (open→high→low→close or open→low→high→close by which extreme is nearer the open).
   When a bar's range contains BOTH the stop and the target, the credited outcome is pure
   heuristic. Audit the List of Trades for those bars and for same-bar entry+exit trades;
   re-check with Bar Magnifier (Premium+) where available.
7. **Contract-roll sanity** — roll boundaries create phantom gaps: on roll-adjacent sessions
   the open-vs-prior-close difference includes the calendar spread, and back-adjusted vs
   unadjusted charts disagree exactly there. The registered trials exclude pinned
   roll-adjacent sessions (2025-12-22, 2026-03-23); any Pine gap signal must skip the same
   dates. Also compare `MNQ1!` back-adjusted vs unadjusted for anything dollar-anchored, and
   note ETH vs RTH chart sessions change VWAP anchoring.
8. **Paper period.** Before ANY funded trade on a future validated candidate: 2+ weeks of
   live bar-close alerts journaled against your actual hand-fill prices. A human acting on a
   phone alert fills later and worse than the emulator's close-price fill — this is the only
   test of that gap, and it calibrates whether 1 tick of modeled slippage is enough.

## MFF discipline guardrails (v2 — robust levers, not signal)

These mute alerts/entries to protect the funded account; tune in the "MFF guardrails" input group:

- **Max trades / day** (default 3, `0` = off) — after N entries, further signals are muted until
  the next RTH session. Counts **signals** (not fills), so it works in live alerting regardless of
  the Tester window or mute state. **This is the only guardrail that protects you live.**
- **Daily loss limit $** (default off) — ⚠️ **Tester-only in v4.** It reads `strategy.netprofit`
  (hypothetical emulator fills), and with the dev-window Tester gate ON (the shipped default)
  no emulator fills occur on live bars — so this guardrail and the dashboard Daily P&L row are
  frozen at $0 in live use. Your real P&L lives at the broker; track the daily loss limit there.
- **`DAILY_STOP` alert** — fires **once** when a cap trips (live: the trades/day cap only, per
  the limitation above), so you get a "stop for the day" ping.
- **Risk context** — every entry alert carries `risk_pts` and `risk_usd_per_contract` (using
  TradingView's real point value) so you size against the MFF trailing drawdown, not by guesswork.
