# IBKR Connection Issues - Fixes Applied

## Problems Identified

1. **Event Loop Conflict**: "This event loop is already running"
   - ib_insync uses asyncio internally, but when called from an async context, it conflicts
   
2. **Client ID Conflicts**: "clientId 2 already in use"
   - Multiple connections trying to use the same client ID
   - Settings not loading environment variables correctly
   
3. **Connection Timeouts**: Connection hangs or times out
   - Gateway rejecting connections due to conflicts
   - No proper fallback to dummy data

## Fixes Applied

### 1. Event Loop Handling (`ibkr_data_provider.py`)

- Added thread-based connection for async contexts
- Detects if running in async context and uses separate thread with new event loop
- Falls back to direct connection if no async context

### 2. Client ID Loading (`ibkr_data_provider.py`)

- Now checks both `IBKR_DATA_CLIENT_ID` and `PEARLALGO_IB_DATA_CLIENT_ID` environment variables
- Proper fallback chain: env var → settings → calculated value
- Added debug logging to show which client ID is being used

### 3. Error Handling (`market_data_agent.py`)

- Better detection of connection errors
- Faster fallback to dummy data when IBKR unavailable
- Suppresses noisy error messages for expected failures

### 4. Broker Connection (`ibkr_broker.py`)

- Improved error messages for client ID conflicts
- Better handling of event loop errors

## Expected Behavior Now

### Dummy Mode Flag

The system now uses an explicit `dummy_mode` flag to control dummy data fallback:

- **`PEARLALGO_DUMMY_MODE=false` (default)**: System will raise clear errors if IBKR connection fails
- **`PEARLALGO_DUMMY_MODE=true`**: System will use dummy data if IBKR connection fails

This prevents silent fallback to dummy data when IBKR is misconfigured, making connectivity issues obvious.

### Connection Scenarios

1. **If IBKR Gateway is NOT running:**
   - Connection fails quickly (5 second timeout)
   - Clear error message with instructions
   - **If `dummy_mode=true`**: System uses dummy data and continues
   - **If `dummy_mode=false`**: System raises error with helpful message pointing to this doc

2. **If Client ID is in use:**
   - Error is detected and logged with clear message
   - **If `dummy_mode=true`**: System falls back to dummy data
   - **If `dummy_mode=false`**: System raises error with instructions

3. **If Event Loop conflict:**
   - Connection runs in separate thread
   - New event loop created for IBKR connection
   - Falls back gracefully if still fails

## Testing

To verify fixes work:

```bash
# Test with IBKR Gateway OFF and dummy_mode enabled
# First, set PEARLALGO_DUMMY_MODE=true in .env
python test_system.py

# Should see:
# - "Using dummy data for MES (dummy_mode=True, all real sources failed)" ✅
# - No noisy "event loop" or "client id" errors ✅
# - Tests pass ✅

# Test with IBKR Gateway OFF and dummy_mode disabled
# Set PEARLALGO_DUMMY_MODE=false in .env
python test_system.py

# Should see:
# - Clear error message about IBKR connection failure ✅
# - Instructions to set dummy_mode or fix IBKR config ✅
# - Error points to this documentation ✅
```

## Environment Variables

Make sure your `.env` has:
```bash
# IBKR Configuration (IBKR_* takes precedence over PEARLALGO_*)
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11

# Trading Mode
PEARLALGO_PROFILE=paper

# Dummy Mode (explicit control)
# Set to true to allow dummy data fallback when IBKR unavailable
# Set to false (default) to raise errors when IBKR unavailable
PEARLALGO_DUMMY_MODE=false
```

Or use the PEARLALGO_ prefix (IBKR_* takes precedence):
```bash
PEARLALGO_IB_HOST=127.0.0.1
PEARLALGO_IB_PORT=4002
PEARLALGO_IB_CLIENT_ID=10
PEARLALGO_IB_DATA_CLIENT_ID=11
```

Both formats are supported. See `.env.example` for complete template.

## Debugging

Use the debug script to verify your configuration:

```bash
python scripts/debug_env.py
```

This will show:
- All IBKR settings
- Validation warnings/errors
- Dummy mode status
- Recommendations

## Next Steps

1. Run `python scripts/debug_env.py` to verify configuration
2. Run `python test_system.py` to verify fixes
3. Start paper trading: `./start_micro_paper_trading.sh`
4. If testing without IBKR, set `PEARLALGO_DUMMY_MODE=true` in `.env`

