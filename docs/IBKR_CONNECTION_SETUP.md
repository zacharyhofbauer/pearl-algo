# IBKR Account Setup & API Connection Guide

Complete guide to connect your IBKR account and enable API access for automated trading using Docker.

## Overview

IBKR doesn't use traditional "API keys" like other brokers. Instead, you:
1. Enable API access in your IBKR account settings
2. Run IB Gateway in Docker (headless, no GUI needed)
3. Connect to Gateway via socket connection (no API key needed)

## Step 1: Enable API Access in IBKR Account

### Via IBKR Web Portal

1. **Log in to IBKR Account Management:**
   - Go to https://www.interactivebrokers.com/
   - Log in with your account credentials

2. **Navigate to API Settings:**
   - Go to **Account Management** → **Settings** → **API Settings**
   - Or direct link: https://www.interactivebrokers.com/account-management/secure/api-settings

3. **Enable API Access:**
   - Check **"Enable ActiveX and Socket Clients"**
   - Check **"Read-Only API"** (recommended for safety)
   - **Socket Port**: Set to `4002` (default for Gateway)
   - **Trusted IPs**: Add your server IP address (or `127.0.0.1` for localhost)

4. **Save Settings:**
   - Click **"Save"** or **"Apply"**
   - Changes take effect immediately

### Important Notes:
- **Paper Trading Account**: If using paper trading, enable API on your paper account separately
- **Two-Factor Authentication**: The Docker Gateway container handles 2FA automatically if configured
- **IP Restrictions**: If you set trusted IPs, make sure your server IP is whitelisted

## Step 2: Configure Docker Environment

1. **Set Environment Variables in `.env` file:**
   ```bash
   cd /home/pearlalgo/pearlalgo-dev-ai-agents
   nano .env
   ```

   Add these lines:
   ```bash
   # IBKR Gateway Configuration
   IBKR_ACCOUNT_TYPE=paper  # or "live"
   IBKR_USERNAME=your_ibkr_username
   IBKR_PASSWORD=your_ibkr_password
   IBKR_READ_ONLY_API=true
   IBKR_SOCKET_PORT=4002
   
   # IBKR Connection Settings (for trading-bot container)
   IBKR_HOST=ib-gateway  # Docker service name
   IBKR_PORT=4002
   IBKR_CLIENT_ID=1
   IBKR_DATA_CLIENT_ID=2
   ```

2. **Save and exit** (Ctrl+X, then Y, then Enter)

## Step 3: Start IB Gateway in Docker

1. **Start IB Gateway container:**
   ```bash
   cd /home/pearlalgo/pearlalgo-dev-ai-agents
   docker-compose up -d ib-gateway
   ```

2. **Check Gateway Status:**
   ```bash
   docker-compose ps ib-gateway
   # Should show "Up" status
   ```

3. **View Gateway Logs:**
   ```bash
   docker-compose logs -f ib-gateway
   # Look for "API server listening on port 4002"
   # First startup may take 1-2 minutes
   ```

4. **Verify Port is Listening:**
   ```bash
   docker-compose exec ib-gateway nc -z localhost 4002 && echo "Port 4002 is open"
   ```

## Step 4: Configure Your Application

### Configuration File

Update `config/config.yaml`:

```yaml
data:
  provider: "ibkr"
  fallback:
    ibkr:
      host: "${IBKR_HOST:-ib-gateway}"
      port: "${IBKR_PORT:-4002}"
      client_id: "${IBKR_DATA_CLIENT_ID:-2}"
```

The application will automatically connect to the `ib-gateway` Docker service.

## Step 5: Test Your Connection

### Quick Test

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents

# Run validation script
python scripts/validate_setup.py

