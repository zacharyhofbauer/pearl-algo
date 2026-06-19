# Spec — Premium Hourly MNQ TradingView script (Pine v6)

**Status:** DRAFT for approval (2026-06-19). No build until approved.
**Author:** Claude (research → spec). Sources: in-repo validation ledger + Pine v6 best-practices research.

---

## 0. TL;DR / the honest framing (read first)

This is a **UX/visual deliverable on a not-yet-validated signal**, not the activation of a
profitable edge. The research found:

- **No hourly edge exists in evidence.** `docs/audits/validation-trial-ledger.md` has **18 trials,
  all 5m, all KILL/fail.** The 1h/4h "defender" is a **research candidate, NOT ledger-registered,
  with NO backtest.** Its 1h entry (EMA breakout/pullback) is structurally the same EMA family that
  was killed (trial 11: −4.46 pt/trade). The 922-trade history shows only *session* edge (RTH >
  overnight) and *direction* edge (longs > shorts) — nothing hourly-specific.
- **Therefore:** we build a **premium hourly-execution toolkit** that looks world-class and is
  correct + honest, with **alerts muted (research posture)**. Looking premium ≠ being profitable.
  An hourly long-only RTH strategy also fires **few signals (a handful/week)** — "premium" here is
  the cloud/dashboard/cleanliness, NOT a busy LuxAlgo-style signal stream. We cannot add signals
  without changing the frozen signal, which requires ledger pre-registration.
- **If you want a *real* hourly edge**, that is a **separate track** (Section 9): pre-register an
  hourly family in the ledger, backtest on the dev window only, pass Tier-0 + split-half stability.
  Base rate says KILL (13 of 15 prior trials died). That track is optional and independent of this
  visual rebuild.

---

## 1. Goal & non-goals

**Goal:** One polished, LuxAlgo/ChartPrime-grade MNQ Pine v6 script whose execution model is
**hourly (1h execution / 4h regime)**, with a clean uncluttered visual layer + corner dashboard,
the robustness-sweep diagnostic, MFF guardrails, and the honest validation posture.

**Non-goals:** Claiming/implying edge; turning alerts on for a funded account; making the chart
"busy"; changing the signal math (that is a ledger-gated validation task, not a UX task).

---

## 2. Decision: consolidate on the defender as the base

- **Base = `mnq_1h_4h_defender.pine`** — it is already the premium template (corner table, tiny
  muted markers, correct tuple `request.security(..., lookahead_off)` HTF read). Promote it to the
  primary script: **"PearlAlgo MNQ — Hourly v5"**.
- **Port in** from `mnq_rth_long_bias.pine`: the **robustness-sweep** block (read-only diagnostic)
  and the richer dashboard rows, adapted to the 1h/4h model.
- **Demote `mnq_rth_long_bias.pine`** to a clearly-labeled legacy/study file (the 5m EMA/VWAP
  study + its sweep stays for reference). Decision point D1 (Section 10): keep as legacy vs delete.

---

## 3. Functional requirements (UNCHANGED signal — UX only)

The signal logic stays exactly as `hourly_defender_signals` / the defender Pine (frozen; any change
is a new ledger trial):

- **Regime (4h):** last *confirmed* 4h bar; EMA fast(8)/slow(21); up = `close[1]>fast[1]>slow[1]
  and fast[1]>=fast[2]`; down = mirror; else neutral. Anti-repaint via `[1]` + `lookahead_off`.
- **Execution (1h):** require `timeframe.multiplier == 60`. Entries = breakout (close *crosses*
  prior-N high) OR pullback (close crosses EMA20), gated by matching 4h regime + RTH + trades/day
  cap + valid ATR.
- **Exits:** stop = 1.5×ATR; target = 1.5×ATR×2.5 (R=2.5); flatten at RTH close (never overnight).
- **Constraints (preserve, quote-for-quote):** MFF max 5 MNQ; RTH-only (flatten at close);
  long-bias (shorts off by default, labeled "weak win rate"); max trades/day cap (the only live
  guardrail); dev-window Tester gate; never spend held-out slice (≥2026-04-20); honest costs
  ($0.95/side + 1-tick slippage on entry/stop, none on limit target).

---

## 4. Visual system spec (the premium rebuild)

All from the Pine v6 best-practices research. **Drawing-count discipline:** declare
`max_labels_count=200, max_lines_count=200, max_boxes_count=100`; single-instance `var` or capped
`array<>` + `array.shift()`+`.delete()` for anything dynamic; never accumulate.

### 4.1 Corner table dashboard = the ONLY home for trade detail
- Single `var table`, populated only under `if barstate.islast`; values computed outside the guard.
- Branded header (one accent glyph, tinted `bgcolor`, `size.normal` max — no emoji spam).
- Rows: Status pill (● ARMED/MUTED/CLOSED) · Regime (4H UP/DOWN/NEUTRAL) · Active (BUY/—) ·
  Trigger (breakout/pullback) · Entry · Stop · Target · R:R · Trades n/N · Validation
  (RESEARCH/CANDIDATE — the binding truth).
