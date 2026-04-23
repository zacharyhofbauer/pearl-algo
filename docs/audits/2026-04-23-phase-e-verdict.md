# Phase E Verdict — 2026-04-23

**Session goal:** ship the review work + find a config that clears the re-arm gate and get pearl-algo back to live trading.
**Outcome:** infrastructure shipped successfully (19 PRs merged, deploy green, replay harness operational). **No candidate config clears the re-arm gate.**

Do NOT re-arm based on this session's grid-search. The honest path to $1,500/day is longer than a config tune.

---

## Re-arm gate (from the IBKR-era baseline audit)

A config passes the gate only if the 30-day replay with 0.25 pt slippage produces:

- Win rate ≥ 45 %
- Expectancy ≥ 2 pt / trade **post-slippage**
- Max drawdown ≤ 200 pt
- ≥ 60 replay trades (spans multiple regime transitions)

---

## Grid-search results

30-day replay, 5m timeframe, 0.25 pt slippage per side, 120-bar warmup, 1 concurrent position.

| Candidate | n | WR | Total (pt) | Exp / t | DD | Gate |
|---|---|---|---|---|---|---|
| A — current live | 347 | 51.0 % | +126.7 | **+0.37** | 158 | fail (exp<2) |
| B — W13 full revert | _parse error_ | — | — | — | — | (pre-fidelity ran −403 pt; still fail) |
| C — current + allow_orb_entries | 348 | 51.1 % | +133.5 | **+0.38** | 158 | fail (exp<2) |
| D — current + orb + vwap_2sd | 363 | 50.7 % | +138.9 | +0.38 | 204 | fail (exp<2, DD>200) |
| E — current thresholds, SL/TP 2.0/3.5 | 513 | 48.5 % | −39.1 | −0.08 | 267 | fail (exp, DD) |
| F — W13 thresholds + current triggers | 820 | 47.9 % | −520.7 | −0.64 | 755 | fail (exp, DD) |

Raw JSON: `docs/audits/2026-04-23-grid-search-results.json`.

### What the numbers say

- **Best expectancy across all 6 is +0.38 pt / trade** (candidate C). At 1 MNQ contract × $2/pt = **+$0.76 / trade**. At 348 trades / 30 days = **+$8.82 / day average**. Not $1,500.
- The difference between the top-3 (A, C, D) is statistical noise — all within 0.01 pt / trade of each other. Adding ORB and VWAP-2SD triggers didn't hurt, didn't help materially.
- Narrowing SL/TP (E) and restoring W13 thresholds (F) made things worse, not better. Tighter stops on current volatility get taken out; 0.40 confidence floor admits too much noise.
- The IBKR-era audit's caveat held: **W13 was regime-dependent, not config-dependent.** The same signal generator produces a marginal-positive-edge across 5 of 6 variants and a losing edge on the 6th — no tuning in this grid unlocks the +$1,500/day pattern.

---

## Honest interpretation

1. The system is **not bleeding** on any of the top-3 configs — small positive expectancy (~breakeven after commissions). Re-arming wouldn't blow up the account at 1 contract. But it also wouldn't build $1,500/day.
2. **Config tuning has hit its ceiling.** 6 candidates spanning all the obvious dimensions all cluster around the same marginal edge. The next unlock has to come from something the grid didn't touch.
3. **W13 was a gift from the market**, not a configuration you can copy-paste back. 91 of 92 trades were long in a strong uptrend week. The current market doesn't repeat that pattern.

---

## What has NOT been tried

These are the variables the current replay grid did not cover. Each is a candidate next session:

