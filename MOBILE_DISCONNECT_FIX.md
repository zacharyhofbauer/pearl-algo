# Fix: Mobile App Disconnection Issue

## ✅ Solution Applied

**Updated Client ID to 10** - This should prevent conflicts with your mobile app.

## What Changed

- **Before**: Client ID 3 (could conflict)
- **After**: Client ID 10 (safer, less likely to conflict)
- **Mobile App**: Uses Client ID 0 (main session)
- **Automated System**: Uses Client ID 10 (secondary session)

## Why This Should Fix It

1. **Higher Client IDs are safer** - Client IDs 0-1 are main sessions, 2-9 might conflict, 10+ are typically safe
2. **Clear separation** - Mobile app (0) and automated system (10) are far apart
3. **IB Gateway allows multiple sessions** on paper trading, but they need different Client IDs

## Testing

1. **Restart your automated trading system** (if running):
   ```bash
   # Stop any running trading
   pkill -f "pearlalgo trade"
   
   # Start fresh with new Client ID
   pearlalgo trade auto --symbols MES MNQ
   ```

2. **Open your mobile app** - it should stay connected now

3. **Verify both work simultaneously**:
   - Mobile app shows your account
   - Automated system can place orders
   - No disconnection messages

## If It Still Disconnects

### Option 1: Check IB Gateway Settings

1. Open IB Gateway
2. **Configure → Settings → API → Settings**
3. Make sure:
   - ✅ "Enable ActiveX and Socket Clients" is checked
   - ✅ "Read-Only API" is enabled (for secondary connections)
   - ✅ Socket port is 4002

### Option 2: Use Even Higher Client ID

If Client ID 10 still conflicts, try 20 or higher:

```bash
# Edit .env
PEARLALGO_IB_CLIENT_ID=20
```

### Option 3: Connection Management

The automated system should:
- Connect only when actively trading
- Disconnect when idle
- Not maintain persistent connections unnecessarily

If you see multiple connections, you may need to:
- Stop all automated trading processes
- Restart IB Gateway
- Start automated trading fresh

## Current Configuration

```bash
PEARLALGO_IB_HOST=127.0.0.1
PEARLALGO_IB_PORT=4002          # Paper trading
PEARLALGO_IB_CLIENT_ID=10      # Secondary session (safe for mobile)
PEARLALGO_PROFILE=live
PEARLALGO_ALLOW_LIVE_TRADING=true
```

## Best Practices

1. **Use Client ID 10+** for automated systems
2. **Let mobile app use Client ID 0** (default)
3. **Restart IB Gateway** if you see persistent conflicts
4. **Check for multiple connections** - only one automated trading process should run

## Verify It's Working

```bash
# Test connection with new Client ID
python scripts/test_broker_connection.py

# Should show: "Connecting to 127.0.0.1:4002 (Client ID: 10)..."
# Should connect successfully
```

Then open your mobile app - it should stay connected! 📱✅

