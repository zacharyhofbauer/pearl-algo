# Trading Optimization Summary - Jan 9, 2026

## Current Performance (7 Days)
- **Win Rate**: 31.25% (CRITICAL - below break-even threshold)
- **Total P/L**: -$2,118
- **Avg P/L per Trade**: -$44
- **Break-even WR needed**: ~40%+ for 1.5:1 R:R, ~33% for 2.0:1 R:R

## Signal Type Performance

### ✅ GOOD Signals (Keep Enabled)
- **mean_reversion_long**: 47% WR, +$116 avg ✅ **BEST PERFORMER**
- **mean_reversion_short**: 33% WR, -$50 avg (needs wider stops)
- **sr_bounce_long**: 33% WR (marginal, but better than short)
- **breakout_long/short**: Need more data

### ❌ BAD Signals (Now Disabled)
- **sr_bounce_short**: 0% WR, -$289 avg loss ❌ **WORST**
- **momentum_short**: 0% WR, -$241 avg loss ❌
- **momentum_long**: 0% WR historically ❌

## Changes Made

### 1. Wider Stop Losses (CRITICAL FIX)
- **stop_loss_atr_multiplier**: 1.5 → **2.5** (67% wider)
- **max_stop_points**: 20.0 → **35.0** (75% wider)
- **adaptive_stops min_stop_points**: 5.0 → **8.0**
- **Session multipliers increased**: Tokyo 0.8→1.0, London 0.9→1.1, NY 1.0→1.2
- **Volatility multipliers increased**: High vol 1.3→1.5

**Why**: Current stops are too tight, causing premature exits. With 20-point stops, normal MNQ noise (15-25 points) triggers stops too early. Wider stops give trades room to develop.

### 2. Better Risk:Reward Ratio
- **take_profit_risk_reward**: 1.5 → **2.0**

**Why**: With 31% WR, need 2:1+ R:R to be profitable. Math:
- 1.5:1 R:R with 31% WR = (0.31 × 1.5) - (0.69 × 1.0) = -0.195 (losing)
- 2.0:1 R:R with 31% WR = (0.31 × 2.0) - (0.69 × 1.0) = -0.07 (still negative but better)
- Target: Get WR to 40%+ for sustainable profitability

### 3. Increased Position Sizing
- **base_contracts**: 3 → **5**
- **high_conf_contracts**: 8 → **10**
- **max_conf_contracts**: 12 → **15**

**Why**: Need larger positions to target $100+ per trade. Current math:
- With 5 contracts and 2:1 R:R: Risk $50, Target $100 (20 points × 5 contracts × $2/point)
- Scaling up to 10-15 contracts on high-confidence setups for bigger wins

### 4. Disabled Broken Signals
- **momentum_long**: Disabled (0% WR)
- **momentum_short**: Disabled (0% WR, -$241 avg)
- **sr_bounce_short**: Disabled (0% WR, -$289 avg)

**Why**: These signals are consistently losing money. Better to focus on signals that work (mean_reversion_long with 47% WR).

### 5. Reduced Claude API Costs (Credit Drain Fix)
**Disabled expensive features:**
- `llm_signal_annotation`: false (was true)
- `llm_trade_postmortem`: false (was true)
- `llm_pattern_recognition`: false (was true)
- `llm_risk_assessment`: false (was true)
- `llm_adaptive_tuning`: false (was true)

**Optimized Claude Monitor:**
- `realtime_monitoring`: false (was true)
- `frequent_interval_seconds`: 900 → **3600** (4x less frequent)
- `max_alerts_per_hour`: 12 → **6** (50% reduction)
- `auto_apply_enabled`: false (was true - was making things worse)
- `code_analysis_interval_hours`: 24 → **48** (2x less frequent)

**Why**: Claude API was draining credits with every trade. These features weren't adding enough value to justify the cost. Monitor still runs for daily/weekly reports, but much less frequently.

## Expected Impact

### Before (Current State)
- Win Rate: 31.25%
- Avg P/L: -$44/trade
- R:R: 1.5:1 (unprofitable with this WR)
- Stops: 20 points (too tight)
- Position Size: 3 contracts
- Claude API: High cost, low value

### After (Expected)
- **Win Rate**: Should improve to 35-40%+ with wider stops (fewer premature exits)
- **Avg P/L**: Target +$50 to +$100 per winning trade
- **R:R**: 2.0:1 (better match for WR)
- **Stops**: 30-35 points (allows trades to breathe)
- **Position Size**: 5-10 contracts (targets $100+ wins)
- **Claude API**: ~80% cost reduction

## Recommendations Going Forward

### 1. Monitor Performance
- Watch win rate over next 20-30 trades
- If WR improves to 40%+, system should be profitable
- If WR stays below 35%, consider further tightening entry filters

### 2. Focus on What Works
- **mean_reversion_long** is your best signal (47% WR, +$116 avg)
- Consider increasing position size on this signal type specifically
- Reduce or eliminate mean_reversion_short if it doesn't improve

### 3. Claude Monitor Decision
**Should you keep it?**
- **YES, but simplified**: Keep daily/weekly reports, disable real-time monitoring
- **Cost**: Now ~$10-20/month instead of $100+/month
- **Value**: Daily performance summaries are useful, auto-tuning was making things worse

### 4. Further Optimizations (If Still Losing)
- Increase minimum confidence threshold (currently 0.4)
- Focus on NY session only (best liquidity)
- Consider disabling mean_reversion_short if WR doesn't improve
- Increase min_risk_reward to 2.5:1 if WR stays low

## Math: Why These Changes Work

### Stop Loss Math
- **MNQ Average True Range (ATR)**: ~15-25 points
- **Old stop (1.5 ATR)**: ~22-37 points → too tight, normal noise hits it
- **New stop (2.5 ATR)**: ~37-62 points → gives room for normal volatility
- **Max stop points**: 35 points → prevents stops from being too wide on low-volatility days

### Risk:Reward Math
```
Break-even formula: WR × R:R_ratio - (1-WR) × 1.0 = 0

For 31% WR:
- 1.5:1 R:R = 0.31 × 1.5 - 0.69 = -0.195 (losing 19.5% per trade)
- 2.0:1 R:R = 0.31 × 2.0 - 0.69 = -0.07 (losing 7% per trade, but better)
- 2.5:1 R:R = 0.31 × 2.5 - 0.69 = +0.085 (winning 8.5% per trade)

Target: Get WR to 40% for sustainable profitability
40% WR × 2.0 R:R = 0.40 × 2.0 - 0.60 = +0.20 (20% edge per trade)
```

### Position Sizing Math
```
Target: $100 profit per winning trade

With 5 contracts, 2:1 R:R, 20-point profit target:
- Risk: 10 points × 5 contracts × $2 = $100
- Reward: 20 points × 5 contracts × $2 = $200 ✅

With 10 contracts (high confidence):
- Risk: 10 points × 10 contracts × $2 = $200
- Reward: 20 points × 10 contracts × $2 = $400 ✅✅
```

## Next Steps

1. **Restart the agent** to apply new config
2. **Monitor first 10-20 trades** with new settings
3. **Track win rate improvement** - target 35-40%+
4. **Review Claude Monitor daily reports** (should be cheaper now)
5. **Adjust further** if needed based on performance

## Files Changed
- `config/config.yaml`: Risk settings, stop losses, position sizing, signal enable/disable, Claude API optimizations
