# MNQ Validation Trial Ledger

Durable record of every backtest/parameter trial run by the validation framework,
so the Deflated Sharpe Ratio's multiple-testing correction (Tier 3) is honest and
the held-out set is touched exactly once. Plan: `~/.claude/plans/im-starting-to-think-curious-sketch.md`.

## Frozen data snapshot

- Source: Beelink `candles.db`, pulled to Mac 2026-06-03.
- Primary dataset: **MNQ 5m, 41,423 bars, 2025-10-26 → 2026-06-03 (~7 months)**.
- 5m series sha256: `15b2fa76649ccc57419ddb5f254f079a4555f95a5bc0f79e6190f6ab088eece5`
- candles.db file sha256: `77a258614c246c2d4701dd7c7fb2dfd8b0c9432db9f44c7a5e24c02c65386676`

## Held-out set (registered — touch ONCE, only at Tier 5)

- Reserve the most recent ~25%: **2026-04-20 → 2026-06-03** (do not run any tier
  on this range until the final held-out test). Development uses 2025-10-26 → 2026-04-19.
  *(Enforcement: the harness must refuse to load held-out dates outside the Tier-5 run.)*

## Engine state

- 2026-06-03 — Fixed critical exit-sim bug (commit `d88db45`): the engine was
  force-closing trades at the next ~5-min bar instead of holding to SL/TP/max-hold.
  **All prior Phase-E backtest numbers (incl. +0.38 pt/trade) are INVALID** — they
  measured 5-min noise, not the strategy. Added realistic round-trip commission
  (1.0 pt ≈ $2 on MNQ). Tier-0 stats gate committed `4cccafe`.

## Trials

| # | Date | Strategy | Window | Trades | Net exp (pt/trade) | Tier | Verdict |
|---|------|----------|--------|--------|--------------------|------|---------|
| 1–6 | pre-2026-06-03 | composite (Phase E E/F grid, broken engine) | — | — | void (broken engine) | — | seed-only for DSR multiple-testing count |
| 7 | 2026-06-03 | RICH (live composite) | 120d (dev) | 228 | **−7.29** | 0 | **KILL** (exp ≤ 0) |
| 8 | 2026-06-03 | pine (EMA9/21+VWAP, long-only, 1.5×/3.0× ATR) | 120d (dev) | 113 | +6.50, 95% CI [−9.5, +22.9] | 0 | PASS\* — INCONCLUSIVE (CI crosses 0); 14d +37.8→120d +6.5 = regime-dependent; 1280-pt max DD. Advance to WFA. |
| 9 | 2026-06-03 | orb (opening-range breakout, 2-sided) | 120d (dev) | 192 | **−0.47** | 0 | **KILL** (exp ≤ 0) |
| 10 | 2026-06-03 | vwap_reversion (fade ±2σ → VWAP, 2-sided) | 120d trailing† | 228 | **−5.26** | 0 | **KILL** (exp ≤ 0) |
| 11 | 2026-06-03 | pine | dev-only 2025-10-26→2026-04-19 | 152 | **−4.46** | 0 | **KILL** — the +6.50 was 100% held-out-uptrend contamination |

## CONCLUSION (2026-06-03)

**All four intraday-MNQ signal families FAIL Tier-0 cost-viability on clean data.**
On the corrected simulator (real holds + ~$2 RT commission), with 150–230 trades each:

- RICH (live composite): −7.29 pt/trade
- pine (EMA9/21+VWAP, long-only — the rules traded manually): −4.46 (dev-clean)
- ORB: −0.47
- VWAP-reversion: −5.26

No strategy survives the cheapest gate, so none advances to walk-forward / Monte-Carlo /
trailing-DD survival (kill-early). The contamination from the held-out uptrend only
*helped* the long-biased strategies, so these KILLs are conservative — RICH/ORB/vwr were
KILL even *with* the favorable recent data and would be worse dev-only.

**Evidence-based recommendation:** do NOT fund a manual intraday-MNQ account on these
signals. The honest "no" — reached for the cost of days, not an MFF eval fee + a blown
funded account. If pursuing futures further, the next hypotheses should be genuinely
different from EMA/VWAP/ORB/VWAP-reversion (e.g., order-flow at sub-minute resolution,
overnight/time-of-day seasonality) — and tested on this now-trustworthy engine with deeper
multi-year data before any capital.

