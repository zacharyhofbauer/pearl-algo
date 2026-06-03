# Manual TradingView-Alert Pivot

**Date:** 2026-06-02
**Decision:** Pivot pearl-algo from a fully-automated futures bot to a **manual, discretionary**
model driven by TradingView Pine Script alerts, executed by hand on a **My Funded Futures (MFF)**
MNQ account.

---

## Why we pivoted

Both automated trading efforts were disproven on their own evidence:

| System | What it was | Verdict |
| --- | --- | --- |
| **pearl-algo** (this repo) | Automated MNQ scalper (IBKR data + Tradovate exec) | **−2,026 pts over 717 trades** (−2.83 pt/trade). Parked at Phase E — no candidate cleared the re-arm gate. |
| **pearl-arbitrage** | Kalshi prediction-market arb | Net negative. Binding constraint was **bankroll × venue × adverse selection**, not signal quality. |

The honest read: at small personal bankroll, automated edge did not survive out-of-sample, and
the prediction-market microstructure punished a small taker. A prop-firm + manual model changes
**the binding constraint**:

- **Capital** is provisioned by MFF, not a ~$100 personal bankroll.
- **Microstructure**: MNQ is deeply liquid — no latency arms race, minimal adverse selection.
- **Execution**: by hand, a few trades a day — we stop fighting the parts that killed the bots.

## The honest caveat (read this)

This is **not a clean slate**. The Pine signal family here (EMA / VWAP / regime) is the *same*
family the automated bot lost ~2,000 pts on. The pivot's real, new variable is **operator
discretion** — can a human reading alerts and managing risk beat the mechanical version?

That is an unproven bet. The constraint hasn't disappeared, it has **moved**: from "$100 bankroll"
to "**pass the MFF eval + survive the trailing drawdown + actually have discretionary edge**."
So we **validate cheaply before risking the funded account.**

---

## Known edges (from the 922-trade analysis — encode these)

- **RTH only.** Overnight (18:00–08:30 ET) historically *lost money* (−$4,477 net). Trade the
  regular session; the starter Pine strategy gates to RTH by default.
- **Long bias.** Short trades had a poor win rate. The starter strategy is long-preferred
  (shorts off by default; enable deliberately).
- **No heavy gating.** Prior hard hour/direction/regime vetoes over-fit; prefer a small number of
  robust filters over many.

---

## MFF account constraints (confirm against your exact plan)

> The repo's operating note: *MFF compliance expects max 5 MNQ total; TraderSyncer copies
> demo → live.* These are MFF-style rules — **verify the exact figures for your account tier
> before trading.**

- **Max contracts:** 5 MNQ total.
- **Trailing drawdown:** the killer rule — one bad cluster of trades liquidates the account. Size
  so a string of stops cannot breach it.
- **Daily loss limit:** stop for the day when hit; the strategy/journal should make this loud.
- **Consistency rule (payout):** no single day should be an outsized share of total profit — spread
  gains across days.

---

## Validation gate — pre-commit BEFORE risking the funded account

Run the full loop (Pine alert → Discord → manual entry) on an **MFF demo/eval (or sim)** account
first. Decide the bar **now**, not after the fact:

1. **Sample:** ≥ 30 trades (a "2-week" window of a few trades/day is too few to trust).
2. **Expectancy:** positive **net of commissions** (≈ round-trip fees per MNQ — use MFF/Tradovate's
   actual number, not gross points).
3. **Drawdown:** max peak-to-trough stays **inside the MFF trailing-DD limit** for the target tier.
4. **Discipline:** you actually followed the rules (no revenge trades, respected the daily stop).

**If it clears all four → take it to the funded account.** If not → the manual edge isn't there
either, and we've spent days, not months, finding out.

---

## Architecture (active model)

```text
TradingView (pine/*.pine, alertcondition/alert)
        │  webhook
        ▼
alerts/  (TradingView webhook → Discord)   ── zero-server option also documented
        │  Discord notification on your phone
        ▼
YOU      place the MNQ order by hand on MFF (TraderSyncer copies demo→live)
        │
        ▼
journal/ (trades.db + dashboard)  ── log + review every manual trade
        ▲
backtest (scripts/backtesting/)   ── vet a Pine idea before trading it
```

The automated stack (`src/pearlalgo/market_agent`, `execution/tradovate`, IBKR providers, systemd)
is **dormant**, preserved at tag `legacy/automated-mnq-2026-06-02`. See [`legacy/README.md`](legacy/README.md) to re-arm.
