# Connection Status & Paper Trading Guide

## ✅ What's Connected

### IBKR Gateway
- **Status**: ✅ RUNNING
- **Process ID**: 308045
- **Port**: 4002 (listening)
- **API Ready**: ✅ Accepting connections
- **Location**: `/home/pearlalgo/ibc/config-auto.ini`

### Environment Configuration
- **Status**: ✅ CONFIGURED
- **.env file**: ✅ Exists
- **IBKR_HOST**: ✅ Configured
- **IBKR_PORT**: ✅ Configured  
- **IBKR_CLIENT_ID**: ✅ Configured
- **PEARLALGO_PROFILE**: ✅ Configured

### System Components
- **Virtual Environment**: ✅ Active
- **Dependencies**: ✅ Installed
- **Configuration Files**: ✅ Valid
- **Performance Logs**: ✅ Directory exists

## ❌ What's NOT Connected (Optional)

### LLM Providers (Optional - for signal reasoning)
- **Groq API**: Not configured (optional)
- **OpenAI API**: Not configured (optional)
- **Anthropic API**: Not configured (optional)
- **Note**: System works without LLM, just won't have AI reasoning for signals

### Alerts (Optional)
- **Telegram**: Not configured (optional)
- **Discord**: Not configured (optional)
- **Note**: System works without alerts, just won't send notifications

### Alternative Brokers (Not needed - using IBKR)
- **Bybit**: Not configured (only needed for crypto)
- **Alpaca**: Not configured (alternative to IBKR)

### Data Fallback (Optional)
- **Polygon.io**: Not configured (optional fallback for market data)

## 🎯 Ready for Paper Trading!

**Everything you need is connected:**
- ✅ IBKR Gateway running
- ✅ Configuration valid
- ✅ System ready

---

## 🚀 Starting Paper Trading with Micro Contracts

### Step 1: Start Trading System

Open **Terminal 1** and run:

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./start_micro_paper_trading.sh
```

Or manually:
```bash
python -m pearlalgo.live.langgraph_trader \
    --symbols MES MNQ \
    --strategy sr \
    --mode paper \
    --interval 60
```

**What this does:**
- Connects to IBKR Gateway
- Starts trading MES (Micro E-mini S&P 500) and MNQ (Micro E-mini Nasdaq)
- Uses Support/Resistance strategy
- Runs in paper mode (no real money)
- Checks for signals every 60 seconds

### Step 2: Monitor Trades (Separate Terminal)

Open **Terminal 2** and run:

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./monitor_trades.sh
```

Or use the dashboard:
```bash
python scripts/dashboard.py --live
```

### Step 3: Watch Logs (Optional - Terminal 3)

```bash
tail -f logs/langgraph_trading.log | grep -E "(Signal|Trade|Position|Risk)"
```

---

## 📊 What You'll See

### In the Trading Terminal

```
🚀 Starting Paper Trading with Micro Contracts
================================================

✓ IBKR Gateway is running

Starting LangGraph Paper Trading System...
Symbols: MES, MNQ (Micro E-mini S&P 500 and Nasdaq)
Strategy: Support/Resistance
Mode: Paper Trading
Interval: 60 seconds

Press Ctrl+C to stop

[INFO] MarketDataAgent: Fetching live data for all symbols
[INFO] QuantResearchAgent: Generating signals for all symbols
[INFO] RiskManagerAgent: Evaluating risk for MES
[INFO] PortfolioExecutionAgent: Executing position decisions
```

### In the Monitor Terminal

```
📊 PearlAlgo Trade Monitor
===========================

=== System Status ===
✓ Trading system is running
✓ IBKR Gateway is running

=== Latest Trades ===
timestamp           symbol  side   entry_price  realized_pnl
2024-12-02 10:30:15 MES     LONG   4850.25      0.00
2024-12-02 10:45:22 MES     EXIT   4852.50      22.50

=== Latest Signals ===
timestamp           symbol  direction  confidence  entry_price
2024-12-02 10:30:15 MES     LONG       0.75        4850.25
```

### Trade Files Created

1. **Performance Log**: `data/performance/futures_decisions.csv`
   - All trade entries and exits
   - P&L tracking
   - Entry/exit times

