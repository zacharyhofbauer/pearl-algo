# IBKR Connection Fixes - Final Solution

**Date**: After research and implementation  
**Issues Fixed**: 
- "Error 326: client id already in use"
- "Event loop is closed"
- "ConnectionError: Not connected"
- Contract discovery timeouts

---

## Root Causes Identified

Based on research of IBKR API best practices and ib_insync documentation:

1. **Multiple Connections with Same Client ID**: Creating multiple connections all trying to use client ID 11 caused "client id already in use" errors.

2. **Event Loop Conflicts**: IB connections are tied to event loops. Creating new event loops in threads and trying to use connections from different loops caused "Event loop is closed" errors.

3. **Premature Disconnection**: Disconnecting connections after each call prevented reuse and caused "Not connected" errors.

4. **Async Method Misuse**: Using async methods (`reqContractDetailsAsync`, `qualifyContractsAsync`) from threads with different event loops caused connection issues.

---

## Solution Implemented

### 1. Connection Manager (Singleton Pattern)

**File**: `src/pearlalgo/data_providers/ibkr_connection_manager.py`

- Maintains **one connection per client ID** (singleton pattern)
- Thread-safe connection access
- Reuses existing connections instead of creating new ones
- Prevents "client id already in use" errors

**Key Features**:
- `IBKRConnectionManager.get_instance()` - Returns singleton for client ID
- `get_connection()` - Returns existing or creates new connection
- Thread-safe with locks

### 2. Simplified Contract Discovery

**File**: `src/pearlalgo/brokers/contracts.py`

**Changes**:
- Removed thread-based async handling
- Use **sync methods** (`reqContractDetails`, `qualifyContracts`) instead of async
- ib_insync's sync methods work from any context (sync or async)
- Reuse existing connection instead of creating new ones

**Why This Works**:
- ib_insync's sync methods handle event loops internally
- No need to create new connections or event loops
- Works from both sync and async contexts

### 3. Keep Connections Alive

**File**: `src/pearlalgo/data_providers/ibkr_data_provider.py`

**Changes**:
- Removed `ib.disconnect()` calls after each operation
- Connections are kept alive for reuse
- Connection manager handles cleanup when needed

**Why This Works**:
- IBKR connections should be kept alive for reuse
- Disconnecting after each call causes "Not connected" errors
- Connection manager maintains connection lifecycle

### 4. Use Connection Manager

**File**: `src/pearlalgo/data_providers/ibkr_data_provider.py`

**Changes**:
- `IBKRDataProvider` now uses `IBKRConnectionManager`
- All connections go through the manager
- Ensures single connection per client ID

---

## Key Principles Applied

Based on IBKR API best practices:

1. **Single Connection Per Client ID**: One connection per client ID prevents conflicts
2. **Use Sync Methods**: ib_insync's sync methods work from any context
3. **Keep Connections Alive**: Don't disconnect after each operation
4. **Thread-Safe Access**: Use locks when accessing connections from multiple threads

---

## Testing

After these fixes:

1. **No More Client ID Conflicts**: Single connection per client ID
2. **No Event Loop Errors**: Using sync methods avoids event loop conflicts
3. **Connection Reuse**: Connections stay alive and are reused
4. **Contract Discovery Works**: Sync methods work from async contexts

---

## Usage

The fixes are transparent - existing code continues to work:

```python
from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider
from pearlalgo.config.settings import get_settings

provider = IBKRDataProvider(settings=get_settings())
# Connection is automatically managed by connection manager
data = provider.fetch_historical("MES")
```

---

## Files Modified

1. `src/pearlalgo/data_providers/ibkr_connection_manager.py` - NEW
2. `src/pearlalgo/data_providers/ibkr_data_provider.py` - Updated to use connection manager
3. `src/pearlalgo/brokers/contracts.py` - Simplified to use sync methods

---

## Next Steps

If issues persist:

1. Check IBKR Gateway is running: `python scripts/debug_ibkr.py`
2. Verify client IDs don't conflict (main: 10, data: 11)
3. Check IBKR Gateway logs for connection issues
4. For testing without IBKR: `PEARLALGO_DUMMY_MODE=true`

---

**This solution follows IBKR API best practices and ib_insync recommendations for connection management.**

