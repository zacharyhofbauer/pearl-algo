# System Restart Guide

Quick reference for restarting Pearl Algo services.

---

## Quick Commands

```bash
# Web App (pearlalgo.io)
cd ~/pearlalgo-dev-ai-agents/pearlalgo_web_app
npm run build && pkill -f "next-server"; sleep 2 && nohup npx next start -p 3001 > /tmp/next-server.log 2>&1 &

# Market Agent
cd ~/pearlalgo-dev-ai-agents
./scripts/lifecycle/agent.sh restart --market NQ --background

# Telegram Handler
./scripts/telegram/restart_command_handler.sh --background

# API Server (port 8000)
pkill -f "api_server.py"; sleep 2
nohup python scripts/pearlalgo_web_app/api_server.py --market NQ > /tmp/api-server.log 2>&1 &
```

---

## Web App (pearlalgo.io)

**Port:** 3001 (Cloudflare tunnel routes here)

### When to Restart
- After editing files in `pearlalgo_web_app/`
- After CSS/component changes
- After fixing bugs in the web UI

### How to Restart
```bash
cd ~/pearlalgo-dev-ai-agents/pearlalgo_web_app

# 1. Rebuild
npm run build

# 2. Kill old server
pkill -f "next-server"

# 3. Start on port 3001 (required for Cloudflare tunnel)
nohup npx next start -p 3001 > /tmp/next-server.log 2>&1 &

# 4. Verify
curl -s -o /dev/null -w "%{http_code}" http://localhost:3001
# Should return: 200
```

### Verify pearlalgo.io
```bash
curl -s -o /dev/null -w "%{http_code}" https://pearlalgo.io
# Should return: 200
```

---

## API Server (Backend)

**Port:** 8000

### When to Restart
- After editing `scripts/pearlalgo_web_app/api_server.py`
- After API endpoint changes

### How to Restart
```bash
cd ~/pearlalgo-dev-ai-agents

pkill -f "api_server.py"
sleep 2
nohup python scripts/pearlalgo_web_app/api_server.py --market NQ > /tmp/api-server.log 2>&1 &

# Verify
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/state
# Should return: 200
```

---

## Market Agent

### When to Restart
- After `config/config.yaml` changes
- After risk/strategy setting changes

### How to Restart
```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/lifecycle/agent.sh restart --market NQ --background

# Or via Telegram: /start → System → Restart Agent
```

### Check Status
```bash
ps aux | grep "market_agent.main" | grep -v grep
```

---

## Telegram Handler

### When to Restart
- After telegram handler code changes
- Usually auto-reloads

### How to Restart
```bash
./scripts/telegram/restart_command_handler.sh --background
```

---

## IBKR Gateway

### Check Status
```bash
ps aux | grep -i "ibkr\|ibcGateway" | grep -v grep
```

### Restart (if needed)
```bash
# Usually managed by IBC - check IBC docs
~/ibkr/ibc/scripts/ibcstart.sh
```

---

## Cloudflare Tunnel

**Config:** `~/.cloudflared/config.yml`

Routes:
- `/ws` → localhost:8000 (WebSocket)
- `/api/*` → localhost:8000 (API)
- Everything else → localhost:3001 (Web App)

### Check Status
```bash
ps aux | grep cloudflared | grep -v grep
systemctl status cloudflared-pearlalgo
```

### Restart (if needed)
```bash
sudo systemctl restart cloudflared-pearlalgo
```

---

## Status Check - All Services

```bash
echo "=== Web App (3001) ==="
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3001

echo "=== API Server (8000) ==="
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health

echo "=== Market Agent ==="
ps aux | grep "market_agent.main" | grep -v grep | wc -l

echo "=== Telegram Handler ==="
ps aux | grep "telegram_command_handler" | grep -v grep | wc -l

echo "=== IBKR Gateway ==="
ps aux | grep -i "ibcGateway" | grep -v grep | wc -l

echo "=== Cloudflare Tunnel ==="
ps aux | grep cloudflared | grep -v grep | wc -l

echo "=== pearlalgo.io ==="
curl -s -o /dev/null -w "%{http_code}\n" https://pearlalgo.io
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| pearlalgo.io not loading | Check Next.js on port 3001, not 3000 |
| API errors | Check api_server.py on port 8000 |
| Data stale (market open) | Restart market agent |
| Data stale (market closed) | Normal - no new bars |
| WebSocket disconnected | Check API server, restart if needed |

---

## Port Reference

| Service | Port | Notes |
|---------|------|-------|
| Web App (Next.js) | 3001 | Cloudflare routes here |
| API Server | 8000 | Backend API + WebSocket |
| IBKR Gateway | 4002 | TWS API port (paper trading) |

---

## Systemd Services (Optional)

For auto-start on reboot, install systemd services:

```bash
# Install services (requires sudo)
sudo ./scripts/systemd/install-services.sh

# Enable auto-start
sudo systemctl enable ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-webapp pearlalgo-telegram

# Start all services
sudo systemctl start ibkr-gateway
sudo systemctl start pearlalgo-agent pearlalgo-api pearlalgo-webapp pearlalgo-telegram

# Check status
sudo systemctl status pearlalgo-*

# View logs
journalctl -u pearlalgo-agent -f
```

---

## Health Monitoring

Automated monitoring sends Telegram alerts when services go down.

### Cron Setup (Simple)
```bash
./scripts/monitoring/setup-cron.sh
# Runs health check every 5 minutes
```

### Systemd Timer (Alternative)
```bash
sudo systemctl enable --now pearlalgo-monitor.timer
# View results: journalctl -u pearlalgo-monitor --since '1 hour ago'
```

### Manual Check
```bash
.venv/bin/python scripts/monitoring/health_check.py
```

Alerts are sent via Telegram when:
- Agent stops or pauses
- Data becomes stale (>15 min)
- API server stops responding
- Gateway goes down

---

## IBKR Gateway Notes

**Config file:** `~/ibkr/ibc/config-auto.ini`

| Setting | Value | Description |
|---------|-------|-------------|
| ReadOnlyApi | yes | Data only, no trading |
| TradingMode | paper | Paper trading account |

To enable trading orders, change `ReadOnlyApi=no` and restart gateway.