2. **Signals Log**: `signals/YYYYMMDD_HHMMSS_signals.csv`
   - All generated signals
   - Confidence scores
   - Strategy details

3. **State Cache**: `data/state_cache/state.json`
   - Current system state
   - Positions
   - Risk state

---

## 🔍 Understanding the Output

### When a Signal is Generated

```
[INFO] QuantResearchAgent: Generated LONG signal for MES (confidence: 0.75)
```

This means:
- Strategy detected a LONG opportunity
- Confidence: 75% (0.75)
- Will be evaluated by Risk Manager

### When Risk Manager Approves

```
[INFO] RiskManagerAgent: Approved position for MES: 1 contracts @ $4850.25
[INFO] RiskManagerAgent: Risk: $97.50 (2.0% of portfolio)
```

This means:
- Risk check passed
- Position size calculated (1 micro contract)
- Risk amount: $97.50 (2% of $5,000 starting balance)

### When Trade is Executed

```
[INFO] PortfolioExecutionAgent: Entering LONG for MES: 1 contracts @ $4850.25
[INFO] PortfolioExecutionAgent: Order submitted for MES: order_12345
```

In paper mode:
- Order is logged but NOT sent to broker
- Position tracked in system
- P&L calculated based on price movements

### When Trade Exits

```
[INFO] PortfolioExecutionAgent: Exiting position for MES: 1 contracts
[INFO] PortfolioExecutionAgent: Realized P&L: $22.50
```

---

## 📈 Micro Contracts Explained

### MES (Micro E-mini S&P 500)
- **Tick Value**: $1.25 per point
- **Contract Size**: 5 points per contract
- **Example**: If MES moves from 4850 to 4851, you make $1.25 per contract
- **Risk**: Much lower than full ES contract

### MNQ (Micro E-mini Nasdaq)
- **Tick Value**: $2.00 per point
- **Contract Size**: 2 points per contract
- **Example**: If MNQ moves from 15000 to 15001, you make $2.00 per contract
- **Risk**: Much lower than full NQ contract

### Why Micros?
- ✅ Lower risk (1/10th the size of regular contracts)
- ✅ Perfect for testing strategies
- ✅ Lower capital requirements
- ✅ Same price movements as full contracts

---

## 🎮 Quick Commands

### Start Trading
```bash
./start_micro_paper_trading.sh
```

### Monitor Trades
```bash
./monitor_trades.sh
```

### View Latest Trades
```bash
tail -20 data/performance/futures_decisions.csv
```

### View Latest Signals
```bash
ls -t signals/*_signals.csv | head -1 | xargs tail -10
```

### View Logs
```bash
tail -f logs/langgraph_trading.log
```

### Stop Trading
```bash
# In the trading terminal, press Ctrl+C
```

---

## ⚠️ Important Notes

1. **Paper Trading**: No real money is at risk
2. **Market Hours**: Trades only happen during market hours (9:30 AM - 4:00 PM ET)
3. **Signal Frequency**: Signals generated every 60 seconds (configurable)
4. **Risk Limits**: Hardcoded 2% max risk per trade, 15% daily drawdown limit
5. **Micro Contracts**: Much smaller position sizes, perfect for testing

---

## 🐛 Troubleshooting

### No Trades Happening?

1. **Check if market is open**: Trades only during market hours
2. **Check signals**: Look at `signals/` directory for generated signals
3. **Check risk state**: System may be in cooldown or hit risk limits
4. **Check logs**: `tail -f logs/langgraph_trading.log`

### IBKR Connection Issues?

```bash
# Test connection
python scripts/setup_assistant.py --test-connection

# Restart Gateway
python scripts/setup_assistant.py --restart-gateway
```

### Want to See More Activity?

- Reduce interval: `--interval 30` (check every 30 seconds)
- Add more symbols: `--symbols MES MNQ MCL MGC`
- Try different strategy: `--strategy ma_cross` or `--strategy breakout`

---

## 🎯 Next Steps

1. ✅ Start the trading system
2. ✅ Monitor in separate terminal
3. ✅ Watch for signals and trades
4. ✅ Review performance logs
5. ✅ Adjust strategy parameters if needed

**Ready to start? Run `./start_micro_paper_trading.sh` in one terminal and `./monitor_trades.sh` in another!**

