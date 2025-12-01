# Mobile App Setup for Paper Trading Monitoring

## ✅ Configuration Complete

Your automated trading system is now configured to work alongside the IBKR mobile app:

- **Automated System**: Port 4002, Client ID 2 (secondary session)
- **Mobile App**: Port 4002, Client ID 0 (main session)
- **Both can connect simultaneously** ✅

## How It Works

### Paper Trading (Port 4002)
- **Multiple sessions allowed** on paper trading
- Mobile app uses Client ID 0 (main session) - can view and trade
- Automated system uses Client ID 2 (secondary session) - can view and trade
- **No conflicts** - both can be active at the same time

### Session Hierarchy
- **Client ID 0**: Main session (mobile app)
- **Client ID 1**: Alternative main session (not used)
- **Client ID 2+**: Secondary sessions (automated system)

## Mobile App Setup

### 1. Connect to Paper Trading Account

1. Open IBKR Mobile App
2. Log in with your paper trading account credentials
3. Make sure you're connected to **Paper Trading** (not Live Trading)

### 2. View Trades

- **Positions**: View all open positions
- **Orders**: See pending and filled orders
- **Activity**: Monitor trade activity in real-time
- **P&L**: Track profit/loss

### 3. What You Can Do

✅ **View all trades** placed by automated system
✅ **See positions** in real-time
✅ **Monitor P&L** and performance
✅ **View order history**
✅ **Place manual trades** (if needed)

## Automated System Behavior

The automated system will:
- ✅ Connect using Client ID 2 (won't conflict with mobile)
- ✅ Place orders autonomously
- ✅ Manage positions
- ✅ Run 24/7 on the server

## Testing the Setup

### 1. Start Automated Trading

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
pearlalgo trade auto --symbols MES MNQ
```

### 2. Open Mobile App

- Log into paper trading account
- You should see trades appearing in real-time
- No disconnection errors

### 3. Verify Both Are Connected

- Automated system: Check logs for "Connected" messages
- Mobile app: Should show account data and positions
- Both should work simultaneously

## Troubleshooting

### Mobile App Gets Kicked Out

**Problem**: Mobile app disconnects when automated system starts

**Solution**: 
- Verify Client ID is 2 in `.env` file
- Restart automated trading system
- Check IB Gateway is running on port 4002

### Can't See Trades on Mobile

**Problem**: Trades not showing on mobile app

**Solution**:
- Make sure both are connected to same paper trading account
- Refresh mobile app (pull down to refresh)
- Check automated system logs for order execution

### Connection Errors

**Problem**: "Another application is using this connection"

**Solution**:
- Verify Client ID 2 is set: `grep PEARLALGO_IB_CLIENT_ID .env`
- Restart IB Gateway
- Restart automated trading system

## Current Configuration

```bash
# .env file
PEARLALGO_IB_HOST=127.0.0.1
PEARLALGO_IB_PORT=4002          # Paper trading port
PEARLALGO_IB_CLIENT_ID=2         # Secondary session (compatible with mobile)
PEARLALGO_PROFILE=live
PEARLALGO_ALLOW_LIVE_TRADING=true
```

## Summary

✅ **Automated system** runs on server with Client ID 2
✅ **Mobile app** connects with Client ID 0 (main session)
✅ **Both can be active** simultaneously on paper trading
✅ **No conflicts** - you can monitor trades on your phone while system trades autonomously

## Next Steps

1. **Start automated trading** on server
2. **Open mobile app** and log into paper trading
3. **Monitor trades** in real-time
4. **Enjoy** watching your system trade while you're on the go! 📱

