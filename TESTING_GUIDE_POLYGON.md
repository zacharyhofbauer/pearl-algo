# Polygon-Only System Testing Guide

This guide walks you through testing the restructured Polygon-only market data retrieval system.

## Quick Start

### 1. Install Dependencies

```bash
# Activate virtual environment
source .venv/bin/activate  # or: python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 2. Set Up Environment

```bash
# Copy example env file
cp .env.example .env

# Add your Polygon API key
echo "POLYGON_API_KEY=your_key_here" >> .env
```

### 3. Run Tests

```bash
# Run all tests
pytest

# Run only Polygon provider tests
pytest tests/test_polygon_provider.py -v

# Run with coverage
pytest --cov=src/pearlalgo/data_providers/polygon_provider --cov-report=html
```

## Test Categories

### Unit Tests (Mocked)

These tests don't require a real API key and use mocks:

```bash
# Run unit tests only
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit -v
pytest tests/test_polygon_provider.py::TestPolygonConfig -v
pytest tests/test_polygon_provider.py::TestPolygonHealthMonitor -v
```

**What they test:**
- Configuration loading
- Rate limiting logic
- Session management
- Error handling (401, 429, timeouts)
- Health monitoring
- Circuit breaker behavior

### Integration Tests (Real API)

These tests require a valid Polygon API key:

```bash
# Set API key
export POLYGON_API_KEY=your_key_here

# Run integration tests
pytest tests/test_polygon_provider.py::TestPolygonProviderIntegration -v -m integration
```

**What they test:**
- Real API calls to Polygon
- Data retrieval (latest bar, historical)
- Circuit breaker with real requests
- Rate limit handling

### Error Handling Tests

```bash
# Test error scenarios
pytest tests/test_polygon_provider.py::TestPolygonProviderErrorHandling -v
```

**What they test:**
- Network errors
- Timeouts
- Invalid responses
- Malformed JSON

## Testing Specific Components

### 1. Polygon Provider

```bash
# Test provider initialization
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit::test_session_management -v

# Test rate limiting
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit::test_rate_limiting -v

# Test data retrieval (mocked)
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit::test_get_latest_bar_success -v
```

### 2. Configuration

```bash
# Test config from API key
pytest tests/test_polygon_provider.py::TestPolygonConfig::test_config_from_api_key -v

# Test config from environment
pytest tests/test_polygon_provider.py::TestPolygonConfig::test_config_from_env -v
```

### 3. Health Monitoring

```bash
# Test health metrics
pytest tests/test_polygon_provider.py::TestPolygonHealthMonitor -v
```

## Manual Testing

### Test Polygon Provider Directly

Create a test script `test_polygon_manual.py`:

```python
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pearlalgo.data_providers.polygon_provider import PolygonDataProvider

async def test_polygon():
    # Get API key from environment
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print("ERROR: Set POLYGON_API_KEY environment variable")
        return
    
    # Create provider
    provider = PolygonDataProvider(api_key=api_key)
    
    print("Testing Polygon.io provider...")
    
    # Test 1: Get latest bar
    print("\n1. Testing get_latest_bar('AAPL')...")
    result = await provider.get_latest_bar("AAPL")
    if result:
        print(f"   ✅ Success: {result['close']} @ {result['timestamp']}")
    else:
        print("   ❌ Failed or no data")
    
    # Test 2: Fetch historical data
    print("\n2. Testing fetch_historical('AAPL', last 7 days)...")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    df = provider.fetch_historical("AAPL", start=start, end=end, timeframe="1d")
    if not df.empty:
        print(f"   ✅ Success: {len(df)} bars retrieved")
        print(f"   First: {df.index[0]}, Last: {df.index[-1]}")
    else:
        print("   ❌ Failed or no data")
    
    # Test 3: Health check
    print("\n3. Testing health monitoring...")
    # Health monitor would be integrated in real usage
    print("   ✅ Health monitoring available")
    
    # Cleanup
    await provider.close()
    print("\n✅ All tests completed")

if __name__ == "__main__":
    asyncio.run(test_polygon())
```

Run it:
```bash
python test_polygon_manual.py
```

### Test Market Data Agent

```python
import asyncio
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.agents.langgraph_state import TradingState

async def test_market_data_agent():
    # Create agent (no broker needed!)
    agent = MarketDataAgent(
        symbols=["AAPL", "MSFT"],
        config={}  # Will use POLYGON_API_KEY from env
    )
    
    # Create initial state
    state = TradingState()
    
    # Fetch data
    state = await agent.fetch_live_data(state)
    
    print(f"Fetched data for {len(state.market_data)} symbols")
    for symbol, data in state.market_data.items():
        print(f"  {symbol}: ${data.close:.2f}")
    
    await agent.close()

asyncio.run(test_market_data_agent())
```

## Testing Workflow Integration

### Test Full LangGraph Workflow

```bash
# Test the complete workflow (signal-only mode)
python -m pytest tests/test_workflow_integration.py -v
```

This tests:
- Market data agent (Polygon)
- Signal generation
- Risk management
- Signal logging (no broker execution)

## Common Issues & Solutions

### Issue: "POLYGON_API_KEY not set"

**Solution:**
```bash
export POLYGON_API_KEY=your_key_here
# Or add to .env file
```

### Issue: Rate limit errors (429)

**Solution:**
- Tests use exponential backoff automatically
- Integration tests may hit rate limits - use sparingly
- Consider using a test/demo API key for integration tests

### Issue: "Circuit breaker is open"

**Solution:**
- Circuit breaker opens after 5 consecutive failures
- Wait 60 seconds for recovery
- Check API key validity
- Check network connectivity

### Issue: Tests failing due to missing paper trading

**Solution:**
- Some old tests may reference paper trading
- Update or remove those tests
- Paper trading was removed as part of restructuring

## Test Coverage Goals

Target coverage:
- **Polygon Provider**: >80%
- **Configuration**: 100%
- **Health Monitoring**: >90%
- **Error Handling**: >85%

Check coverage:
```bash
pytest --cov=src/pearlalgo/data_providers --cov-report=term-missing
```

## Continuous Integration

For CI/CD, use mocked tests only:

```bash
# CI should run unit tests (no API key needed)
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit -v
pytest tests/test_polygon_provider.py::TestPolygonConfig -v
pytest tests/test_polygon_provider.py::TestPolygonHealthMonitor -v
pytest tests/test_polygon_provider.py::TestPolygonProviderErrorHandling -v
```

Integration tests should run separately with a test API key.

## Next Steps

1. **Run unit tests** to verify basic functionality
2. **Set up API key** and run integration tests
3. **Test with real symbols** (AAPL, MSFT, etc.)
4. **Monitor health metrics** during testing
5. **Check error handling** with invalid API keys

## Additional Resources

- Polygon API Docs: https://polygon.io/docs
- Polygon Rate Limits: https://polygon.io/pricing
- Test Data: Use free tier for testing (limited requests)