The held-out slice (2026-04-20→2026-06-03) remains **untouched** for a future Tier-5 check
should a genuinely new candidate ever clear Tiers 0–4.

† **Contamination caveat:** trials 7–10 used a trailing `--days 120` window (~Feb→Jun) which **overlaps the registered held-out slice (2026-04-20+)**. For RICH/ORB/vwap-reversion the KILL is robust (they lose with or without the recent uptrend). For **pine** it matters — its +6.50 was inflated by the held-out uptrend — so pine is re-run dev-only (trial 11). Date-range support (`--start/--end`) added to the engine for this.

\* Tier-0 is a coarse cost filter; pine survives only as a *candidate to disprove*. Per the committed gate (KILL if exp≤0, or 0<exp<1 with CI crossing 0), +6.50 passes — but the wide CI means the edge is NOT established and must be confirmed in walk-forward + the W13 regime guard + trailing-DD survival.

## Findings

- **Config flags do NOT cleanly isolate strategies.** The base EMA-cross
  ("pearlbot_pinescript") fires regardless of the `allow_*` trigger flags, and
  trigger attribution labels everything `pearlbot_pinescript`. So config-only
  overlays for ORB / VWAP-reversion / pure-SIMPLE run the *same* base strategy
  with extras added — they are NOT valid isolated baselines. The clean 4-way
  comparison requires the pluggable `strategy_fn` refactor (separate ORB-only,
  VWAP-reversion-only, and faithful-Pine signal functions). The generated configs
  in `config/candidates/validation/` are scaffolding pending that refactor.

## Next

- Make `strategy_fn` pluggable in the engine; build faithful Pine-simple +
  ORB-only + VWAP-reversion-only signal sources; re-run the 4-way Tier 0.
- For any survivor: Tier 1 (robust levers) → WFA → MC → trailing-DD survival → held-out.
- ~~Install `scipy` before Tier 3 (DSR).~~ Correction 2026-06-03: `scipy` IS importable
  in `.venv` (`from scipy.stats import norm` works) — the earlier "not installed" note was
  stale. Irrelevant to Tier 0; only matters at a future Tier-3 DSR.

---

## Path B — genuinely-different time-based hypotheses (pre-registered 2026-06-03)

After all four intraday families were killed at Tier-0, the operator chose to test
**genuinely different** hypotheses (NOT more EMA/VWAP/ORB) on the existing free 5m dev
data before any data spend. Two families: **opening-drive** (does the sign of the first
few minutes of RTH continue?) and **time-of-day / overnight seasonality** (is there
directional drift conditioned on the ET clock?).

**Pre-registration (immutable):** the 4 trials below are a fixed set chosen BEFORE the
official full-slice runs. Directions are fixed pre-hoc from priors, never grid-searched
(opening-drive = continuation; RTH = long from the 922-trade long-bias; overnight = short
from the local prior that the overnight long-biased bot lost −$4,477). Exits hold to a
session boundary via the engine's max-hold timeout (far sentinel stops — no ATR-stop
lever). **DSR `n_trials` is now 15** (6 dead Phase-E seed + trials 7–11 + these 4).
**H1 (trial 12) is the single primary read; H2–H4 are secondaries — best-of-4 expectancy
is upward-biased (family-wise ≈19% chance of ≥1 false positive at nominal 95%).** Honest
ceiling (operator-acknowledged): a Tier-0 PASS on this ~5.5-month slice is NOT an edge and
NOT a fund signal — it only justifies procuring deep multi-year data to confirm.

| # | Date | Strategy | Window | Trades | Net exp (pt/trade) | Tier | Verdict |
|---|------|----------|--------|--------|--------------------|------|---------|
| 12 | 2026-06-03 | **opening_drive** (PRIMARY: continue sign of first-15min RTH move, hold to close) | dev-only 2025-10-26→2026-04-19 | 122 | **+12.72** | 0 | **PASS\*** — INCONCLUSIVE: CI95 [−25.66,+49.87] crosses 0; split-half = regime artifact (see below) |
| 13 | 2026-06-03 | opening_drive_5 (5-min drive window) | dev-only 2025-10-26→2026-04-19 | 122 | **+19.18** | 0 | **PASS\*** — INCONCLUSIVE: CI95 [−20.24,+59.04] crosses 0; split-half = regime artifact |
| 14 | 2026-06-03 | overnight_seasonality (SHORT @18:00 ET, hold overnight) | dev-only 2025-10-26→2026-04-19 | 123 | **−13.57** | 0 | **KILL** (exp ≤ 0) |
| 15 | 2026-06-03 | tod_rth_long (unconditional LONG @RTH open, hold to close) | dev-only 2025-10-26→2026-04-19 | 122 | **−4.81** | 0 | **KILL** (exp ≤ 0) |

