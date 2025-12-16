# Prop Firm Trading Configuration

## Overview

This configuration is optimized for **prop firm style trading** with **Mini NQ (MNQ)** futures, focusing on:
- **Intraday swings** (15-60 minute holds)
- **Quick scalps** (5-15 minute holds)
- **Conservative risk management** (prop firm rules)

## Key Changes from Standard NQ Strategy

### 1. Symbol: NQ → MNQ

**MNQ (Mini NQ) Benefits:**
- 1/10th the size of NQ contracts
- Lower margin requirements
- Better for prop firm account sizes
- Same price action, smaller risk per contract

**Contract Specifications:**
- **MNQ:** $2 per point (0.25 point = $0.50 per tick)
- **NQ:** $20 per point (0.25 point = $5.00 per tick)
- **Size Ratio:** 1 NQ = 10 MNQ

### 2. Position Sizing: 5-15 Contracts

**Prop Firm Typical Range:**
- **Minimum:** 5 MNQ contracts
- **Default:** 10 MNQ contracts  
- **Maximum:** 15 MNQ contracts

**Risk Calculation:**
- Risk per contract = Stop Loss Points × $2 (MNQ tick value)
- Total risk = Risk per contract × Number of contracts
- Example: 3.75 point stop × $2 × 10 contracts = $75 risk

### 3. Tighter Stops for Scalping

**Stop Loss Settings:**
- **ATR Multiplier:** 1.5 (was 2.0) - tighter stops
- **Stop Loss Ticks:** 15 ticks (3.75 points)
- **Max Risk:** 1% per trade (was 2%)

**Take Profit Settings:**
- **Risk/Reward:** 1.5:1 (was 2:1) - quicker profits
- **Take Profit Ticks:** 22 ticks (5.5 points)
- **Target Hold Time:** 5-15 minutes for scalps, 15-60 minutes for swings

### 4. Faster Signal Scanning

**Scan Interval:**
- **30 seconds** (was 60 seconds)
- Faster detection of scalping opportunities
- More responsive to quick price movements

### 5. Prop Firm Risk Rules

**Daily Risk Limits:**
- **Max Risk Per Trade:** 1% of account
- **Max Daily Drawdown:** 10% (prop firm typical)
- **Max Position Size:** 15 contracts
- **Min Position Size:** 5 contracts

**Example Risk Calculation:**
```
Account Size: $50,000 (prop firm typical)
Max Risk Per Trade: 1% = $500
Stop Loss: 3.75 points
Risk Per Contract: 3.75 × $2 = $7.50
Max Contracts: $500 ÷ $7.50 = 66 contracts
But limited to: 15 contracts (position size limit)
Actual Risk: 15 × $7.50 = $112.50 (0.225% of account)
```

## Strategy Adjustments for Scalping

### Signal Generation

**Faster Entry Conditions:**
- Tighter confidence thresholds (50% vs 55%)
- Quicker signal validation
- More frequent signals during active periods

**Session Filters:**
- **Avoid Lunch Lull:** 11:30 AM - 1:00 PM ET (low volume, choppy)
- **Focus on Active Hours:** 
  - Opening: 9:30-10:30 AM ET
  - Morning: 10:30-11:30 AM ET
  - Afternoon: 1:00-3:30 PM ET
  - Closing: 3:30-4:00 PM ET

### Timeframe Optimization

**Primary Timeframe:** 1-minute bars
- Fast enough for scalping
- Detailed enough for quick entries/exits

**Multi-Timeframe Analysis:**
- 1m: Entry signals
- 5m: Trend confirmation
- 15m: Overall direction

## Configuration Files

### config.yaml

```yaml
symbol: "MNQ"
timeframe: "1m"
scan_interval: 30

risk:
  max_risk_per_trade: 0.01  # 1%
  max_drawdown: 0.10  # 10%
  stop_loss_atr_multiplier: 1.5
  take_profit_risk_reward: 1.5
  max_position_size: 15
  min_position_size: 5
```

### Strategy Config (config.py)

- Symbol: `MNQ`
- Scan Interval: `30 seconds`
- Stop Loss ATR: `1.5x` (tighter)
- Risk/Reward: `1.5:1` (quicker profits)
- Position Size: `5-15 contracts`

## Prop Firm Trading Tips

### 1. Risk Management

- **Never risk more than 1% per trade**
- **Respect daily drawdown limits**
- **Use position sizing calculator**
- **Scale in/out gradually**

### 2. Trade Selection

- **Focus on high-probability setups**
- **Avoid choppy/lunch hours**
- **Trade with the trend**
- **Wait for clear signals**

### 3. Execution

- **Quick entries on signals**
- **Tight stops (3-4 points)**
- **Quick profits (5-6 points)**
- **Don't hold losers**

### 4. Performance Tracking

- **Track win rate (target: >55%)**
- **Monitor average R:R (target: >1.5:1)**
- **Review daily P&L**
- **Adjust based on results**

## Example Trade

**Setup:**
- Signal: Momentum Long
- Entry: $17,500.00
- Stop Loss: $17,496.25 (3.75 points)
- Take Profit: $17,505.50 (5.5 points)
- Position Size: 10 MNQ contracts

**Risk:**
- Risk per contract: 3.75 × $2 = $7.50
- Total risk: 10 × $7.50 = $75.00
- Risk %: $75 / $50,000 = 0.15% (well under 1% limit)

**Reward:**
- Reward per contract: 5.5 × $2 = $11.00
- Total reward: 10 × $11.00 = $110.00
- R:R Ratio: $110 / $75 = 1.47:1

## Monitoring

Check Telegram for:
- Signal notifications with position size
- Risk calculations per trade
- Performance summaries
- Daily/weekly P&L

## Next Steps

1. **Update config.yaml** with MNQ symbol
2. **Restart agent** to apply changes
3. **Monitor first few trades** carefully
4. **Adjust position sizing** based on account size
5. **Review performance** weekly

---

**Remember:** Prop firm trading requires discipline. Stick to your rules, respect risk limits, and focus on consistency over big wins.
