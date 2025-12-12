# Future Providers Guide

This guide explains how to add new data providers (Massive, DataBento, etc.) to the system.

## Architecture Overview

The system uses a provider-agnostic architecture:

```
[ Strategy Code ]
        ↓
[ MarketDataProvider Interface ]
        ↓
[ Provider Implementation (IBKR/Massive/DataBento) ]
```

Strategies only depend on the `MarketDataProvider` interface, never on provider-specific code.

## Adding a New Provider

### Step 1: Create Provider Module

Create a new directory for your provider:

```bash
mkdir -p src/pearlalgo/data_providers/{provider_name}
```

Example:
```bash
mkdir -p src/pearlalgo/data_providers/massive
mkdir -p src/pearlalgo/data_providers/databento
```

### Step 2: Implement MarketDataProvider Interface

Create `src/pearlalgo/data_providers/{provider_name}/{provider_name}_provider.py`:

```python
from pearlalgo.data_providers.market_data_provider import MarketDataProvider

class MassiveProvider(MarketDataProvider):
    """Massive futures data provider."""
    
    def __init__(self, api_key: str, ...):
        # Initialize provider
        pass
    
    async def get_underlier_price(self, symbol: str) -> float:
        # Implement using Massive API
        pass
    
    async def get_option_chain(self, symbol: str, filters: Optional[Dict] = None) -> List[Dict]:
        # Implement using Massive API
        pass
    
    # ... implement all required methods
```

See `docs/PROVIDER_INTERFACE.md` for complete interface specification.

### Step 3: Register in Factory

Update `src/pearlalgo/data_providers/factory.py`:

```python
from .massive.massive_provider import MassiveProvider

_PROVIDER_REGISTRY: Dict[str, Type[DataProvider]] = {
    "ibkr": IBKRProvider,
    "massive": MassiveProvider,  # Add here
    "databento": DataBentoProvider,  # Add here
    # ...
}

def create_data_provider(...):
    # Add provider-specific initialization
    elif provider_name == "massive":
        api_key = kwargs.get("api_key") or settings.massive_api_key
        return provider_class(api_key=api_key, ...)
```

### Step 4: Add Configuration

Update configuration files to support new provider:

**config/config.yaml:**
```yaml
data:
  provider: "massive"  # or "databento"
  massive:
    api_key: "${MASSIVE_API_KEY}"
  databento:
    api_key: "${DATABENTO_API_KEY}"
```

### Step 5: Update Settings

Add provider settings to `src/pearlalgo/config/settings.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...
    massive_api_key: Optional[str] = None
    databento_api_key: Optional[str] = None
```

### Step 6: Add Tests

Create test file `tests/test_{provider_name}_provider.py`:

```python
import pytest
from pearlalgo.data_providers.massive.massive_provider import MassiveProvider

@pytest.mark.asyncio
async def test_massive_provider_connection():
    provider = MassiveProvider(api_key="test_key")
    assert await provider.validate_connection()

@pytest.mark.asyncio
async def test_massive_get_underlier_price():
    provider = MassiveProvider(api_key="test_key")
    price = await provider.get_underlier_price("SPY")
    assert price > 0
```

### Step 7: Update Documentation

- Update `README.md` to mention new provider
- Update `ARCHITECTURE.md` with provider details
- Add provider-specific setup guide if needed

## Provider-Specific Considerations

### Massive Futures

**Key Features:**
- Futures-focused data
- Real-time and historical data
- Options on futures

**Implementation Notes:**
- May need different contract specification format
- Futures symbols may differ from IBKR
- Handle roll dates for continuous contracts

### DataBento

**Key Features:**
- High-frequency market data
- Options and futures
- Historical data access

**Implementation Notes:**
- May require WebSocket connections
- Different authentication mechanism
- Handle rate limits carefully

## Testing Provider Integration

1. **Unit Tests**: Test provider methods in isolation
2. **Integration Tests**: Test with real API (use test keys)
3. **Strategy Tests**: Verify strategies work with new provider
4. **End-to-End Tests**: Full trading flow with new provider

## Switching Providers

To switch from IBKR to another provider:

1. Update `config/config.yaml`:
   ```yaml
   data:
     provider: "massive"  # Change from "ibkr"
   ```

2. Update environment variables:
   ```bash
   export MASSIVE_API_KEY=your_key
   ```

3. Restart service - strategies will automatically use new provider

## Assumptions to Avoid

**DO NOT:**
- Hardcode provider-specific logic in strategies
- Assume provider-specific data formats
- Use provider-specific error types in strategies
- Depend on provider-specific features without abstraction

**DO:**
- Use `MarketDataProvider` interface in all strategy code
- Normalize data in provider layer
- Handle errors generically in strategies
- Abstract provider-specific features

## Example: Adding Massive Provider

See `src/pearlalgo/data_providers/ibkr/` for a complete reference implementation.

Key files to create:
- `src/pearlalgo/data_providers/massive/massive_provider.py` - Main provider class
- `src/pearlalgo/data_providers/massive/__init__.py` - Module exports
- `tests/test_massive_provider.py` - Tests

Then register in factory and update configuration.

## Questions?

- See `docs/PROVIDER_INTERFACE.md` for interface details
- See `src/pearlalgo/data_providers/ibkr/` for reference implementation
- Check existing tests for examples
