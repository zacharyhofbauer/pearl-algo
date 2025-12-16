# Real Data Testing Guide

## Overview

Tests have been updated to use **real market data** from IBKR instead of mock/dummy data. Tests will gracefully handle cases where IBKR Gateway is not available.

## Test Fixtures

### `real_data_provider` Fixture

All integration tests now use the `real_data_provider` fixture which:
- Uses actual `IBKRProvider` to fetch real market data
- Gracefully skips tests if IBKR Gateway is not running
- Automatically cleans up connections after tests

### `past_signals` Fixture

Telegram notification tests use the `past_signals` fixture which:
- Loads real past signals from `data/nq_agent_state/signals.jsonl`
- Uses actual signal data for testing notifications
- Falls back to test data if no past signals are available

## Running Tests

### With IBKR Gateway Running

```bash
# Start IBKR Gateway first
./scripts/start_ibgateway_ibc.sh

# Run all tests (will use real market data)
pytest tests/ -v

# Run integration tests specifically
pytest tests/ -m integration -v
```

### Without IBKR Gateway

Tests will automatically skip if IBKR Gateway is not available:

```bash
# Tests will skip gracefully
pytest tests/ -v

# To see which tests were skipped
pytest tests/ -v -rs
```

## Test Behavior

### Integration Tests
- **Use Real Data**: Fetch actual market data from IBKR
- **Real Signals**: Use past signals from state files for Telegram tests
- **Graceful Fallback**: Skip if services unavailable (no failures)

### Unit Tests
- Continue to work without external services
- Test logic and data structures
- Fast execution

## Benefits

1. **Real Market Conditions**: Tests run against actual market data
2. **Past Signal Testing**: Telegram tests use real historical signals
3. **No Mock Data**: Eliminates synthetic data that may not reflect real conditions
4. **Graceful Handling**: Tests skip when services unavailable (no false failures)

## Notes

- Tests that require IBKR Gateway will be marked as `@pytest.mark.integration`
- Use `pytest -m "not integration"` to run only unit tests
- Real data tests may take longer due to network calls
- Past signals are loaded from `data/nq_agent_state/signals.jsonl` if available
