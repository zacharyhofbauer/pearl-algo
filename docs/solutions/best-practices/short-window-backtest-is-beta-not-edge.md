---
module: validation
date: 2026-06-19
problem_type: best_practice
component: development_workflow
severity: high
applies_when: "Judging whether a trading strategy or backtest has real edge before risking funded (MFF) capital"
tags:
  - backtesting
  - validation
  - overfitting
  - prop-firm
  - mnq
  - tradingview
---

# A short-window backtest on a trend-follower is beta, not edge

## Context

While building `pine/mnq_hourly.pine` (a 4h-regime / 1h-execution MNQ strategy) the TradingView
Strategy Tester, run over **"last 90 days"**, showed a beautiful result: **+$6,119, profit factor
7.24, 69% win, a smooth-rising equity curve, max DD 0.04%.** It looked obviously fundable. The
same strategy, run through the repo's cost-honest engine over the **dev window (Oct 2025 → Apr
2026)**, was a **−6.35 pt/trade KILL** (171 trades). The temptation was to "go live" on the green
TradingView panel.

## Guidance

Treat a great-looking backtest as **un-validated until it clears a hard bar** — and recognize that
a trend-following strategy measured over a trending window is just **long the market (beta)**, not
alpha. The bar before any funded use:

1. **Sample ≥ 100 trades.** 39 trades (the TradingView read) is noise; 13 is meaningless.
2. **Both halves green.** Split the window in half; it must be profitable in *both*. A strategy
   that's +$ in the recent rally and −$ in the prior chop is regime beta. **This is the single
   decider.**
3. **Long / regime-diverse window**, not a hand-picked recent 90 days. The +$6k window (Mar–Jun
   2026) was a clean uptrend; the −6.35 window (Oct–Apr) included the chop/downtrend where the
   same logic bled.
4. **Cost sensitivity.** Re-run with commission+slippage zeroed vs honest; if the edge dies, it
   was never there.
5. **Forward paper-test 2+ weeks** before one funded dollar — the only test that can't be
   curve-fit. Log real hand-fills (you fill later and worse than a close-fill backtest).

When two backtests of "the same strategy" disagree wildly, **they are almost always measuring
different things** — confirm period, sample size, fill model, and exact signal logic before
trusting either. Here: different periods (uptrend vs chop), different samples (39 vs 171),
different fill models (optimistic intrabar vs pessimistic + costs).

## Why This Matters

On a prop account the binding constraint is the **trailing drawdown** — one regime change against
a beta-not-edge strategy bleeds the buffer and ends the account. The 90-day curve hides this
precisely because the market only went one way. Acting on the pretty panel is the classic way
funded accounts die. Pearl-algo's ledger is now **20 trials, all KILL** across EMA/VWAP/ORB/gap/
hourly families on both 5m and 1h, long and two-sided — the recurring failure mode is exactly this
(looks good in one regime, dies in the other).

## When to Apply

- Any time a TradingView Strategy Tester / backtest looks fundable, especially over a short or
  recent window, or with < 100 trades.
- Before flipping a research signal to "live" / arming alerts on funded capital.
- When a discretionary trader is excited by a single green equity curve.

## Examples

**The trap (what NOT to conclude):**
> "TradingView shows +$6,119 / PF 7.24 over the last 90 days — let's go live."

**The honest read (what actually held):**
> Same strategy, dev window (Oct→Apr) = −6.35 pt/trade, KILL. The +$6k is the Mar–Jun uptrend.
> It fails *both-halves*. Do not fund. Validate over a year+, then forward-paper.

**Pre-registration discipline that makes the verdict trustworthy** (see
`docs/audits/validation-trial-ledger.md`, Path D): freeze the hypothesis + params + commands in the
ledger and commit *before* running; reproduce a known prior result as an integrity gate (trial 11
pine → n=152, −4.46 exactly) to prove the data hasn't drifted; run dev-window only and never spend
the held-out slice. The fill-in scorecard for doing this on TradingView lives in
`pine/VALIDATION.md`.

**Pine v6 build gotchas surfaced the same session** (separate concern, recorded for reuse): `enum`
+ `input.enum()` can fail the TradingView translator — use `input.string(options=...)` + `switch`;
`force_overlay=true` is valid on `plot`/`plotshape`/`line`/`label` but **not** on `fill()` (fills
ride their plots' z-order); a Pine function can mutate a global array but cannot reassign a scalar
global; `display.pane` keeps decorative plots off the price scale + status line.
