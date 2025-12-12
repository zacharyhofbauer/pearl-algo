# Quick Start: IBKR Connection (Docker Only)

## TL;DR - Fastest Path to Connect

### 1. Enable API in IBKR Account (2 minutes)
1. Log in to https://www.interactivebrokers.com/
2. Go to **Account Management** → **Settings** → **API Settings**
3. Enable **"Enable ActiveX and Socket Clients"**
4. Set **Socket Port** to `4002`
5. Add your server IP to **Trusted IPs** (or use `127.0.0.1` for localhost)
6. Click **Save**

### 2. Configure Docker Environment
```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents

# Edit .env file
nano .env

# Add these lines:
IBKR_USERNAME=zachofbauer  
IBKR_PASSWORD=Zqfa89HqDsr9jy
IBKR_ACCOUNT_TYPE=paper
IBKR_READ_ONLY_API=true
IBKR_HOST=ib-gateway
IBKR_PORT=4002
```

### 3. Start IB Gateway

**First, fix Docker permissions (one-time):**
```bash
sudo usermod -aG docker $USER
# Then log out and back in, OR run:
newgrp docker
```

**Then start Gateway:**
```bash
docker compose up -d ib-gateway

# Check logs
docker compose logs -f ib-gateway
```

### 4. Test Connection
```bash
python scripts/validate_setup.py
```

### 5. Start Trading System
```bash
# Start all services
docker compose up -d

# Or just trading bot (Gateway must be running)
docker compose up -d trading-bot
```

## Common Issues

**"Connection refused"**
→ Gateway not running. Run `docker compose up -d ib-gateway`

**"Authentication failed"**
→ Check credentials in `.env` file and Gateway logs

**"API not enabled"**
→ Enable in IBKR Account Management → API Settings

**"Container keeps restarting"**
→ Check logs: `docker compose logs ib-gateway`

**"Permission denied" (Docker)**
→ Run: `sudo usermod -aG docker $USER` then log out/in or run `newgrp docker`

## Full Guide

See `docs/IBKR_CONNECTION_SETUP.md` for complete instructions.