Commands (held-out discipline = explicit `--end 2026-04-19`; `--max-hold` per the hold target):
```
backtest_config.py --strategy opening_drive         --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy opening_drive_5        --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy overnight_seasonality  --tf 5m --max-hold-minutes 900 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy tod_rth_long           --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
```

### Tier-1 regime-stability check on the two Tier-0 survivors (split-half, dev-only)

opening_drive / opening_drive_5 cleared Tier-0 (cost viability), so the kill-early ladder advances
them to the first Tier-1 robust lever: per-period / regime stability (the framework's committed W13
guard — "any single regime > 40% of profit" is a KILL). A split-half of the dev slice shows the
positive full-slice expectancy is **100% regime-carried, and — the decisive tell — the two variants
are positive in OPPOSITE halves**: correlated signals (5-min vs 15-min opening drive) that disagree
on *which* half pays is the signature of noise, not a persistent effect (the split-half magnitudes
are themselves n≈60 wide-CI noise; the sign-disagreement is the real evidence):

| Strategy | H1 2025-10-26→2026-01-22 | H2 2026-01-23→2026-04-19 |
|----------|--------------------------|--------------------------|
| opening_drive (15-min) | n=62, **−10.82** pt | n=59, **+39.58** pt |
| opening_drive_5 (5-min) | n=62, **+42.49** pt | n=59, **−2.50** pt |

Every sub-period CI also crosses zero. The 15-min "edge" lives entirely in H2; the 5-min "edge"
entirely in H1. They contradict each other on *which* half is profitable → not a credible lead.

## CONCLUSION — Path B (2026-06-03)

**No Path-B hypothesis demonstrates a stable, tradeable edge on free 5m dev data.**

