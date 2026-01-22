# Testing Guide

## Overview

All tests in this project use **actual production code** dynamically without duplicating files or code. Tests import directly from `src/pearlalgo/` and run against the real implementation.

## Key Principles

1. **No Code Duplication**: Tests import actual production code from `src/pearlalgo/`
2. **Dynamic Imports**: Tests use Python's import system - no file copying needed
3. **Development Mode**: Package must be installed in development mode: `pip install -e .`
4. **Shared Fixtures**: Common test fixtures are in `tests/conftest.py`
5. **Mock Helpers**: `MockDataProvider` is a test helper (not production code)

## Running Tests

### Quick Start

```bash
# Install package in development mode (required for tests)
pip install -e .

# Install test dependencies
pip install -e '.[dev]'

# Run all tests
pytest
# or
./scripts/testing/run_tests.sh

# Run specific test file
pytest tests/test_config_loader.py

# Run with coverage
pytest --cov=pearlalgo --cov-report=html
```

### Test Scripts

- **`./scripts/testing/run_tests.sh`**: Runs all pytest unit tests
- **`python3 scripts/testing/test_all.py`**: Integration tests (Telegram, signals, service, arch)

## Test Structure

```
tests/
├── __init__.py          # Package marker, ensures imports work
├── conftest.py          # Shared pytest fixtures and configuration
├── mock_data_provider.py # Test helper for fake market data
└── test_*.py            # Individual test files
```

## How Tests Import Production Code

Tests import directly from the installed package:

```python
# ✅ Correct - imports actual production code
from pearlalgo.config.config_loader import load_service_config
from pearlalgo.trading_bots.pearl_bot_auto import generate_signals
from pearlalgo.market_agent.service import MarketAgentService

# ❌ Wrong - don't duplicate code in tests/
# from tests.duplicate_code import something
```

## Configuration

### pytest.ini

- Configures test discovery
- Sets up Python path to include `src/` and `.`
- Defines test markers for categorization
- Configures coverage reporting

### conftest.py

- Sets up Python path for all tests
- Provides shared fixtures
- Ensures tests can import actual code

## Test Helpers

### MockDataProvider

Located in `tests/mock_data_provider.py`, this is a test helper that:
- Implements the `DataProvider` interface
- Generates synthetic market data for testing
- Simulates IBKR connection issues, timeouts, etc.
- **Does NOT duplicate production code** - it's a test utility

Usage:
```python
from tests.mock_data_provider import MockDataProvider

provider = MockDataProvider(base_price=17500.0, volatility=25.0)
data = await provider.get_latest_bar("MNQ")
```

## Test Categories

Tests are marked with pytest markers:

- `@pytest.mark.unit`: Fast, isolated unit tests
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.slow`: Tests that take > 1 second
- `@pytest.mark.requires_ibkr`: Tests needing IBKR connection
- `@pytest.mark.requires_telegram`: Tests needing Telegram credentials

Run specific categories:
```bash
pytest -m unit              # Only unit tests
pytest -m "not slow"        # Skip slow tests
pytest -m "not requires_ibkr"  # Skip IBKR tests
```

## Troubleshooting

### Import Errors

If tests fail with import errors:

1. **Ensure package is installed in development mode:**
   ```bash
   pip install -e .
   ```

2. **Check Python path:**
   ```bash
   python3 -c "import sys; print(sys.path)"
   # Should include project root and src/
   ```

3. **Verify pytest.ini configuration:**
   - `pythonpath` should include `src` and `.`

### Tests Not Found

If pytest doesn't find tests:

1. **Check test file naming:** Must start with `test_`
2. **Check test function naming:** Must start with `test_`
3. **Verify testpaths in pytest.ini:** Should be `tests`

### Using Mock vs Real Code

- **Use MockDataProvider** for testing strategy logic without real market data
- **Use actual production classes** for testing business logic
- **Mock external services** (IBKR, Telegram) but use real internal code

## Best Practices

1. **Always import from `pearlalgo.*`** - never duplicate code in tests/
2. **Use fixtures** from `conftest.py` for common setup
3. **Mark tests appropriately** with pytest markers
4. **Keep tests fast** - use mocks for slow operations
5. **Test actual behavior** - use real code, mock external dependencies

## Integration Tests

For integration-style tests (Telegram, signals, service lifecycle), use:

```bash
python3 scripts/testing/test_all.py [mode]
```

Modes:
- `all` (default): Run all integration tests
- `telegram`: Test Telegram notifications
- `signals`: Test signal generation
- `service`: Test full service lifecycle
- `arch`: Test architecture boundaries
