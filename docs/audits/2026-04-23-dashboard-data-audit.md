# Dashboard Data Audit — 2026-04-23

Status: **5 real discrepancies found.** 3 require code changes, 2 are data hygiene.

## Scope
Cross-checks each pearlalgo.io dashboard tab (Positions, History, Stats, Analytics, Signals) against the raw agent state on disk and Tradovate broker state. Ran against a live MNQ session at 2026-04-23 07:18 UTC with the agent running on Tradovate Paper.

Inputs (copied from Beelink `~/projects/pearl-algo/data/agent_state/MNQ/`):
- `state.json` — agent snapshot + `tradovate_account`
- `performance.json` — 971 closed trades
- `tradovate_fills.json` — 1,942 broker fills
- `signals.jsonl` — 6,258 signal lifecycle events
- `signal_audit.jsonl` — 196 audit entries

Script: `/tmp/pearl-audit/audit.py` (not committed; copy under `scripts/ops/` if you want it recurring).

## What the dashboard was showing at audit time
- Header: `EQUITY $43,470.86 | W/L 1/0`
- Dock dock header extras (post-PR-23): `Day +$6.70`
- Info strip: `Day Net +$6.70 | Week -$951.20 | Fees -$285.80`
- Tabs: `Positions 0 · History 50 · Stats · Analytics · Signals`
- Order stats: `Filled 4 · Cancelled 2`
- Top-right: `EXEC DISARM` (orange)

## Ground truth for today (trading day = 17:00 ET prev = 21:00 UTC)
Window: `2026-04-22T21:00Z .. 2026-04-23T21:00Z`

**Broker (source of truth):**
| Fill | UTC time | Side | Qty | Price | Net pos |
|---|---|---|---|---|---|
| 1 | 05:26:53 | Buy | 1 | 26940.00 | 1 (open long) |
| 2 | 05:51:55 | Sell | 1 | 26965.75 | 0 (close) → +$51.50 gross |
| 3 | 06:13:39 | Sell | 1 | 26980.75 | -1 (open short) |
| 4 | 06:17:42 | Buy | 1 | 27001.25 | 0 (close) → -$41.00 gross |

Gross: +$10.50. Commissions ~$3.80. **Net realized PnL = +$6.70** (matches `state.tradovate_account.realized_pnl`). **True W/L = 1/1.**

---

## Findings

### 🚨 F1 — W/L counter is wrong (dashboard says 1/0, truth is 1/1)
- Dashboard: `W/L 1/0`
- Source data: 1 winning round-trip (+$51.50 → TARGET HIT), 1 losing round-trip (-$41.00 → STOP LOSS). Both exited before audit time.
- `state.daily_wins` and `state.daily_losses` are both `null`. The non-null `1` in the display must be computed elsewhere (likely `/api/agent-state` server-side) and the computation misses losses.
- **Hypothesis**: counter increments on `exit_reason=="take_profit"` but not on `stop_loss` — i.e. the map of "exit_reason → win/loss" is incomplete. Or it filters by `pnl > 0` / `pnl < 0` but uses `performance.json` (which has estimated PnL — see F3) instead of fills.
- **Suggested fix:** compute `daily_wins` / `daily_losses` server-side directly from `tradovate_fills.json` paired-trade output, with `pnl > 0` → win, `pnl < 0` → loss, `pnl == 0` → flat. Same source as Day Net.

