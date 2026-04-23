# IBKR-era Baseline Reconstruction — 2026-04-23

**Author:** Claude (review-driven reconstruction)
**Data source:** `trades.db` on the Beelink at `/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ/trades.db` — 717 trades spanning `2026-03-30` to `2026-04-23`
**Plan reference:** Tier 1 research item in `~/.claude/plans/this-session-work-cosmic-horizon.md`; paired with Issue 24-A (PR #43 `pearl.sh backtest-config`)

---

## TL;DR

The inline comments in `config/live/tradovate_paper.yaml` attributed to an April-10 "audit" assert the IBKR-era winning system ran with `min_confidence=0.55`, `SL=54pt / TP=80pt`, and only the "legacy 4-trigger pearlbot core" — i.e., with ORB, VWAP-2SD, and SMC *disabled*. **Those assertions are not supported by the trades in `trades.db`.** The only profitable week in the 25-day window (W13, `2026-03-30` to `2026-04-01`, **+1,203.7 pt on 92 trades, 47.8 % WR**) ran the *pre-audit* config: `min_confidence=0.40`, `SL=1.5 × ATR`, `TP=2.5 × ATR`, all three "new" triggers enabled, full overnight session. The April-10 retune that claimed to restore the IBKR-era winners is the commit that broke expectancy. Every week since has been negative, with SL-hit rate rising from 49 % (W13) to 67 % (W15-16).

---

## Weekly PnL history

| Week | Dates | n | PnL (pt) | WR | Status |
|---|---|---|---|---|---|
| W13 | 2026-03-30 → 2026-04-01 | 92 | **+1,203.7** | 47.8 % | 🟢 profitable |
| W14 | 2026-04-09 → 2026-04-10 | 153 | −39.4 | 41.8 % | 🔴 flat-to-down |
| W15 | 2026-04-13 → 2026-04-19 | 320 | −1,586.1 | 33.4 % | 🔴 heavy loss |
| W16 | 2026-04-20 → 2026-04-23 | 152 | −1,604.5 | 34.9 % | 🔴 heavy loss |
| **Overall** | 2026-03-30 → 2026-04-23 | **717** | **−2,026.3** | **37.4 %** | — |

Note the W13 → W14 gap: no trades logged `2026-04-02` through `2026-04-08`. The April-10 retune commit (`be3bb97`) landed during that gap; W14 is the first week of trading after the audit took effect.

---

## Week 13 (winner) vs Week 15-16 (loser) — head-to-head

| Metric | W13 (winner) | W15-16 (loser) | Delta |
|---|---|---|---|
| Trades | 92 | 472 | +5.1 × |
| Total PnL (pt) | +1,203.7 | −3,190.6 | −4,394.3 |
| Expectancy / trade | **+13.08 pt** | **−6.76 pt** | −19.84 pt |
| Win rate | 47.8 % | 34.2 % | −13.6 pp |
| Avg win | +71.2 pt | +61.5 pt | −9.7 pt |
| Avg loss | −40.2 pt | −42.9 pt | −2.7 pt |
| Avg win / avg loss (R) | **1.77** | 1.43 | −0.34 |
| Avg hold (min) | _not logged_ | 28 | — |
| TP-hit rate | **49 %** (44 / 89) | 32 % (151 / 472) | −17 pp |
| SL-hit rate | 51 % | 67 % | +16 pp |

**The headline failure:** R:R on winning trades didn't collapse by much (1.77 → 1.43), but **SL-hit frequency rose from 51 % to 67 %**. Hitting the stop two-thirds of the time at ~1.4 R:R is a solid losing formula.

### Per-trigger PnL

**W13 (winner):**
```
pearlbot_pinescript    n= 90  pnl=  +983.4  avg=+10.93  wr=46.7%
smc_silver_bullet      n=  2  pnl=  +220.4  avg=+110.18 wr=100.0%
```

**W15-16 (loser):**
```
pearlbot_pinescript    n=452  pnl= -3,415.6  avg= -7.56  wr=33.0%
(unknown)              n= 20  pnl=   +225.0  avg=+11.25  wr=55.0%
```

`pearlbot_pinescript` — the default signal type from the main generator — went from **+10.93 pt / trade** to **−7.56 pt / trade** between these eras. Nothing else moved materially. This is the single signal-type to fix.

### Exit reason histogram

**W13:** 45 SL / 44 TP / 3 auto-flat.
**W15-16:** 313 SL / 151 TP / 7 auto-flat / 1 kill-switch.

Widening SL / TP by the April-10 audit (1.5 → 2.5 ATR SL, 2.5 → 4.0 ATR TP) did not improve the ratio — it kept trades in the market longer, where adverse moves could find the (further) stop. The hypothesis "wider stops let winners mature" failed empirically.

### Direction asymmetry in W13

```
long   n=91  pnl=+1,248.9  wr=48.4%
short  n= 1  pnl=   −45.2  wr= 0.0%
```

**Warning:** 91 of the 92 W13 trades were long. That week was almost certainly a strong-uptrend regime. Reverting today to the W13 config does **not** mean reproducing W13 PnL — the market regime does not cooperate on demand. Any revert must be validated against *current* candles via backtest-config.

### Regime breakdown (W15-16 only — W13 pre-dated regime logging)

```
trending_up     n=290  pnl=−1,977.7  wr=35.2%
trending_down   n=138  pnl=−1,244.3  wr=29.7%
ranging         n= 24  pnl=  −193.6  wr=25.0%
NULL            n= 20  pnl=  +225.0  wr=55.0%
```

Even in supposedly-favorable `trending_up`, the current config lost. The problem is not a regime filter — it's the entry / exit parameters producing signals that don't resolve favorably.

---

## Timeline — what changed between W13 and W15

Commits on `config/live/tradovate_paper.yaml`:

```
316a86e  2026-04-02  chore(runtime): re-arm tradovate paper execution      ← end of W13
be3bb97  2026-04-10  checkpoint(2026-04-10): retuned strategy              ← the audit
6a65fea  2026-04-10  feat(cb+webapp): session profit lock + commission clamp
5efabbf  2026-04-21  feat(tradovate): enable session profit lock + size up on high confidence
0865a0e  2026-04-22  fix(execution): never auto-rearm after protection disarm
928c25b  2026-04-22  fix(config): remove one-way direction gating from paper profile
aeef4a7  2026-04-22  fix(strategy): remove short-confidence handicap in paper profile
22503a5  2026-04-23  feat(config): loosen demo guardrails for strategy iteration (#17)
```

### What the April-10 `be3bb97` audit changed in `strategies.composite_intraday`

```diff
-    min_confidence: 0.4
-    min_confidence_long: 0.4
-    min_confidence_short: 0.4
-    stop_loss_atr_mult: 1.5
-    take_profit_atr_mult: 2.5
+    min_confidence: 0.55
+    min_confidence_long: 0.55
+    min_confidence_short: 0.55
+    stop_loss_atr_mult: 2.5
+    take_profit_atr_mult: 4.0
...
-    allow_orb_entries: true
-    allow_vwap_2sd_entries: true
-    allow_smc_entries: true
+    allow_orb_entries: false
+    allow_vwap_2sd_entries: false
+    allow_smc_entries: false
```

The commit comments cite "IBKR-era avg SL 54pt / TP 80pt" and "IBKR-era 0.55 confidence floor" as justification. Neither number appears in this repo's `trades.db`. They look like they came from a prior system's post-mortem. Transplanting those values into the current generator didn't restore prior performance — it broke the system that was working.

---

## The W13 config (to try first in `pearl.sh backtest-config`)

The exact `strategies.composite_intraday` block that produced the W13 winners (from commit `316a86e`):

```yaml
strategies:
  composite_intraday:
    ema_fast: 9
    ema_slow: 21
    min_confidence: 0.4
    min_confidence_long: 0.4
    min_confidence_short: 0.4
    stop_loss_atr_mult: 1.5
    take_profit_atr_mult: 2.5
    volatile_sl_mult: 1.3
    volatile_tp_mult: 1.3
    ranging_sl_mult: 0.8
    ranging_tp_mult: 0.7
    allow_vwap_cross_entries: true
    allow_vwap_retest_entries: true
    allow_trend_momentum_entries: true
    trend_momentum_atr_mult: 0.5
    allow_trend_breakout_entries: true
    trend_breakout_lookback_bars: 5
    volume_ma_length: 20
    sr_length: 130
    sr_atr_mult: 0.5
    tbt_period: 10
    tbt_trend_type: wicks
    sd_threshold_pct: 10.0
    sd_resolution: 50
    vwap_std_dev: 1.0
    allow_orb_entries: true
    allow_vwap_2sd_entries: true
    allow_smc_entries: true
    adx_period: 14
    adx_trending_threshold: 25.0
    adx_ranging_threshold: 20.0
session:
  start_time: '18:00'
  end_time: '17:00'
  timezone: America/New_York
```

---

## Recommended re-prime flow

**Do NOT blindly revert to the W13 config on the live agent.** Instead:

1. **Merge PR #37 first** (pre-deploy smoke + rollback) so every subsequent change ships through the hardened path.
2. **Merge PR #43** (`pearl.sh backtest-config`).
3. **Backfill the candle archive** on the Beelink to cover at least `2026-03-01` through today (`scripts/ops/backfill_ibkr_historical.py`). Without this, backtest-config has no data to replay against.
4. **Create a candidate config file** `config/candidates/w13_revert.yaml` containing the W13 block above.
5. **Run backtest-config against both configs over the same 30-day window** and compare scorecards:
   ```bash
   ./pearl.sh backtest-config config/candidates/w13_revert.yaml --days 30 --json > audits/w13_revert_replay.json
   ./pearl.sh backtest-config config/live/tradovate_paper.yaml --days 30 --json > audits/current_replay.json
   ```
6. **Only re-arm if** the W13-revert scorecard shows expectancy > 0 and materially better than the current config AND the Phase-1 demo guardrails (`max_daily_loss=$120`, 1 contract, RTH-only, `max_consecutive_losses=2`) are kept in force.

Note: W13's 91/92 long bias means the revert may underperform in a trending-down or ranging regime. The backtest-config replay covers ≥30 days precisely to catch that. Don't trust a config that only shows up green in one regime — demand at least 60 trades across multiple regime transitions in the replay before re-arming.

---

## Follow-up items

- The 5 "IBKR-era" inline comments in `config/live/tradovate_paper.yaml` should be corrected or deleted — they're archaeologically misleading. A follow-up PR can replace them with a pointer to this audit doc.
- The April-10 `be3bb97` retune should not be reverted as a revert commit; instead, land a new commit that moves the parameters back to the W13 values with a comment citing this audit as the evidence.
- Verify `trades.db` records the `regime` column on future signals so the next baseline reconstruction isn't blind to regime for the winning era.
- Issue 24-A (backtest-config) explicitly limited scope to "no slippage model" — replay results will flatter real outcomes. Any config whose replay scorecard is marginal on points is probably unprofitable after slippage + commission.

---

## Confidence level

**High** on the W13-vs-W15-16 deltas — 564 combined trades is enough sample size to be confident the expectancy regression is real and not noise.

**Medium** on W13 being a reproducible baseline — 92 trades with 91/92 directional bias means the regime was favorable. A 30-day backtest-config replay is the right way to validate the revert against modern data.

**Low** on the April-10 audit's "IBKR-era" attribution being meaningful — the numbers in the inline comments don't match this repo's history, so they were either pulled from a different codebase or approximated. Either way, they are not the target.