- **overnight_seasonality (short): KILL** (−13.57 pt/trade). Shorting the overnight session lost
  money → the overnight session actually had a mild *positive* drift in-sample. This *contradicts*
  the local prior (the bot's overnight longs lost −$4,477) — that loss was execution/adverse-
  selection on an automated scalper, not a directional drift. Per anti-fishing discipline, overnight
  *long* was NOT separately tested; by symmetry it would be ≈ small-positive (gross overnight drift
  minus double costs) — itself a wide-CI, inconclusive-noise result that would not establish an edge,
  so it reinforces rather than changes this verdict. A lone direction-flip on noisy data is no green light.
- **tod_rth_long: KILL** (−4.81 pt/trade). Being unconditionally long the RTH session lost money
  after costs — so **RTH sessions did not trend up** in-sample (the index's net gains were *overnight*,
  per the overnight-short loss above). Useful apples-to-apples control: always-long-RTH lost while
  sign-conditioned-RTH (opening_drive) gained — both are RTH-duration holds — so the opening-sign
  added in-sample value (a real signal, but one that does not survive Tier 1; see below).
- **opening_drive / opening_drive_5: PASS Tier-0, FAIL Tier-1.** They clear the coarse Tier-0 cost
  filter on full-slice expectancy (+12.72 / +19.18) — the first hypotheses in the whole program to do
  so — then **die at the first Tier-1 lever (regime stability)**: CIs span zero and the split-half
  shows the profit is one-regime-only with the two variants positive in *opposite* halves. This is the
  kill-early ladder working exactly as designed (the pine-trial-8 pattern), **not** a moved goalpost.

**Decision-tree branch:** opening_drive cleared Tier-0 but **failed Tier-1 regime stability on free
data**, so it does NOT graduate to a credible "procure deep data to confirm" candidate — the free
data already shows the lead is a regime artifact, making confirmation low-EV. Honest recommendation:
**do NOT fund anything; do NOT spend on tick/L2 + multi-year data on this basis.** opening-drive is
the only non-dead lead, but it is fragile. Combined with the four dead intraday families (trials
7–11) and the two Path-B KILLs, the cost-clean evidence increasingly says signal-based intraday MNQ
has no edge that survives costs on this data → this **leans toward path A (redirect off intraday
MNQ)**, unless the operator chooses to spend on deep data to test opening-drive at fidelity *despite*
the weak free-data signal (operator's $ call).

The held-out slice (2026-04-20→2026-06-03) remains **untouched** (all runs verified
`window_to ≤ 2026-04-20`). DSR `n_trials` is now **15**. Per-strategy JSON saved at
`docs/audits/2026-06-03-pathb-*.json`.

---

## Path C — overnight-gap conditioning (pre-registered 2026-06-12)

A genuinely different signal family: the conditioning variable is the **overnight gap**
(today's RTH open vs yesterday's RTH close) — never used by trials 7–15 (those were
indicator crosses, range breakouts, band fades, and unconditional clock bets). Plan:
`docs/plans/2026-06-12-001-feat-gap-family-validation-pine-honesty-plan.md`.

**Pre-registration (immutable; this entry is committed BEFORE any trial runs).**

### Frozen definitions

- `prior_rth_close` = close of the last 5m bar with ET time in [09:30, 16:00) on the most
  recent prior trading date.
- `gap` = open of the FIRST RTH 5m bar today − `prior_rth_close` (points; + = up-gap).
- `ATR_d(14)` = Wilder ATR over daily aggregates (ET calendar date, full ETH range) of all
  bars **strictly before today**. Valid only once **14 complete prior daily aggregates**
  exist; the archive's first (possibly partial) calendar day is excluded from aggregates.
- Decision/entry bar = the first RTH bar of the session; entries at its CLOSE (engine
  convention, same as Path B). Fire at most once per session.
- Cost floor: no fade trade unless the remaining distance to target at the entry-bar close
  is ≥ **5.0 pt** (≥5× the ~1.0 pt RT cost). Skip the session if the gap has already
  filled by the entry-bar close (fades only).
- **Roll-splice exclusion:** sessions **2025-12-22** and **2026-03-23** are excluded from
  all three trials. The dev window is IBKR continuous (`ibkr_historical`), spliced
  unadjusted at expiry; on the first session after the Dec 19, 2025 / Mar 20, 2026
  expirations, `gap` embeds the calendar spread (a phantom gap). Census found no
  basis-jump outlier at these dates (spread hides inside the 120-pt median gap), so this
  is conservative hygiene, not outlier surgery. The three genuine |gap| outliers found
  (2025-11-20 +486.5, 2026-03-03 −487.8, 2026-04-08 +830.0) are real market gaps and are
  KEPT.
- Exits, frozen: fades target `prior_rth_close` (the fill), stop = entry ∓ remaining
  distance (1:1 R on the remaining gap), max-hold to RTH close (`--max-hold-minutes 385`).
  `gap_continue_large` holds to RTH close via the `_HOLD_SENTINEL` convention (pure
  conditional-drift read, no stop lever — same mechanics as Path B).
- ATR-validity gate applies to trials 16 and 18 (their conditions use ATR_d). **Trial 17's
  condition uses no ATR and carries NO ATR-warmup gate** (decided here, pre-hoc).
- Two-sided by design; the two-sided read is THE read. Per-side breakdowns are diagnostics
  and never a promotion basis.

### Trials (DSR `n_trials` 15 → 18)

| # | Strategy | Condition (at entry-bar close) | Direction | Exit |
|---|----------|-------------------------------|-----------|------|
| 16 (PRIMARY) | `gap_fade_small` | 5.0 pt ≤ \|gap\| ≤ 0.30 × ATR_d | against gap | fill target / 1:1 stop / 385m |
| 17 (secondary) | `gap_fade_all` | \|gap\| ≥ 5.0 pt (no ceiling, no ATR gate) | against gap | fill target / 1:1 stop / 385m |
| 18 (secondary) | `gap_continue_large` | \|gap\| ≥ 0.70 × ATR_d | with gap | sentinel hold to RTH close |

**External priors (fixed pre-hoc, never fitted):** NQ gap-fill 2015–2025 (n=2,791,
TradingStats.net): <0.3×ATR fills 77.8% → trial 16 fade prior **moderate**; all-gaps fills
60.3% → trial 17 prior **WEAK** (registered honestly as the dilution control; 17 ⊇ 16);
>1.2×ATR fills only 8.2% → large gaps continue, trial 18 prior directional-only at
0.70×ATR. Overnight-drift literature (Cooper/Cliff/Gulen; Boyarchenko et al. NY Fed)
implies RTH-session weakness but its "opening reversal" is only weakly coupled to the gap;
Plastun et al. 2020 finds gap-day *continuation* in stocks/daily. Net: smallest honest
family that respects the size-regime split. **Family-wise: ≈14% chance of ≥1 false
positive at nominal 95% across 3 trials.**

### Conditioning census (outcome-blind, run BEFORE registration was finalized)

`scripts/ops/pathc_conditioning_census.py` — reads gap sizes, ATR_d, and entry-bar-close
position only; simulates no entries/exits/P&L. Dev window: 121 RTH sessions; median |gap|
120.8 pt; median ATR_d 434.1 pt. **Expected n (after roll exclusion): trial 16 ≈ 50
(max 58), trial 17 ≈ 107, trial 18 ≈ 15.** Disclosed consequences, pre-hoc: trial 16 can
NEVER satisfy the n ≥ 100 powered-read bar on this window; trial 18 is expected
INCONCLUSIVE unless the effect is enormous.

### Pre-registered verdict → action mapping

- **Promotion to the Pine manual toolkit ("candidate — paper-trade the gate") requires ALL
  of:** (1) trial 16 Tier-0 PASS (any n) — the strongest-prior read concurs directionally;
  (2) trial 17 Tier-0 PASS with `undersized=false` (n ≥ 100) — the only powered read;
  (3) Tier-1 split-half on trial 17 (H1 2025-10-26→2026-01-22 / H2 2026-01-23→2026-04-19):
  positive expectancy in BOTH halves AND neither half > 70% of total profit (two-way
  operationalization of the W13 concentration guard; noted deviation from the literal 40%
  wording, which targets finer partitions). On promotion, the shipped Pine defaults to the
  validated TWO-SIDED configuration.
- **Any Tier-0 PASS that fails the above** (incl. PASS+undersized) → recorded
  **INCONCLUSIVE**, record-only, NO Pine signal swap. Sanctioned next steps are an
  operator decision recorded here (paper-trade off chart visuals, or the deep-data $ call).
- **KILL** (per committed `tier0_verdict` gate) → recorded; Pine entry alerts stay muted.
- Operator override of any routing must be recorded in this ledger to take effect.
- Honest ceiling (Path-B precedent, restated): a Tier-0 PASS on this ~5.5-month free slice
  is NOT an edge and NOT a fund signal.

### Integrity preflight (pinned; run before trial 16)

Reproduce trial 11 with every flag explicit — a mismatch is data/engine drift and a hard
STOP; varying flags until n=152 reappears is forbidden (flag-fitting):

```
backtest_config.py --strategy pine --tf 5m --start 2025-10-26 --end 2026-04-19 \
  --warmup-bars 120 --max-hold-minutes 180 --slippage-points 0.25 --commission-points 1.0 --json
```

Expected: n=152, net expectancy −4.46 pt/trade. (Reconstructed engine defaults; trial 11's
flags were never recorded — that reconstruction is itself part of what this pin freezes.)

### Commands (dev-window only; engine-default costs, identical to trials 7–15)

```
backtest_config.py --strategy gap_fade_small     --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy gap_fade_all       --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy gap_continue_large --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
# Tier-1 split-half (only on a trial-17 Tier-0 PASS):
#   same commands with --start 2025-10-26 --end 2026-01-22  and  --start 2026-01-23 --end 2026-04-19
```

**Development prohibition:** no gap-family strategy may be run against `data/candles.db`
until the strategy functions and their synthetic-frame tests are committed and the official
runs (above) begin. Development uses synthetic frames exclusively — this closes the
informal-peek channel that commit ordering alone does not.

### Path C results

*(to be filled by the official runs — verdict rows append below; this section header is
part of the pre-registration so results cannot be reframed)*