### 🚨 F2 — EXEC DISARM vs "system armed and watching the tape" contradiction
- Toolbar: `EXEC DISARM` (orange)
- Dock empty-state: `No open positions — system armed and watching the tape.`
- Meanwhile: broker actually executed 4 fills in the last hour, so *something* is arming. Per [reference_pearl_algo_arm_flag.md](../../../.claude/projects/-Users-pearlassistant/memory/reference_pearl_algo_arm_flag.md), arming has a 5-minute TTL file-drop. Toolbar likely reads current arm state; dock string is hardcoded.
- **Where**: [TradeDockPanel.tsx:846,849](../../apps/pearl-algo-app/components/TradeDockPanel.tsx#L846) — the string is a literal, not driven by `execArmed` or similar prop.
- **Suggested fix**: accept `execArmed?: boolean` prop on TradeDockPanel; render "armed and watching" vs "disarmed — signals will not execute" accordingly. Wire from `agentState?.execution?.armed` (verify the field name).

### 🚨 F3 — 99.5% of performance.json PnL is estimated, not fill-matched
- `pnl_source` breakdown over 971 trades: **966 estimated**, **5 fill_matched**.
- "Estimated" PnL is computed from signal-time TP/SL levels, not actual fill prices. For the two trades today:
  - Perf.json: LONG +$47.86 (estimated exit 26965.18, actual 26965.75 → 57¢ short)
  - Perf.json: SHORT -$60.89 (estimated entry 26986.00, actual 26980.75 → $5.25 worse entry × 2ct = ~-$20 drag on the estimate)
  - **Perf.json today sum: -$13.04. Broker actual today net: +$6.70. Delta: $19.74.**
- Stats/Analytics tabs feed from `performance.json` in IBKR Virtual mode (and partially in Tradovate Paper mode per `/api/performance-summary`). Historical totals like "All Time", "Month", "Week" displayed in the Stats tab are **estimates, not actuals** for 966 of 971 trades.
- **Suggested fix (data hygiene)**: backfill `performance.json` by replacing the 966 estimated entries with fill-matched PnL from `tradovate_fills.json` where a matching `signal_id` (or time-window match) exists. Pre-2026-04-21 (IBKR virtual era) entries may have no broker fills — mark them explicitly as `pnl_source: "virtual_ibkr"` instead of `"estimated"` so Stats tab can warn the user or exclude them.
- **Alternative (UI-only)**: Stats tab badges each value with `(est.)` when `pnl_source != "fill_matched"`. Less invasive but leaves perf.json inaccurate for agents / other consumers.

### 🟡 F4 — Agent daily counters never populated in state.json
- `state.daily_wins`, `state.daily_losses`, `state.daily_pnl` all `null` at audit time.
- Not necessarily a bug — these may be computed at API-response time rather than persisted. But when they're `null`, the dashboard's `agentState.daily_wins ?? 0` falls back to 0, and any consumer treating `null` as "no trades" gets it wrong.
- **Suggested fix**: either (a) populate these in the agent loop (one write per closed trade), or (b) explicitly mark them "computed server-side; do not read from state.json" and remove from the snapshot to prevent stale-looking nulls.

### 🟡 F5 — 83% of signals are duplicates
- `signals.jsonl` has 6,258 rows. **5,180 have `duplicate=true`.** Only 1,078 are fresh signals.
- Of the 6,258 rows:
  - 5,517 status=`generated`, 371 `entered`, 370 `exited` — so 371 real entries (matches the 371 `placed` `_execution_status`)
  - Top rejection reasons: `max_position_size (5/5) reached` (731), `skipped:not_armed` (654), `opposite_direction_blocked` (536), plus cooldown gates firing thousands of times
- **Interpretation**: the pinescript signal generator fires every bar close (15s) and most re-fires are deduplicated at the gate. The dedup IS working — the `duplicate=true` flag is accurate — but the Signals tab's `displayRecentSignals.slice(0, 20)` shows the same signal 20 different times when a signal has been re-tried 20x in the last minutes. That's what "cuts off signals" felt like: the Signals tab view is dominated by repeats of the same underlying decision.
- **Suggested fix**: in `/api/signals-panel`, collapse the slice to unique `signal_id` BEFORE taking the first 20. Also add a UI chip showing "fired N times, 1 unique signal" when collapsing.

---

## Other observations (not bugs, worth tracking)

- **Chart data window ≈ 7 hours on 5m TF**: caches are rolling-window (`candle_cache_MNQ_5m_500` = last 500 bars = ~41h, `candle_cache_MNQ_1m_500` = ~8h). On 5m TF the chart only displays last ~500 bars. Tied to the candle-archival design decision (next task).
- **Session signal counters in state.json are tiny vs cumulative**: `signal_count_session=1, signals_sent_session=1` vs cumulative `signal_count=5812, signals_sent=973`. Session resets look correct; cumulative dwarfs it because `signals_sent=973` tracks over the whole agent lifetime, not just today. Dashboard should clarify which number is which when displayed.
- **`signals_archive.jsonl`** is 25MB and not touched since 2026-04-23T06:30. Any audit depending on older signals (>~today) needs to union signals.jsonl + signals_archive.jsonl; the audit script here only looked at signals.jsonl.
- **`performance.json` has 601 entries without a matching `exited` event** in signals.jsonl — expected, those are pre-archive rotation. Not a bug.

## Recommended action plan
1. **Fix F1 and F2** — they're the most visible to a trader. Both are small PRs (W/L computation + exec-armed prop). ~1–2h total.
2. **Fix F5** — collapse duplicates in `/api/signals-panel`. Small backend change. ~1h.
3. **Decide on F3** — this is the big one. Either backfill perf.json from fills (pre-requisite for trusting any historical stats on the dashboard) or flag estimates in the UI. Discuss before implementing.
4. **F4** is cosmetic — can pair with F1 since they share a data source.

## Trust-but-verify: numbers a trader can spot-check
- Dock's `Day +$6.70` matches `state.tradovate_account.realized_pnl` ✅
- Dock's `Equity $43,470.86` matches `state.tradovate_account.equity` ✅
- Info strip's `Week -$951.20` matches `state.tradovate_account.week_realized_pnl` ✅
- Order stats `Filled 4 / Cancelled 2` matches `state.tradovate_account.order_stats` ✅
- `W/L 1/0` **does not match** reality (should be 1/1) ❌ → see F1
- Stats tab history PnL is **estimated** for 966/971 trades → see F3
