# Provider Interface Documentation

This document describes the `MarketDataProvider` interface that all data providers must implement. This abstraction allows strategies to work with any data provider (IBKR, Massive, DataBento) without knowing implementation details.

## Interface Definition

All data providers must implement the `MarketDataProvider` abstract base class located in `src/pearlalgo/data_providers/market_data_provider.py`.

## Required Methods

### `async def get_underlier_price(symbol: str) -> float`

Get current price for an underlying symbol.

**Parameters:**
- `symbol`: Underlying symbol (e.g., 'SPY', 'QQQ')

**Returns:**
- Current price as float

**Raises:**
- `ConnectionError`: If provider is not connected
- `ValueError`: If symbol is invalid or not found

**Example:**
```python
price = await provider.get_underlier_price("SPY")
```

### `async def get_option_chain(symbol: str, filters: Optional[Dict] = None) -> List[Dict]`

Get options chain for an underlying symbol with optional filtering.

**Parameters:**
- `symbol`: Underlying symbol (e.g., 'SPY', 'QQQ')
- `filters`: Optional filter dictionary with keys:
  - `min_dte`: Minimum days to expiration
  - `max_dte`: Maximum days to expiration
  - `strike_proximity_pct`: Filter strikes within X% of current price
  - `min_volume`: Minimum volume threshold
  - `min_open_interest`: Minimum open interest threshold
  - `delta_range`: Tuple of (min_delta, max_delta)
  - `min_iv`: Minimum implied volatility
  - `expiration_date`: Specific expiration date (YYYYMMDD format)

**Returns:**
List of option contracts, each with:
- `symbol`: Option symbol string
- `underlying_symbol`: Underlying ticker
- `strike`: Strike price
- `expiration`: Expiration date (YYYYMMDD format)
- `expiration_date`: ISO format date string
- `dte`: Days to expiration
- `option_type`: 'call' or 'put'
- `bid`: Bid price
- `ask`: Ask price
- `last_price`: Last trade price
- `volume`: Volume
- `open_interest`: Open interest
- `iv`: Implied volatility (if available)
- `delta`: Delta (if available)
- `gamma`: Gamma (if available)
- `theta`: Theta (if available)
- `vega`: Vega (if available)

**Raises:**
- `ConnectionError`: If provider is not connected
- `ValueError`: If symbol is invalid or not found

**Example:**
```python
options = await provider.get_option_chain(
    "SPY",
    filters={
        "min_dte": 0,
        "max_dte": 7,
        "min_volume": 100,
    }
)
```

### `async def get_option_quotes(contracts: List[str]) -> List[Dict]`

Get real-time quotes for specific option contracts.

**Parameters:**
- `contracts`: List of option contract identifiers (provider-specific format)

**Returns:**
List of quote dictionaries with bid, ask, last, volume, etc.

**Raises:**
- `ConnectionError`: If provider is not connected

### `async def subscribe_realtime(symbols: List[str]) -> AsyncIterator[Dict]`

Subscribe to real-time market data updates.

**Parameters:**
- `symbols`: List of symbols to subscribe to (underliers or options)

**Yields:**
Dictionary with market data updates:
- `symbol`: Symbol string
- `timestamp`: Update timestamp
- `price`: Current price
- `bid`: Bid price (if available)
- `ask`: Ask price (if available)
- `volume`: Volume (if available)
- Other fields as available

**Raises:**
- `ConnectionError`: If provider is not connected

**Example:**
```python
async for update in provider.subscribe_realtime(["SPY", "QQQ"]):
    print(f"{update['symbol']}: ${update['price']}")
```

### `async def validate_connection() -> bool`

Validate that the provider is connected and ready.

**Returns:**
- `True` if connected and ready, `False` otherwise

### `async def validate_market_data_entitlements() -> Dict[str, bool]`

Validate market data entitlements for the account.

**Returns:**
Dictionary with entitlement status:
- `options_data`: True if options data is available
- `realtime_quotes`: True if real-time quotes are enabled
- `historical_data`: True if historical data is accessible
- `account_type`: 'paper' or 'live'

**Raises:**
- `ConnectionError`: If provider is not connected

### `async def close() -> None`

Close connection and cleanup resources.

This is a default implementation that does nothing. Providers can override if they need cleanup.

## Data Format Specifications

### Option Contract Format

All providers must return option contracts in the following format:

```python
{
    "symbol": "SPY 20241220 450 C",  # Provider-specific format
    "underlying_symbol": "SPY",
    "strike": 450.0,
    "expiration": "20241220",  # YYYYMMDD format
    "expiration_date": "2024-12-20",  # ISO format
    "dte": 7,  # Days to expiration
    "option_type": "call",  # or "put"
    "bid": 2.50,
    "ask": 2.55,
    "last_price": 2.52,
    "volume": 1000,
    "open_interest": 5000,
    "iv": 0.20,  # Implied volatility (if available)
    "delta": 0.50,  # Greeks (if available)
    "gamma": 0.01,
    "theta": -0.05,
    "vega": 0.10,
}
```

## Error Handling Expectations

### Connection Errors

When the provider is not connected, methods should raise `ConnectionError` with a descriptive message:

```python
if not await self.validate_connection():
    raise ConnectionError("Not connected to IB Gateway")
```

### Invalid Symbols

When a symbol is invalid or not found, methods should raise `ValueError`:

```python
if symbol not in available_symbols:
    raise ValueError(f"Symbol {symbol} not found or invalid")
```

### Rate Limiting

Providers should handle rate limiting gracefully:
- Return appropriate errors when rate limited
- Log warnings for rate limit issues
- Implement backoff strategies

## Implementation Checklist

When implementing a new provider:

- [ ] Implement all required methods from `MarketDataProvider`
- [ ] Handle connection lifecycle (connect, disconnect, reconnect)
- [ ] Implement proper error handling (ConnectionError, ValueError)
- [ ] Return data in the specified format
- [ ] Add logging for debugging
- [ ] Implement `validate_connection()` and `validate_market_data_entitlements()`
- [ ] Add unit tests
- [ ] Update factory to register new provider
- [ ] Update documentation

## Where to Plug In New Providers

1. **Create provider class** in `src/pearlalgo/data_providers/{provider_name}/`
2. **Implement MarketDataProvider interface**
3. **Register in factory** (`src/pearlalgo/data_providers/factory.py`)
4. **Add configuration** in config files
5. **Update documentation**

See `docs/FUTURE_PROVIDERS.md` for detailed guide on adding new providers.
