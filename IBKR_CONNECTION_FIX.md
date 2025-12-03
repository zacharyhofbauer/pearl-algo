# IBKR Connection Fix - Event Loop Issue

**Date**: After testing paper trading startup  
**Issue**: "Event loop is closed" and "ConnectionError: Not connected" during contract discovery

---

## Problem

When starting paper trading, the system was failing with:
- "Event loop is closed" errors
- "ConnectionError: Not connected" 
- Contract discovery timing out
- Data fetching failing

The root cause: IB connections are tied to specific event loops. When `discover_future_contracts()` or `resolve_future_contract()` runs in an async context, it creates a new event loop in a thread, but tries to use the IB connection from the original event loop, which fails.

---

## Solution

Updated `src/pearlalgo/brokers/contracts.py` to:

1. **Create new connections in threads**: When running in async context, create a fresh IB connection in the thread's new event loop instead of reusing the original connection.

2. **Proper cleanup**: Disconnect thread connections before closing the event loop.

3. **Use data client ID**: Thread connections use the data client ID (11) to avoid conflicts with the main connection (10).

---

## Code Changes

**File**: `src/pearlalgo/brokers/contracts.py`

**Functions Updated**:
- `discover_future_contracts()` - Creates new connection in thread
- `resolve_future_contract()` - Creates new connection in thread for qualification

**Key Changes**:
- Thread functions now create `IBKRDataProvider` with new connection
- Connections are properly disconnected before event loop closes
- Uses data client ID to avoid conflicts

---

## Testing

After this fix, contract discovery should work properly in async contexts. The system should be able to:
- Discover futures contracts
- Resolve contract details
- Fetch market data

---

## Next Steps

If issues persist:
1. Check IBKR Gateway is running: `python scripts/debug_ibkr.py`
2. Verify client IDs don't conflict
3. Check IBKR Gateway logs for connection issues
4. Consider enabling dummy mode for testing: `PEARLALGO_DUMMY_MODE=true`

---

**This fix ensures IB connections work correctly in async contexts.**