- `position` driven by `input.enum` so it never stacks with other panels.

### 4.2 Markers: tiny glyphs only — NO on-price callouts/boxes
- `plotshape(..., size.tiny/small)` triangle glyphs, **no multiline text**. (Replaces defender
  `size.large text="BUY\n1H"`.)
- **Delete entirely** (the "trash"): the on-price `BUY MNQ / Entry/Stop/Target` callout box, the
  over-candle pinstripe box, and the three on-price entry/stop/target level labels. Those numbers
  live in the dashboard now — removal is pure decluttering.
- Optional: ONE single-instance managed label per active setup (`var label`, delete-recreate) if
  you still want an on-price tag — ATR-offset + `yloc` so stop/target never collide. Default OFF.

### 4.3 Premium trend cloud + VWAP
- Trend cloud: `fill()` between fast/slow EMAs, color via
  `color.from_gradient(spread/ATR, -2, 2, dnColor, upColor)` so weak trend reads faint, strong
  saturates. Optional 3-layer glow plot on the fast EMA (off by default).
- VWAP: **break the line at the session anchor** (plot `na` on the reset bar) so there is **no
  vertical "jump"** (the exact artifact you saw). RTH-anchored.

### 4.4 Settings UX
- Migrate string-option dropdowns → `input.enum()` (dashboard position, signal status, sweep
  metric). Keep `group`/`inline`/`tooltip` discipline for a clean panel.

### 4.5 Robustness sweep (carry over, adapt)
- Port the read-only sweep (axis-ordered, frozen-param highlight ◆, in-sample max ⚠ DO-NOT-TRADE,
  RELATIVE-not-Tester label, dev-window gated). Sweep the **execution EMA (pullback length)** as
  the stability axis. Default OFF.

---

## 5. Honesty / validation posture (unchanged guarantees)
- `Signal status` defaults to **research/muted**; real `alert()` delivery gated by it (the one
  load-bearing guard — a muted signal never pings the phone, regardless of how armed it looks).
- Dashboard `Status` row may read ARMED (visual posture) but `Validation` row stays
  RESEARCH/CANDIDATE — the truth.
- Sweep numbers are RELATIVE (manual-seeded EMAs, pessimistic same-bar stop-first), never the
  Strategy Tester; dev-window only.

---

## 6. Anti-repaint
Keep the tuple `request.security(tickerid, "240", [close[1], ema[1], ...], lookahead=lookahead_off)`
idiom. Add an optional debug `plotchar` asserting `off == on` form parity on history. Operator
verifies via Bar Replay across 4h boundaries.

---

## 7. What gets deleted / changed
- DELETE (declutter): on-price callout box, over-candle pinstripe, three on-price level labels.
- CHANGE: markers huge→tiny glyphs; dashPos string-switch→`input.enum`; VWAP na-break; EMA cloud
  gradient.
- ADD: robustness sweep (ported), gradient cloud, enum settings, drawing-count caps.
- KEEP: 1h/4h signal logic, MFF/RTH/long-bias/honesty/dev-window, managed single-instance drawings.

---

## 8. Test & verification plan
- Python invariant tests (extend `tests/test_pine_manual_alert_visuals.py`): assert hourly script
  is v6, has the corner-table-only trade detail (no on-price callout strings), tiny markers, enum
  settings, alerts gated by status, sweep honesty, anti-repaint idiom.
- **Operator eyeball (required — no local Pine compile):** paste into TradingView on a **1h** MNQ
  chart; confirm (a) clean chart, no buried candles, no overlapping labels; (b) dashboard renders;
  (c) VWAP has no jump; (d) Bar Replay shows no repaint; (e) markers sparse-but-clean.

## 9. Optional separate track — actually validate hourly (NOT part of this UX build)
If you want a real hourly edge: pre-register an hourly family in the ledger → backtest dev-window
only → Tier-0 cost-honest gate → split-half stability (the opening-drive killer) → only on BOTH
passing, flip status to Candidate. Base-rate expectation: KILL. This is a Python/validation task,
independent of the Pine UX work above.

## 10. Open decisions (need your call)
- **D1:** Keep `mnq_rth_long_bias.pine` as labeled legacy, or delete it?
- **D2:** New file `pine/mnq_hourly.pine`, or premiumize `mnq_1h_4h_defender.pine` in place (rename
  title to "Hourly v5")?
- **D3:** Run the optional validation track (Section 9) now, or UX-only for now?
- **D4:** Color identity — keep the defender's amber, or move to the cyan PEARL brand?
