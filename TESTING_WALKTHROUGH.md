# Testing Walkthrough - Polygon-Only System

This is a step-by-step walkthrough for testing the restructured Polygon-only system.

## Prerequisites

1. **Python 3.12+** installed
2. **Virtual environment** (we'll create if needed)
3. **Polygon API key** (optional for unit tests, required for integration tests)

## Step 1: Quick Setup (30 seconds)

```bash
# Navigate to project
cd /home/pearlalgo/pearlalgo-dev-ai-agents

# Run the quick test script
./QUICK_TEST_POLYGON.sh
```

This script will:
- ✅ Create virtual environment if needed
- ✅ Install dependencies
- ✅ Run all unit tests (mocked, no API key needed)
- ✅ Run integration tests if API key is set
- ✅ Show test summary

## Step 2: Manual Testing (5 minutes)

### 2.1 Test Configuration

```bash
# Activate environment
source .venv/bin/activate

# Run config tests
pytest tests/test_polygon_provider.py::TestPolygonConfig -v
```

**Expected output:**
```
✅ test_config_from_api_key PASSED
✅ test_config_custom_settings PASSED
✅ test_config_from_env PASSED
✅ test_config_from_env_missing_key PASSED
```

### 2.2 Test Provider (Mocked)

```bash
# Run unit tests (no API key needed)
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit -v
```

**What's tested:**
- Rate limiting logic
- Session management
- Successful API responses (mocked)
- Rate limit handling (429)
- Unauthorized errors (401)

### 2.3 Test Health Monitoring

```bash
# Test health metrics
pytest tests/test_polygon_provider.py::TestPolygonHealthMonitor -v
```

**What's tested:**
- Health metrics recording
- Success/failure tracking
- Health status calculation
- Rate limit tracking

### 2.4 Test Error Handling

```bash
# Test error scenarios
pytest tests/test_polygon_provider.py::TestPolygonProviderErrorHandling -v
```

**What's tested:**
- Network errors
- Timeouts
- Invalid JSON responses

## Step 3: Integration Testing (Requires API Key)

### 3.1 Set Up API Key

```bash
# Option 1: Environment variable
export POLYGON_API_KEY=your_key_here

# Option 2: Add to .env file
echo "POLYGON_API_KEY=your_key_here" >> .env
```

### 3.2 Run Integration Tests

```bash
# Test real API calls
pytest tests/test_polygon_provider.py::TestPolygonProviderIntegration -v -m integration
```

**What's tested:**
- Real API calls to Polygon
- Data retrieval (latest bar, historical)
- Circuit breaker with real requests

**Expected output:**
```
✅ test_get_latest_bar_real PASSED (may skip if API key invalid)
✅ test_fetch_historical_real PASSED
✅ test_circuit_breaker_real PASSED
```

## Step 4: Manual API Testing

Create a test script to manually verify the provider:

```python
# test_manual.py
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pearlalgo.data_providers.polygon_provider import PolygonDataProvider

async def main():
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print("❌ Set POLYGON_API_KEY environment variable")
        return
    
    provider = PolygonDataProvider(api_key=api_key)
    
    print("🧪 Testing Polygon Provider")
    print("=" * 40)
    
    # Test 1: Latest bar
    print("\n1. Getting latest bar for AAPL...")
    result = await provider.get_latest_bar("AAPL")
    if result:
        print(f"   ✅ Price: ${result['close']:.2f}")
        print(f"   ✅ Volume: {result['volume']:,}")
        print(f"   ✅ Timestamp: {result['timestamp']}")
    else:
        print("   ❌ No data (check API key)")
    
    # Test 2: Historical data
    print("\n2. Fetching last 7 days of AAPL...")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    df = provider.fetch_historical("AAPL", start=start, end=end, timeframe="1d")
    if not df.empty:
        print(f"   ✅ Retrieved {len(df)} bars")
        print(f"   ✅ Date range: {df.index[0].date()} to {df.index[-1].date()}")
        print(f"   ✅ Latest close: ${df['close'].iloc[-1]:.2f}")
    else:
        print("   ❌ No data (check API key or symbol)")
    
    await provider.close()
    print("\n✅ Testing complete!")

if __name__ == "__main__":
    asyncio.run(main())
```

Run it:
```bash
python test_manual.py
```

## Step 5: Test Market Data Agent

Test the full agent integration:

```python
# test_agent.py
import asyncio
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.agents.langgraph_state import TradingState

async def test_agent():
    print("🧪 Testing MarketDataAgent")
    print("=" * 40)
    
    # Create agent (no broker parameter needed!)
    agent = MarketDataAgent(
        symbols=["AAPL", "MSFT", "GOOGL"],
        config={}  # Uses POLYGON_API_KEY from env
    )
    
    # Create state
    state = TradingState()
    
    # Fetch data
    print("\nFetching live data...")
    state = await agent.fetch_live_data(state)
    
    print(f"\n✅ Fetched data for {len(state.market_data)} symbols:")
    for symbol, data in state.market_data.items():
        print(f"   {symbol}: ${data.close:.2f} (vol: {data.volume:,.0f})")
    
    await agent.close()
    print("\n✅ Agent test complete!")

asyncio.run(test_agent())
```

## Step 6: Test Coverage

Check test coverage:

```bash
# Run with coverage
pytest --cov=src/pearlalgo/data_providers/polygon_provider \
       --cov=src/pearlalgo/data_providers/polygon_config \
       --cov=src/pearlalgo/data_providers/polygon_health \
       --cov-report=term-missing \
       --cov-report=html

# View HTML report
open htmlcov/index.html  # macOS
# or
xdg-open htmlcov/index.html  # Linux
```

**Target coverage:**
- Polygon Provider: >80%
- Configuration: 100%
- Health Monitoring: >90%

## Step 7: Test Workflow Integration

Test the complete LangGraph workflow:

```bash
# Test workflow (signal-only mode, no broker needed)
pytest tests/test_workflow_integration.py -v
```

This verifies:
- ✅ Market data agent works with Polygon
- ✅ Signal generation works
- ✅ Risk management works
- ✅ Signal logging works (no broker execution)

## Common Issues & Solutions

### Issue: "ModuleNotFoundError: No module named 'pearlalgo'"

**Solution:**
```bash
pip install -e .
```

### Issue: "POLYGON_API_KEY not set"

**Solution:**
```bash
export POLYGON_API_KEY=your_key_here
# Or add to .env file and load with python-dotenv
```

### Issue: Rate limit errors (429)

**Solution:**
- Tests automatically use exponential backoff
- Free tier has strict limits - use sparingly
- Consider upgrading to paid tier for testing

### Issue: Tests fail with "paper_trading" import errors

**Solution:**
- Paper trading was removed - update any remaining tests
- Margin models moved to `risk/margin_models.py`

## Test Checklist

- [ ] Unit tests pass (no API key needed)
- [ ] Configuration tests pass
- [ ] Health monitoring tests pass
- [ ] Error handling tests pass
- [ ] Integration tests pass (with API key)
- [ ] Manual API test works
- [ ] Market data agent works
- [ ] Workflow integration works
- [ ] Test coverage >80%

## Next Steps

1. ✅ Run quick test script
2. ✅ Verify unit tests pass
3. ✅ Set API key and test integration
4. ✅ Test with real symbols
5. ✅ Check test coverage
6. ✅ Review TESTING_GUIDE_POLYGON.md for details

## Quick Reference

```bash
# Run all Polygon tests
pytest tests/test_polygon_provider.py -v

# Run only unit tests (no API key)
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit -v

# Run integration tests (needs API key)
pytest tests/test_polygon_provider.py::TestPolygonProviderIntegration -v -m integration

# Run with coverage
pytest --cov=src/pearlalgo/data_providers --cov-report=html

# Quick test script
./QUICK_TEST_POLYGON.sh
```

Happy testing! 🚀
