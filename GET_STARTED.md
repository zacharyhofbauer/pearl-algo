# 🚀 Get PearlAlgo Running - Quick Start

## ✅ What's Working

- ✅ Code is fixed and tested
- ✅ Dummy data provider works (synthetic market data)
- ✅ Environment variables configured
- ✅ System can run without IBKR Gateway

## 🎯 Quick Start (Choose One)

### Option A: Test First (Recommended)

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate
python test_system.py
```

**Expected:** All 3 tests pass ✅

### Option B: Start Trading Immediately

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate
./start_micro_paper_trading.sh
```

**What happens:**
- System tries IBKR → fails (expected, Gateway not running)
- System tries Polygon → fails (expected, no API key)
- System uses **dummy data** → ✅ Works!
- System generates signals and runs trading cycles

## 📋 Your Current Setup

**Environment (.env):**
```
✅ IBKR_HOST=127.0.0.1
✅ IBKR_PORT=4002
✅ IBKR_CLIENT_ID=10
✅ IBKR_DATA_CLIENT_ID=11
✅ PEARLALGO_PROFILE=paper
✅ GROQ_API_KEY=configured
✅ OPENAI_API_KEY=configured
```

**Missing (Optional - not required):**
- IBKR Gateway (not running - OK, dummy data works)
- Polygon API key (empty - OK, dummy data works)

## 🔍 What You'll See

### When Running:

```
🚀 Starting Paper Trading with Micro Contracts
================================================

Checking IBKR Gateway...
⚠ IBKR Gateway not detected. Starting anyway...

Starting LangGraph Paper Trading System...
Symbols: MES, MNQ
Strategy: Support/Resistance
Mode: Paper Trading
Interval: 60 seconds

WebSocket not supported for broker: ibkr
API connection failed: ConnectionRefusedError...  ← Expected
Using dummy data for MES (all real sources failed)  ← ✅ This is good!
Using dummy data for MNQ (all real sources failed)  ← ✅ This is good!
MarketDataAgent: Updated 2 symbols
Starting cycle #1
QuantResearchAgent: Generated signals
RiskManagerAgent: Evaluated risk
PortfolioExecutionAgent: Executed decisions
```

### In Logs:

```bash
# View live activity
tail -f logs/langgraph_trading.log | grep -E "(Signal|Trade|Position|dummy)"
```

## 📊 Monitor Trades

**Terminal 2:**
```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./monitor_trades.sh
```

**Or manually:**
```bash
tail -f logs/langgraph_trading.log
```

## 🛠️ Troubleshooting

### "All data sources failed" but no dummy data

**Fix:** Ensure mode is "paper":
```bash
python -m pearlalgo.live.langgraph_trader --mode paper --symbols MES --max-cycles 1
```

### "Module not found"

**Fix:** Activate venv:
```bash
source .venv/bin/activate
pip install -e .[dev]
```

### System hangs

**Fix:** Check if port 4002 is in use:
```bash
lsof -i :4002
# If something is using it, kill it or change IBKR_PORT in .env
```

## 📁 Files Created

- `logs/langgraph_trading.log` - All activity
- `data/performance/futures_decisions.csv` - Trade decisions
- `state_cache/trading_state.json` - Current state
- `signals/*.csv` - Generated signals

## 🎯 Next Steps

1. **Run test:** `python test_system.py` ✅
2. **Start trading:** `./start_micro_paper_trading.sh` 🚀
3. **Monitor:** `./monitor_trades.sh` 👀
4. **Review trades:** Check `data/performance/futures_decisions.csv` 📊

## 💡 Tips

- **Dummy data is fine** for testing - it generates realistic price movements
- **No real money** is used in paper mode
- **IBKR Gateway** is optional - add it later for real data
- **Polygon API** is optional - add it later for better fallback

## 🆘 Still Having Issues?

1. Run test: `python test_system.py`
2. Check logs: `tail -50 logs/langgraph_trading.log`
3. Share error output

---

**You're ready to go!** 🎉


