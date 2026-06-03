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
| 12 | 2026-06-03 | **opening_drive** (PRIMARY: continue sign of first-15min RTH move, hold to close) | dev-only 2025-10-26→2026-04-19 | pending | pending | 0 | pre-registered — pending |
| 13 | 2026-06-03 | opening_drive_5 (5-min drive window) | dev-only 2025-10-26→2026-04-19 | pending | pending | 0 | pre-registered — pending |
| 14 | 2026-06-03 | overnight_seasonality (SHORT @18:00 ET, hold overnight) | dev-only 2025-10-26→2026-04-19 | pending | pending | 0 | pre-registered — pending |
| 15 | 2026-06-03 | tod_rth_long (unconditional LONG @RTH open, hold to close) | dev-only 2025-10-26→2026-04-19 | pending | pending | 0 | pre-registered — pending |

Commands (held-out discipline = explicit `--end 2026-04-19`; `--max-hold` per the hold target):
```
backtest_config.py --strategy opening_drive         --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy opening_drive_5        --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy overnight_seasonality  --tf 5m --max-hold-minutes 900 --start 2025-10-26 --end 2026-04-19 --json
backtest_config.py --strategy tod_rth_long           --tf 5m --max-hold-minutes 385 --start 2025-10-26 --end 2026-04-19 --json
```
