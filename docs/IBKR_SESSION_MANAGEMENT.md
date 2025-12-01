# IBKR Session Management Guide

## Why Paper Trading Doesn't Conflict

**Paper Trading and Live Trading are Separate Systems:**
- Paper trading uses **port 7497** (TWS) or **port 4002** (Gateway)
- Live trading uses **port 7496** (TWS) or **port 4001** (Gateway)
- They are completely independent - you can be logged into both simultaneously

## Why Live Trading Sessions Conflict

**IBKR Session Limits:**
- **One "main" session per account** for live trading
- The mobile app creates a "main" session
- IB Gateway/TWS also creates a "main" session
- When both try to connect, IBKR kicks one out

**Session Types:**
1. **Main Session** (Client ID 0 or 1): Full trading capabilities, can place orders
2. **Read-Only Session** (Client ID > 1): Can view data but limited trading
3. **Market Data Session**: Separate client ID for data only

## Current Setup

Your automated trading system is configured to use:
- **Port**: 4002 (IB Gateway paper trading port)
- **Client ID**: 1 (main session)
- **Profile**: live (but connecting to paper port)

## Solutions

### Option 1: Use Different Client IDs (Recommended)

Configure the automated system to use a higher client ID (read-only or secondary session):

```python
# In .env or settings
PEARLALGO_IB_CLIENT_ID=2  # Or higher (read-only session)
```

**Pros:**
- Can run automated trading while using mobile app
- Mobile app gets main session (Client ID 0/1)
- Automated system uses secondary session

**Cons:**
- Some order types may be limited on secondary sessions
- May need to verify order placement works

### Option 2: Use Separate Accounts

- Keep automated trading on paper account (port 4002)
- Use mobile app for live trading (different account)

### Option 3: Disconnect Mobile When Trading

- Close mobile app when automated trading is active
- Or vice versa

### Option 4: Use IB Gateway API Mode

Configure IB Gateway to allow multiple API connections:
- Gateway Settings → API → Settings
- Enable "Read-Only API" for secondary connections
- Use Client ID > 1 for automated system

## Recommended Configuration

For running automated trading while using mobile app:

```bash
# .env file
PEARLALGO_IB_HOST=127.0.0.1
PEARLALGO_IB_PORT=4002          # Paper trading
PEARLALGO_IB_CLIENT_ID=2        # Secondary session (read-only)
PEARLALGO_PROFILE=live
PEARLALGO_ALLOW_LIVE_TRADING=true
```

**Note:** If you need to place orders from the automated system, you may need Client ID 1, which means you'll need to disconnect the mobile app.

## Testing Session Configuration

Run this to check your current session setup:

```bash
python scripts/test_broker_connection.py
```

Check the output for:
- Client ID being used
- Port number
- Whether it's a read-only or main session

## IB Gateway Settings

To allow multiple sessions:

1. Open IB Gateway
2. Go to **Configure → Settings → API → Settings**
3. Check **"Read-Only API"** for secondary connections
4. Set **"Socket port"** to 4002 (paper) or 4001 (live)
5. Enable **"Enable ActiveX and Socket Clients"**

## Mobile App Behavior

- Mobile app typically uses Client ID 0 (main session)
- When it connects, it may disconnect other main sessions
- Read-only sessions (Client ID > 1) usually don't conflict

## Best Practices

1. **For Development/Testing:**
   - Use paper trading (port 4002) with Client ID 2+
   - Mobile app can connect to live without conflict

2. **For Live Trading:**
   - Use Client ID 1 for automated system
   - Disconnect mobile app when automated trading is active
   - Or use Client ID 2+ if order placement works

3. **For Monitoring:**
   - Use Client ID 3+ for read-only monitoring
   - Won't conflict with trading sessions

## Troubleshooting

**Error: "Another application is using this connection"**
- Another session with same Client ID is active
- Solution: Use different Client ID or disconnect other session

**Error: "Connection lost" when mobile app opens**
- Mobile app is taking over main session
- Solution: Use Client ID 2+ for automated system

**Orders not executing on secondary session**
- Some order types require main session
- Solution: Use Client ID 1, but disconnect mobile app