| Axis | Rationale |
|---|---|
| **Hour-of-day filter** | Looking at the W13 trades by UTC hour, the winning hours clustered at 13-14 UTC (09-10 ET, NY open) and 16 UTC (12 ET, lunch break). A filter that only trades those windows might concentrate edge. |
| **Regime-gated entries** | `composite_regime` logs a score + confidence per bar. Only trading when `trending_up` with conf > 0.7 might cut the trades that are random chop. |
| **Different primary timeframe** | 5m with 1m+15m MTF has been the setup forever. A 15m primary with 1h confirm is a totally different signal universe — may be the right timeframe for MNQ given its intraday volatility has grown. |
| **Different instrument** | MNQ volatility post-2025 may not suit this strategy. ES, NQ, CL, GC are cheap to add via the same Tradovate adapter. An instrument where the 51 % WR translates to $2-3 / trade expectancy solves the problem without touching the strategy. |
| **Ensemble sizing** | Replay size is fixed at 1. If expectancy is +$0.76 / trade but variance is controlled, leverage (2-3 contracts during high-confidence signals) could compound the edge — risky but concrete. |
| **1m timeframe replay** | Candle archive has only 760 bars of 1m currently. A proper 60-day 1m backfill + replay on 1m primary = a whole different grid to search. |

None of these are in scope for tonight — they need a fresh session each. But they're the honest candidates for where the next $1,500/day unlock hides.

---

## Service state at end of session (read-only verified)

- Deploy: green. Current main (`086a353` + #55) synced to Beelink. Trading service still running on pre-deploy SHA until explicit restart.
- Arm: **disarmed** (`execution.armed: false`). Unchanged from session start.
- Candle archive: 34,650 rows 5m (~180 days), 760 rows 1m, covers the replay window this session needed. Kept.
- PnL surface: no live trades since disarm; today's virtual ledger −$13 (see 2026-04-23 entries in `trades.db`).
- All Beelink / Mac `/tmp` scratch files cleaned up.

## Decision point (operator, not me)

**Option 1 — accept the truth, go strategy-level next session.** No arm. Pick one of the "NOT been tried" axes above for the next session. Honest about what this grid proved vs didn't.

**Option 2 — arm candidate C (ORB re-enabled) at 1 contract with current demo guardrails.** Expectancy is +$0.76 / trade, not break-even catastrophic. $120 max daily loss + 2 consecutive loss stop + RTH-only keeps downside small. Won't build $1,500/day but produces real fills you can learn from. Accept this is a "keep the system warm" arm, not a profit-targeting arm.

**Option 3 — don't arm, but schedule a follow-up session for the untried axes.** Hour-of-day filter + regime gating are the two most likely to push expectancy from +0.38 → +2 pt / trade.

If you pick option 2, here is the exact operator checklist (I'm stopping at your decision):

```bash
# 1. On Mac, verify tree clean + on main
cd ~/projects/pearl-algo
git status -s                # must be clean
git checkout main && git pull

# 2. Apply candidate C overlay
# Edit config/live/tradovate_paper.yaml:
#   strategies.composite_intraday.allow_orb_entries: true   # (currently false)
#   execution.armed: true                                   # (currently false)

# 3. Commit + push + merge (via PR)
git checkout -b chore/rearm-candidate-c
git add config/live/tradovate_paper.yaml
git commit -m "chore(rearm): apply candidate C (ORB re-enabled) + arm"
git push -u origin chore/rearm-candidate-c
gh pr create --fill
gh pr merge --squash --delete-branch
git checkout main && git pull

# 4. Deploy + restart — the smoke validates YAML + imports before restart
./scripts/ops/deploy-from-mac.sh --tv-paper

# 5. Verify
./pearl.sh quick
ssh pearlalgo 'curl -s http://localhost:8001/api/state | python3 -m json.tool | grep -A2 execution'
# Should show execution.armed = true

# 6. Watch the first 30 minutes live. Have the kill-switch ready:
# curl -X POST http://localhost:8001/api/kill-switch  -H "X-PEARL-OPERATOR: $PEARL_OPERATOR_PASSPHRASE"
```

I'm not executing step 2 because arming live execution is the operator's call, not mine.