# Or run smoke test
python scripts/smoke_test_ibkr.py
```

### Expected Output

You should see:
```
✅ IB Gateway is reachable
✅ IBKR connection established
✅ Account type detected: paper
✅ Critical market data entitlements available
✅ SPY price: $XXX.XX
✅ Retrieved X options for SPY
```

## Step 6: Troubleshooting

### Issue: "Connection refused" or "Port not open"

**Solution:**
1. Check if Gateway container is running:
   ```bash
   docker-compose ps ib-gateway
   ```

2. Check Gateway logs for errors:
   ```bash
   docker-compose logs ib-gateway
   ```

3. Restart Gateway:
   ```bash
   docker-compose restart ib-gateway
   ```

### Issue: "Authentication failed" or "Login required"

**Solution:**
1. Verify credentials in `.env` file:
   ```bash
   grep IBKR_USERNAME .env
   grep IBKR_PASSWORD .env
   ```

2. Check Gateway logs for authentication errors:
   ```bash
   docker-compose logs ib-gateway | grep -i "auth\|login\|password"
   ```

3. If 2FA is enabled, you may need to check Gateway logs for 2FA prompts

### Issue: "API not enabled" or "Socket client not allowed"

**Solution:**
1. Go to IBKR Account Management → API Settings
2. Enable "Enable ActiveX and Socket Clients"
3. Save and restart Gateway:
   ```bash
   docker-compose restart ib-gateway
   ```

### Issue: "Trusted IP restriction"

**Solution:**
1. Check your server's public IP:
   ```bash
   curl ifconfig.me
   ```

2. Add this IP to "Trusted IPs" in IBKR API Settings
3. Or set to `0.0.0.0/0` for testing (less secure)
4. Restart Gateway:
   ```bash
   docker-compose restart ib-gateway
   ```

### Issue: "Container keeps restarting"

**Solution:**
1. Check detailed logs:
   ```bash
   docker-compose logs --tail=100 ib-gateway
   ```

2. Verify environment variables:
   ```bash
   docker-compose config | grep IBKR
   ```

3. Check if credentials are correct in `.env` file

### Issue: "No market data entitlements"

**Solution:**
- This is normal for paper accounts
- Some data may be delayed or unavailable
- Check entitlements with:
  ```bash
  python scripts/validate_setup.py
  ```

## Step 7: Start Trading System

Once connection is validated:

```bash
# Start both Gateway and trading bot
docker-compose up -d

# Or start just the trading bot (Gateway must be running)
docker-compose up -d trading-bot

# Check status
docker-compose ps

# View logs
docker-compose logs -f trading-bot
```

## Security Best Practices

1. **Use Read-Only API** when possible (for data-only access)
2. **Restrict IPs** to your server IP only
3. **Use Paper Account** for testing
4. **Don't commit credentials** - use `.env` file (already in `.gitignore`)
5. **Enable 2FA** on your IBKR account
6. **Monitor API usage** in IBKR account management

## Account Types

### Paper Trading Account
- **Port**: `4002` (Gateway)
- **Account ID**: Usually contains "DU" (e.g., "DU123456")
- **Free**: No cost, delayed data
- **Safe**: No real money at risk

### Live Trading Account
- **Port**: `4002` (Gateway) or `7496` (alternative)
- **Account ID**: Your actual account number
- **Real Money**: Real trades, real risk
- **Real-Time Data**: Requires market data subscriptions

## Docker Commands Reference

```bash
# Start IB Gateway
docker-compose up -d ib-gateway

# Start all services (Gateway + Trading Bot)
docker-compose up -d

# Check status
docker-compose ps

# View Gateway logs
docker-compose logs -f ib-gateway

# View trading bot logs
docker-compose logs -f trading-bot

# Restart Gateway
docker-compose restart ib-gateway

# Stop Gateway
docker-compose stop ib-gateway

# Stop all services
docker-compose down

# View Gateway logs (last 100 lines)
docker-compose logs --tail=100 ib-gateway

# Execute command in Gateway container
docker-compose exec ib-gateway sh
```

## Next Steps

1. ✅ Enable API access in IBKR account
2. ✅ Configure `.env` file with credentials
3. ✅ Start IB Gateway in Docker
4. ✅ Test connection
5. ✅ Start trading system
6. ✅ Monitor logs and alerts

## Additional Resources

- **IBKR API Documentation**: https://interactivebrokers.github.io/tws-api/
- **Docker Compose Documentation**: https://docs.docker.com/compose/
- **Project Documentation**: See `docs/` directory
