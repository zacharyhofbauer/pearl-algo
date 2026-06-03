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
| (Phase E grid: 6 prior trials on the BROKEN engine — counted for DSR but results void) |
| 1–6 | pre-2026-06-03 | composite (Phase E E/F grid) | — | — | void (broken engine) | — | seed-only |
| 7 | 2026-06-03 | RICH (live config) | 120d (dev) | 228 | **−7.29** | 0 | **KILL** (exp ≤ 0) |

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
- Install `scipy` before Tier 3 (DSR).
