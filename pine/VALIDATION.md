# Validating `mnq_hourly.pine` on TradingView

This is the **honest scorecard for the surface you actually trade** — the Pine Strategy Tester
on TradingView, hand-filled as you run each timeframe. The Python ledger
(`docs/audits/validation-trial-ledger.md`, Path D) is a *cousin* on an offline archive; it KILLED
the 1h family at −6.35 pt/trade, but **this** file is what governs whether you trade it, because
it's your exact strategy on your exact data.

**Golden rule: do not risk one funded MFF dollar on a config until it clears the bar below AND
passes a forward paper-test.** A pretty Tester panel over a hand-picked window is not edge.

---

## The bar — a config PASSES only if ALL FOUR hold

| Check | Threshold | Why |
|---|---|---|
| **Sample** | **≥ 100 trades** | 13 trades is noise. You need a real sample. |
| **Profit factor** | **≥ 1.3** (net of costs) | The script bakes $0.95/side + 1-tick slippage; PF is already honest. |
| **Both halves green** ⭐ | profitable in the **first half AND the second half** of the window | THE decider — separates real edge from "caught the 2026 rally" (beta). |
| **Cost-sensitive** | edge survives costs-on vs costs-zeroed | If it dies when costs are real, there was no edge. |

⭐ If a config is only green in the recent uptrend, it's **beta, not edge** — do not trade it.

---

## How to run each timeframe (TradingView)

1. Add `mnq_hourly.pine` to an MNQ chart (any chart TF; 5m–1h is fine).
2. Settings → **Execution (1h) → Execution timeframe** = the TF you're testing: `60` (1h), `30`, `15`, or `240` (4h). **Start with 60.**
3. Settings → **Honesty** → leave **"Limit Strategy Tester to dev window" OFF** (full-sample read; this is now the default).
4. **Strategy Tester → Deep Backtesting → set the widest date range your plan allows** (a year+ if you can).
5. Run it. Read the **Overview** tab for net P&L, profit factor, total trades, max drawdown.
6. For the **both-halves** check: split the date range in two, run each half, record both. (Or read the equity curve — is it rising in BOTH halves, or flat/down until the recent rally?)
7. For **cost-sensitivity**: note the result, then in Settings → Properties set commission + slippage to 0, re-run, compare. The gap is your cost drag.

> Test long-only first (Execution → uncheck *Allow shorts*), then two-sided. The Python run found
> shorts made it **worse** — confirm or refute that here.

---

## Scorecard — fill this in

| TF | Side | Window (from→to) | Trades | PF | Net P&L | Max DD % | H1 P&L | H2 P&L | Both halves green? | Cost-survives? | PASS? |
|----|------|------------------|--------|----|---------|----------|--------|--------|--------------------|----------------|-------|
| 1h | long |  |  |  |  |  |  |  |  |  |  |
| 1h | two-sided |  |  |  |  |  |  |  |  |  |  |
| 30m | long |  |  |  |  |  |  |  |  |  |  |
| 30m | two-sided |  |  |  |  |  |  |  |  |  |  |
| 15m | long |  |  |  |  |  |  |  |  |  |  |
| 4h | long |  |  |  |  |  |  |  |  |  |  |

---

## How to read it

- **Both-halves is the whole ballgame.** A config that's +$2k in H2 (the rally) and −$1k in H1 is
  not a strategy — it's a long-the-dip bet on one regime. KILL it.
- **Multiple-testing caveat.** Testing 4 timeframes × 2 sides = 8 configs. If you pick the single
  best, it's partly luck (you searched 8 times). That's *exactly* why the forward paper-test below
  is non-negotiable before funding.
- **If 1h fails both-halves, 30m/15m won't save it** — same family, more noise. That's your signal
  to stop trading this signal family and hunt a *genuinely different* edge (e.g. market internals
  as a primary trigger), not another timeframe.

---

## Forward paper-test — the only test that can't be curve-fit

Run this on any config that passed the bar above, BEFORE funded use:

1. Settings → **Honesty → Signal status = "Candidate — alerts on"** (arms `alert()` delivery).
2. Wire the alert → Discord (`alerts/tv_to_discord.py`, see `alerts/README.md`).
3. For **2+ weeks**, take every alert as a paper trade — log your **real hand-fill price** (you fill
   later and worse than the Tester's close-fill; this measures that gap).
4. Compare paper results to the backtest. If paper holds up → fundable. If it falls apart → the
   backtest was optimistic; do not fund.

| Date | TF | Dir | Alert px | Your fill px | Exit px | P&L (pt) | Notes |
|------|----|----|----------|--------------|---------|----------|-------|
|  |  |  |  |  |  |  |  |

---

## Decision rule

- **Backtest bar PASS + forward paper green → fundable** (start at minimum MFF size; the risk engine
  sizes off your trailing-DD buffer).
- **Fails both-halves at every TF → stop trading this family.** The honest next move is a different
  *signal*, not a different timeframe. Pre-register it (ledger Path E) and test it the same way.

---

_Status: as of 2026-06-19 the Python ledger has this family at KILL (Path D, n_trials 20). This TV
scorecard is empty — fill it in to make the call on your own surface._
