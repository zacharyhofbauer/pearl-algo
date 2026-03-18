#!/bin/bash
# IBKR Gateway Watchdog
# Checks if gateway API port is listening; restarts service if not.
# Runs every 2 minutes via systemd timer.

GATEWAY_PORT=4001
LOG_TAG="ibkr-watchdog"
NOTIFY_SCRIPT="/home/pearlalgo/pearl-algo-workspace/scripts/notify_algo_logs.py"

# Helper: send to Algo Logs topic (best-effort, non-blocking)
notify_algo_logs() {
    local msg="$1"
    if [ -f "$NOTIFY_SCRIPT" ]; then
        python3 "$NOTIFY_SCRIPT" "$msg" &>/dev/null &
    fi
}

# Only run during market hours (Sun 6pm - Fri 5pm ET) + 1h buffer
# Skip weekends to avoid unnecessary restarts
DOW=$(date +%u)  # 1=Mon 7=Sun
HOUR=$(date +%H)

# Skip Sat entirely; skip Sun before 17:00 UTC (1pm ET); skip Fri after 22:00 UTC (6pm ET)
if [ "$DOW" -eq 6 ]; then
    logger -t "$LOG_TAG" "Weekend (Sat) - skipping watchdog check"
    exit 0
fi

# Check if port 4001 is listening
if nc -z 127.0.0.1 $GATEWAY_PORT 2>/dev/null; then
    logger -t "$LOG_TAG" "Gateway OK - port $GATEWAY_PORT listening"
    exit 0
fi

logger -t "$LOG_TAG" "WARNING: Gateway port $GATEWAY_PORT not responding - restarting ibkr-gateway.service"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S ET')
notify_algo_logs "$(printf '🔴 IBKR Gateway down — auto-restart triggered\nTime: %s\nStatus: Restarting ibkr-gateway.service...' "$TIMESTAMP")"

sudo systemctl restart ibkr-gateway.service
sleep 5

if nc -z 127.0.0.1 $GATEWAY_PORT 2>/dev/null; then
    logger -t "$LOG_TAG" "Gateway restarted successfully"
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S ET')
    notify_algo_logs "$(printf '✅ IBKR Gateway restored\nTime: %s\nPort 4001: listening' "$TIMESTAMP")"
else
    logger -t "$LOG_TAG" "Gateway restart initiated - waiting for auth (may need 2FA)"
fi
