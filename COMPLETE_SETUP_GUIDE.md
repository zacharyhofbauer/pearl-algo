# Complete Setup Guide - Get PearlAlgo Running

## Current Status

✅ **Code is fixed** - All parameter mismatches resolved
✅ **Dummy provider created** - Synthetic data for paper trading
✅ **Environment variables configured** - Your .env file looks good
❌ **IBKR Gateway not running** - Port 4002 connection refused
❌ **Polygon API key missing** - Returns 401 (optional, not critical)

## Quick Start (3 Options)

### Option 1: Run WITHOUT IBKR (Recommended for Testing)

The system will automatically use dummy data when real sources fail.

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate
./start_micro_paper_trading.sh
```

**What happens:**
- System tries IBKR → fails → tries Polygon → fails → uses dummy data ✅
- You'll see: "Using dummy data for MES (all real sources failed)"
- System continues running and generates signals

### Option 2: Start IBKR Gateway First

If you want real data:

```bash
# Terminal 1: Start IBKR Gateway
cd /home/pearlalgo/pearlalgo-dev-ai-agents
# If you have IBC installed:
ibc/start_ibgateway.sh

# Or manually:
# Download IB Gateway from Interactive Brokers
# Configure it to listen on port 4002
# Start it

# Terminal 2: Start Trading System
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate
./start_micro_paper_trading.sh
```

### Option 3: Add Polygon API Key (Optional)

For better data fallback:

1. Get free API key: https://polygon.io/
2. Add to `.env`:
   ```bash
   POLYGON_API_KEY=your_key_here
   ```
3. Update `config/config.yaml`:
   ```yaml
   data:
     fallback:
       polygon:
         api_key: "${POLYGON_API_KEY}"
   ```

## Your Current .env File

```bash
IBKR_HOST=127.0.0.1          # ✅ Correct
IBKR_PORT=4002                # ✅ Correct
IBKR_CLIENT_ID=10             # ✅ Correct
IBKR_DATA_CLIENT_ID=11        # ✅ Correct
PEARLALGO_PROFILE=paper       # ✅ Correct
GROQ_API_KEY=...              # ✅ Configured
OPENAI_API_KEY=...            # ✅ Configured
```

**Missing (Optional):**
- `POLYGON_API_KEY=` (empty - that's OK, dummy provider will work)

## Step-by-Step Test

### 1. Verify Environment

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Check Python
python --version  # Should be 3.12+

# Check imports
python -c "from pearlalgo.live.langgraph_trader import LangGraphTrader; print('✓ OK')"

# Check dummy provider
python -c "from pearlalgo.data_providers.dummy_provider import DummyDataProvider; dp = DummyDataProvider(['MES']); print(f'✓ Dummy works: {dp.get_latest_bar(\"MES\")[\"close\"]:.2f}')"
```

### 2. Test Single Cycle

```bash
# Run one cycle (should complete in ~10 seconds)
python -m pearlalgo.live.langgraph_trader \
    --symbols MES \
    --strategy sr \
    --mode paper \
    --interval 5 \
    --max-cycles 1
```

**Expected output:**
- "WebSocket not supported for broker: ibkr" (OK, expected)
- "API connection failed" (OK, IBKR not running)
- "Polygon API error" (OK, no key)
- "Using dummy data for MES" (✅ This means it's working!)
- "MarketDataAgent: Updated 1 symbols"
- "Starting cycle #1"
- "QuantResearchAgent: Generated signals"
- "RiskManagerAgent: Evaluated risk"
- "PortfolioExecutionAgent: Executed decisions"

### 3. Run Continuous Trading

```bash
./start_micro_paper_trading.sh
```

**What to watch for:**
- System starts without errors
- Logs show "Using dummy data" messages
- Cycles run every 60 seconds
- Signals are generated
- Trades are logged (paper mode)

### 4. Monitor in Another Terminal

```bash
# Terminal 2
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./monitor_trades.sh

# Or watch logs directly
tail -f logs/langgraph_trading.log | grep -E "(Signal|Trade|Position|dummy)"
```

## Troubleshooting

### Issue: "All data sources failed" but no dummy data

**Fix:** Check that trading mode is "paper" in config:
```bash
# In config/config.yaml, ensure:
trading:
  mode: "paper"
```

Or pass it explicitly:
```bash
python -m pearlalgo.live.langgraph_trader --mode paper ...
```

### Issue: "Module not found" errors

**Fix:** Activate virtual environment:
```bash
source .venv/bin/activate
pip install -e .[dev]
```

### Issue: IBKR connection errors

**Fix:** This is expected if IBKR Gateway isn't running. The system will use dummy data automatically.

### Issue: System hangs or doesn't start

**Fix:** Check for port conflicts:
```bash
netstat -tuln | grep 4002
lsof -i :4002
```

## What Gets Logged

- **Market Data**: Prices, volumes (from dummy provider if real sources fail)
- **Signals**: Buy/sell signals with confidence scores
- **Risk Decisions**: Position sizing, stop losses, take profits
- **Trades**: Entry/exit decisions (paper mode - no real money)
- **Performance**: P&L, drawdown, trade statistics

## Files Created

- `logs/langgraph_trading.log` - Main log file
- `data/performance/futures_decisions.csv` - Trade decisions
- `state_cache/trading_state.json` - Current system state
- `signals/*.csv` - Generated signals

## Next Steps

1. **Get it running** - Use Option 1 (dummy data) to test
2. **Monitor output** - Watch logs to see signals and trades
3. **Add real data** - Start IBKR Gateway when ready
4. **Review trades** - Check `data/performance/futures_decisions.csv`

## Quick Commands Reference

```bash
# Start trading
./start_micro_paper_trading.sh

# Monitor trades
./monitor_trades.sh

# View logs
tail -f logs/langgraph_trading.log

# Check system status
python -m pearlalgo.utils.health

# Run single test cycle
python -m pearlalgo.live.langgraph_trader --symbols MES --max-cycles 1
```

## Support

If something still doesn't work:
1. Check logs: `tail -50 logs/langgraph_trading.log`
2. Run test: `python -m pearlalgo.live.langgraph_trader --symbols MES --max-cycles 1`
3. Share the error output


