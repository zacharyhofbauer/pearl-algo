# Prop Firm Migration Guide: NQ → MNQ

## ✅ Changes Completed

### 1. Symbol Change: NQ → MNQ
- ✅ Updated `config.yaml`: `symbol: "MNQ"`
- ✅ Updated default in `config.py`: `symbol: str = "MNQ"`
- ✅ Updated Telegram notifications to default to MNQ
- ✅ Added MNQ to futures symbols list

### 2. Position Sizing: 5-15 Contracts
- ✅ `min_position_size: 5` contracts
- ✅ `max_position_size: 15` contracts  
- ✅ Default: 10 contracts per trade
- ✅ Risk calculation updated for MNQ tick value ($2/point)

### 3. Prop Firm Risk Parameters
- ✅ `max_risk_per_trade: 0.01` (1% - was 2%)
- ✅ `max_drawdown: 0.10` (10% - was 15%)
- ✅ `stop_loss_atr_multiplier: 1.5` (tighter - was 2.0)
- ✅ `take_profit_risk_reward: 1.5:1` (quicker - was 2:1)

### 4. Scalping Optimizations
- ✅ `scan_interval: 30` seconds (faster - was 60)
- ✅ Tighter stops: 15 ticks (3.75 points)
- ✅ Quick targets: 22 ticks (5.5 points)
- ✅ Expected hold time: 10 minutes for scalps
- ✅ Avoid lunch lull: 11:30 AM - 1:00 PM ET

### 5. Contract Specifications
- ✅ MNQ tick value: $2 per point (vs NQ $20)
- ✅ Risk calculation updated in signal generator
- ✅ Position size included in signal metadata

## 📋 Configuration Summary

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
  min_position_size: 5
  max_position_size: 15
```

### Key Differences

| Parameter | NQ (Old) | MNQ (New) | Reason |
|-----------|----------|-----------|--------|
| Symbol | NQ | MNQ | Prop firm friendly |
| Contracts | 1 | 5-15 | Better risk sizing |
| Tick Value | $20/point | $2/point | 1/10th size |
| Risk/Trade | 2% | 1% | Prop firm conservative |
| Stop ATR | 2.0x | 1.5x | Tighter for scalping |
| R:R Ratio | 2:1 | 1.5:1 | Quicker profits |
| Scan Interval | 60s | 30s | Faster signals |
| Hold Time | 30 min | 10 min | Quick scalps |

## 🚀 Next Steps

### 1. Restart Agent
```bash
# Stop current agent
./scripts/stop_nq_agent_service.sh

# Start with new MNQ configuration
./scripts/start_nq_agent_service.sh
```

### 2. Verify Configuration
```bash
# Check config is loaded correctly
./scripts/check_nq_agent_status.sh

# Validate strategy
python3 scripts/validate_strategy.py
```

### 3. Monitor First Trades
- Watch Telegram for MNQ signals
- Verify position sizing (5-15 contracts)
- Check risk calculations
- Review stop/target placement

### 4. Adjust as Needed
Based on your prop firm account:
- **Account Size:** Adjust position sizing
- **Risk Tolerance:** Adjust max_risk_per_trade
- **Trading Style:** Adjust stop/target ratios
- **Time Preferences:** Adjust session filters

## 📊 Example Trade

**Signal:**
- Type: Momentum Long
- Symbol: MNQ
- Entry: $17,500.00
- Stop: $17,496.25 (3.75 points)
- Target: $17,505.50 (5.5 points)
- Position: 10 contracts

**Risk:**
- Risk per contract: 3.75 × $2 = $7.50
- Total risk: 10 × $7.50 = $75.00
- Risk %: $75 / $50,000 = 0.15%

**Reward:**
- Reward per contract: 5.5 × $2 = $11.00
- Total reward: 10 × $11.00 = $110.00
- R:R: 1.47:1

## ⚠️ Important Notes

1. **MNQ is 1/10th the size of NQ**
   - Same price action, smaller risk
   - Better for prop firm account sizes
   - More contracts = better risk distribution

2. **Prop Firm Rules**
   - Respect daily drawdown limits
   - Never risk more than 1% per trade
   - Use position sizing limits (5-15 contracts)
   - Track performance daily

3. **Scalping Focus**
   - Quick entries/exits
   - Tighter stops
   - Faster profit targets
   - Avoid choppy periods

## 📚 Documentation

- [Prop Firm Configuration Guide](./docs/PROP_FIRM_CONFIG.md)
- [Strategy Testing Guide](./docs/STRATEGY_TESTING_GUIDE.md)
- [Testing Guide](./docs/TESTING_GUIDE.md)

---

**Ready to trade!** The strategy is now optimized for prop firm style trading with MNQ. Monitor carefully and adjust based on your results.
