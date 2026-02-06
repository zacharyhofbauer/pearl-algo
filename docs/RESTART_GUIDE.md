# System Restart Guide

Quick reference for restarting Pearl Algo services.

---

## Recommended: Use pearl.sh

```bash
./pearl.sh restart        # Restart everything (Gateway + Agent + MFFU + Telegram + Chart + Tunnel)
./pearl.sh stop           # Stop everything
./pearl.sh start          # Start everything
./pearl.sh quick          # Check all services: GW | Agent | MFFU | TG | Chart | Tunnel
./pearl.sh status         # Detailed status view
```

## Individual Services

```bash
./pearl.sh agent restart          # Inception agent only
./pearl.sh mffu restart           # MFFU eval agent + API only
./pearl.sh chart restart          # Web app + inception API only (does NOT kill MFFU API)
./pearl.sh telegram restart       # Telegram handler only
./pearl.sh gateway restart        # IBKR Gateway only
./pearl.sh tunnel restart         # Cloudflare tunnel only
```

## MFFU-Specific

```bash
./pearl.sh mffu start             # Start MFFU agent + API server (port 8001)
./pearl.sh mffu stop              # Stop MFFU
./pearl.sh mffu status            # Check MFFU status
./pearl.sh mffu logs              # Tail MFFU agent log
./pearl.sh mffu api               # Start MFFU API server only (view data without trading)
```

## Manual Restarts (if pearl.sh doesn't work)

```bash
# Inception Agent
./scripts/lifecycle/agent.sh start --market NQ --background

# MFFU Agent
./scripts/lifecycle/mffu_eval.sh start --background

# Telegram Handler
./scripts/telegram/restart_command_handler.sh --background

# API Server (inception, port 8000)
python scripts/pearlalgo_web_app/api_server.py --market NQ --port 8000 &

# API Server (MFFU, port 8001)
PEARLALGO_STATE_DIR=data/agent_state/MFFU_EVAL python scripts/pearlalgo_web_app/api_server.py --market MNQ --port 8001 &
```

## Important Notes

- `pearl.sh restart` now includes MFFU in the start/stop cycle
- `pearl.sh chart restart` only kills the inception API (port 8000), NOT the MFFU API (port 8001)
- IBKR client IDs: inception=10/11, MFFU agent=50/51, inception chart=96, MFFU chart=97
- Secrets stored in `~/.config/pearlalgo/secrets.env` (Telegram, Tradovate, API keys)
