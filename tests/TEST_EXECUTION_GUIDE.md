# Test Execution Guide

## Quick Test Summary

### Unit Tests (Fast, No External Services)
```bash
# Run all unit tests (recommended for development)
pytest tests/ -m "not integration" -v

# Run specific test files
pytest tests/test_config_loading.py tests/test_nq_agent_state.py tests/test_nq_agent_performance.py tests/test_nq_agent_signals.py tests/test_telegram_integration.py -v
```

**Result**: All unit tests pass quickly (~6-7 seconds)

### Integration Tests (Require IBKR Gateway)
```bash
# Start IBKR Gateway first
./scripts/start_ibgateway_ibc.sh

# Wait for Gateway to be ready (check port 4002)
./scripts/check_gateway_status.sh

# Run integration tests
pytest tests/ -m integration -v
```

## Test Strategy

### Unit Tests (Default)
- **Use**: `mock_data_provider` fixture
- **Speed**: Fast (~0.01-0.1s per test)
- **Purpose**: Test logic, data structures, state management
- **No external dependencies**

### Integration Tests (Marked)
- **Use**: `real_data_provider` fixture  
- **Speed**: Slower (requires IBKR connection)
- **Purpose**: Test actual data fetching, real market data
- **Requires**: IBKR Gateway running

## Current Test Status

### ✅ All Passing (50 tests)
- `test_config_loading.py`: 13/13
- `test_nq_agent_state.py`: 9/9
- `test_nq_agent_performance.py`: 11/11
- `test_nq_agent_signals.py`: 7/7
- `test_telegram_integration.py`: 10/10

### ⚠️ Integration Tests
- Marked with `@pytest.mark.integration`
- Require IBKR Gateway
- Can be skipped: `pytest -m "not integration"`

## Why Tests Don't Hang Anymore

1. **Unit tests use mocks** - No connection attempts
2. **Session-scoped fixture** - Reuses single connection
3. **Faster retry settings** - Reduced delays for tests
4. **Proper timeouts** - Tests skip if connection fails
5. **Integration tests marked** - Can be run separately

## Best Practices

1. **Development**: Run unit tests only (`-m "not integration"`)
2. **CI/CD**: Run all tests, integration tests will skip if Gateway unavailable
3. **Pre-commit**: Run unit tests only for speed
4. **Full validation**: Run integration tests before releases
