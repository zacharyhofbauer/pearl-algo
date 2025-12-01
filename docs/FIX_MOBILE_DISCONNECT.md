# Fix: Mobile App Disconnection Issue

## Problem
IBKR mobile app says "someone with same username disconnected me"

## Root Cause
IBKR has session limits - even on paper trading, multiple connections from the same account can conflict. The mobile app and automated system are competing for session slots.

## Solutions

### Solution 1: Use Higher Client ID (Recommended)

The automated system should use a **much higher Client ID** to avoid conflicts:

```bash
# Edit .env file
PEARLALGO_IB_CLIENT_ID=10  # Use 10 or higher
```

**Why this works:**
- Client IDs 0-1 are typically reserved for main sessions
- Client IDs 2-9 might still conflict with mobile app
- Client IDs 10+ are safer for automated systems

### Solution 2: Ensure Proper Connection Management

The automated system should:
- Connect only when needed
- Disconnect when idle
- Not maintain persistent connections

### Solution 3: Use Read-Only API Mode

Configure IB Gateway to allow read-only secondary connections:
1. Open IB Gateway
2. Configure → Settings → API → Settings
3. Enable "Read-Only API" for secondary connections
4. Set "Socket port" to 4002
5. Enable "Enable ActiveX and Socket Clients"

### Solution 4: Mobile App Connection Priority

When using mobile app:
1. **Close automated trading** temporarily
2. **Use mobile app** for monitoring
3. **Restart automated trading** when done

Or vice versa - use automated trading when mobile app is closed.

## Recommended Configuration

```bash
# .env file
PEARLALGO_IB_HOST=127.0.0.1
PEARLALGO_IB_PORT=4002
PEARLALGO_IB_CLIENT_ID=10        # Higher client ID
PEARLALGO_PROFILE=live
PEARLALGO_ALLOW_LIVE_TRADING=true
```

## Testing

After changing Client ID:

```bash
# Test connection
python scripts/test_broker_connection.py

# Check if mobile app still works
# Open mobile app - should not disconnect
```

## Alternative: Connection Lifecycle Management

If conflicts persist, the automated system should:
1. Connect only during active trading hours
2. Disconnect when not actively trading
3. Use connection pooling to avoid multiple simultaneous connections

## Understanding IBKR Session Limits

**Paper Trading (Port 4002):**
- Allows multiple sessions BUT
- Each session uses a Client ID
- Mobile app typically uses Client ID 0
- Too many connections can still cause conflicts

**Best Practice:**
- Mobile app: Client ID 0 (main session)
- Automated system: Client ID 10+ (secondary session)
- Keep connections minimal and well-managed

