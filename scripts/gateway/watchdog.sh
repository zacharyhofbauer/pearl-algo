#!/bin/bash
# IBKR Gateway Watchdog
# Checks if gateway API port is listening; prefers a warm IBC restart when
# possible, and only falls back to a cold systemd restart when necessary.
# Runs every 2 minutes via systemd timer.

GATEWAY_PORT=4001
LOG_TAG="ibkr-watchdog"
NOTIFY_SCRIPT="/home/pearlalgo/projects/pearl-algo/scripts/notify_algo_logs.py"
STATE_DIR="/home/pearlalgo/var/pearl-algo/state/watchdog"
STATE_FILE="$STATE_DIR/ibkr_gateway_watchdog_state.json"
RESTART_COOLDOWN_SECONDS=600

# Helper: send to Algo Logs topic (best-effort, non-blocking)
notify_algo_logs() {
    local msg="$1"
    if [ -f "$NOTIFY_SCRIPT" ]; then
        python3 "$NOTIFY_SCRIPT" "$msg" &>/dev/null &
    fi
}

mkdir -p "$STATE_DIR"

load_state() {
    if [ -f "$STATE_FILE" ]; then
        cat "$STATE_FILE"
    else
        echo '{}'
    fi
}

write_state() {
    local payload="$1"
    printf '%s\n' "$payload" > "$STATE_FILE"
}

STATE_JSON="$(load_state)"
LAST_ALERT_TYPE="$(printf '%s' "$STATE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("last_alert_type",""))')"
LAST_ALERT_TS="$(printf '%s' "$STATE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(int(d.get("last_alert_ts",0) or 0))')"
NOW_TS="$(date +%s)"

# Only run during market hours (Sun 6pm - Fri 5pm ET) + 1h buffer
# Skip weekends to avoid unnecessary restarts
DOW=$(date +%u)  # 1=Mon 7=Sun
# Skip Sat entirely; skip Sun before 17:00 UTC (1pm ET); skip Fri after 22:00 UTC (6pm ET)
if [ "$DOW" -eq 6 ]; then
    logger -t "$LOG_TAG" "Weekend (Sat) - skipping watchdog check"
    exit 0
fi

# Check if port 4001 is listening
if nc -z 127.0.0.1 $GATEWAY_PORT 2>/dev/null; then
    logger -t "$LOG_TAG" "Gateway OK - port $GATEWAY_PORT listening"
    if [ "$LAST_ALERT_TYPE" != "ok" ]; then
        write_state "{\"last_alert_type\":\"ok\",\"last_alert_ts\":$NOW_TS}"
    fi
    exit 0
fi

logger -t "$LOG_TAG" "WARNING: Gateway port $GATEWAY_PORT not responding - restarting gateway"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S ET')

SHOULD_ALERT=1
if [ "$LAST_ALERT_TYPE" = "down" ] && [ $((NOW_TS - LAST_ALERT_TS)) -lt "$RESTART_COOLDOWN_SECONDS" ]; then
    SHOULD_ALERT=0
fi

if [ "$SHOULD_ALERT" -eq 1 ]; then
    notify_algo_logs "$(printf '🔴 IBKR Gateway down — restart triggered\nTime: %s\nStatus: Trying warm restart first, cold restart only if needed.' "$TIMESTAMP")"
    write_state "{\"last_alert_type\":\"down\",\"last_alert_ts\":$NOW_TS}"
fi

/home/pearlalgo/projects/pearl-algo/scripts/gateway/gateway.sh restart
sleep 5

if nc -z 127.0.0.1 $GATEWAY_PORT 2>/dev/null; then
    logger -t "$LOG_TAG" "Gateway restarted successfully"
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S ET')
    if [ "$LAST_ALERT_TYPE" != "restored" ] || [ $((NOW_TS - LAST_ALERT_TS)) -ge "$RESTART_COOLDOWN_SECONDS" ]; then
        notify_algo_logs "$(printf '✅ IBKR Gateway restored\nTime: %s\nPort 4001: listening' "$TIMESTAMP")"
    fi
    write_state "{\"last_alert_type\":\"restored\",\"last_alert_ts\":$(date +%s)}"
else
    logger -t "$LOG_TAG" "Gateway restart initiated - waiting for auth (may need 2FA)"
    write_state "{\"last_alert_type\":\"waiting_auth\",\"last_alert_ts\":$(date +%s)}"
fi
